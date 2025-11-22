# Copyright (C) 2023, Roman V. M.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
Example video plugin that is compatible with Kodi 20.x "Nexus" and above
"""
# Add resources/lib directory to Python path for third-party packages
import sys
from pathlib import Path

_addon_dir = Path(__file__).resolve().parent
_lib_path = _addon_dir / 'resources' / 'lib'
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

import json
from urllib.parse import urlencode, parse_qsl

import requests
from resources.lib.httpx._config import UNSET
from resources.lib.lrt_epika_api_client.types import Unset
from resources.lib.lrt_epika_api_client.models.category_type import CategoryType
from resources.lib.lrt_epika_api_client.models.category import Category
from resources.lib.lrt_epika_api_client.models.movie_type import MovieType
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
from xbmcaddon import Addon
from xbmcvfs import translatePath

import urllib.request, json 
from typing import TypedDict, Literal, NotRequired

class Tenant(TypedDict):
    uid: str

class Image(TypedDict):
    url: str
    templateUrl: str

class Images(TypedDict):
    NotRequired["16x9"]: list[Image]
    NotRequired["1x1"]: list[Image]
    NotRequired["3x4"]: list[Image]

class MainCategory(TypedDict):
    id: int
    name: str
    seoName: str
    seoNameSingular: str
    slug: str
    adult: bool
    type: str

class DisplaySchedule(TypedDict):
    since: str  # ISO 8601 datetime
    till: NotRequired[str]  # ISO 8601 datetime, optional
    type: str

class VodItem(TypedDict):
    type_: str
    id: int
    publicUid: str
    title: str
    lead: str
    rating: NotRequired[int]
    ratingEmbedded: bool
    type: str
    uhd: bool
    displayActive: bool
    since: str
    till: NotRequired[str]
    images: Images
    mainCategory: MainCategory
    displaySchedules: list[DisplaySchedule]
    webUrl: str
    trailer: bool
    titleTreatmentImages: dict  # Empty dict in example
    tenant: Tenant
    payable: bool
    duration: int
    year: int
    originalTitle: NotRequired[str]
    hd: bool
    showRecommendations: bool
    loginRequired: bool
    artworks: NotRequired[Images]
    audio: bool
    video: bool
    kmsManagement: bool
    slug: str

class SectionElement(TypedDict):
    id: int
    since: str  # ISO 8601 datetime
    item: VodItem
    rank: int

class Section(TypedDict):
    id: int
    title: str
    type: str
    images: dict  # Empty dict in example
    webUrl: str
    tenant: Tenant
    contentType: str
    layout: str
    tilesAspect: str
    tilesSize: str
    elements: list[SectionElement]
    banner: dict  # Empty dict in example
    showTitle: bool
    presentationTime: int
    showTileTitle: bool
    tilesActivity: str
    slug: str

SectionList = list[Section]


# Get the plugin url in plugin:// notation.
URL = sys.argv[0]
# Get a plugin handle as an integer number.
HANDLE = int(sys.argv[1])
# Get the addon base path. Here we use pathlib.Path for convenient path handling
ADDON_PATH = Path(translatePath(Addon().getAddonInfo('path')))
ICONS_DIR = ADDON_PATH / 'resources' / 'images' / 'icons'
FANART_DIR = ADDON_PATH / 'resources' / 'images' / 'fanart'

# Public domain movies are from https://publicdomainmovie.net
# Here we use a hardcoded list of movies from a JSON file simply for demonstrating purposes
# In a "real life" plugin you will need to get info and links to video files/streams
# from some website or online service.

MOVIES_INFO_PATH = ADDON_PATH / 'movies.json'

from resources.lib.lrt_epika_api_client import Client
from resources.lib.lrt_epika_api_client.api.categories import get_categories
from resources.lib.lrt_epika_api_client.api.products import get_season_episodes, get_serial_seasons, get_vods

client = Client(base_url="https://epika.lrt.lt/api")

def get_url(**kwargs):
    """
    Create a URL for calling the plugin recursively from the given set of keyword arguments.

    :param kwargs: "argument=value" pairs
    :return: plugin call URL
    :rtype: str
    """
    return f'{URL}?{urlencode(kwargs)}'


def get_categories_internal() -> list[Category]:
    """
    Get the list of video genres

    Here you can insert some code that retrieves
    the list of video sections (in this case movie genres) from some site or API.

    :return: The list of video genres
    :rtype: list
    """
    data = [
            Category(268, "Filmai", 'filmai', False, CategoryType.VOD, 'filmai', 'filmas'),
            Category(304, "Serialai", 'serialai', False, CategoryType.VOD, 'serialai', 'serialas'),
    ]
    return data

def get_sub_categories_internal(category_id: int):
    """
    Get the list of video genres

    Here you can insert some code that retrieves
    the list of video sections (in this case movie genres) from some site or API.

    :return: The list of video genres
    :rtype: list
    """
    data = get_categories.sync(client=client, main_category_id=category_id)
    return data

def get_vods_internal(category_id: int, subcategory_id: int):
    data = get_vods.sync(client=client, main_category_id=[category_id], category_id=[subcategory_id], max_results=100)
    return data
    
def get_sub_category_internal(subcategory_id: int) -> Category:
    return Category(0, "Not implemented", 'unknown', False, CategoryType.VOD, 'unknown', 'unknown')

def get_videos(genre_index) -> list[VodItem]:
    """
    Get the list of videofiles/streams.

    Here you can insert some code that retrieves
    the list of video streams in the given section from some site or API.

    :param genre_index: genre index
    :type genre_index: int
    :return: the list of videos in the category
    :rtype: list
    """
    # https://epika.lrt.lt/api/products/vods?firstResult=0&maxResults=100&mainCategoryId[]=<ID>&lang=LIT&platform=BROWSER with <ID> being genre_index
    with urllib.request.urlopen(f"https://epika.lrt.lt/api/products/vods?firstResult=0&maxResults=100&mainCategoryId[]={genre_index}&lang=LIT&platform=BROWSER") as url:
        data = json.loads(url.read().decode())
        return data['items']

def get_series_internal(serial_id: int):
    data = get_serial_seasons.sync(client=client, serial_id=serial_id)
    return data

def list_categories():
    """
    Create the list of movie genres in the Kodi interface.
    """
    # Set plugin category. It is displayed in some skins as the name
    # of the current section.
    xbmcplugin.setPluginCategory(HANDLE, 'Public Domain Movies')
    # Set plugin content. It allows Kodi to select appropriate views
    # for this type of content.
    xbmcplugin.setContent(HANDLE, 'movies')
    # Get movie genres
    categories = get_categories_internal()
    if not categories:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Failed to get categories',
            xbmcgui.NOTIFICATION_ERROR
        )
        return
    # Iterate through genres
    for index, category in enumerate(categories):
        # Create a list item with a text label.
        list_item = xbmcgui.ListItem(label=category.name)
        # Set images for the list item.
        # Convert Path objects to str because Kodi API accepts only str.
        # list_item.setArt({
            # 'icon': str(ICONS_DIR / genre_info['icon']),
            # 'fanart': str(FANART_DIR / genre_info['fanart']),
        # })
        # Set additional info for the list item using its InfoTag.
        # InfoTag allows to set various information for an item.
        # For available properties and methods see the following link:
        # https://codedocs.xyz/xbmc/xbmc/classXBMCAddon_1_1xbmc_1_1InfoTagVideo.html
        # 'mediatype' is needed for a skin to display info for this ListItem correctly.
        info_tag = list_item.getVideoInfoTag()
        info_tag.setMediaType('video')
        info_tag.setTitle(category.name)
        info_tag.setGenres([category.name])
        # Create a URL for a plugin recursive call.
        # Example: plugin://plugin.video.example/?action=listing&category=0
        url = get_url(action='categories', category=category.id)
        # is_folder = True means that this item opens a sub-list of lower level items.
        is_folder = True
        # Add our item to the Kodi virtual folder listing.
        xbmcplugin.addDirectoryItem(HANDLE, url, list_item, is_folder)
    # Add sort methods for the virtual folder items
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    # Finish creating a virtual folder.
    xbmcplugin.endOfDirectory(HANDLE)

def list_sub_categories(category_id: int):
    xbmcplugin.setPluginCategory(HANDLE, 'Public Domain Movies')
    xbmcplugin.setContent(HANDLE, 'movies')
    subcategories = get_sub_categories_internal(category_id)
    
    if not subcategories:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Failed to get sub-categories',
            xbmcgui.NOTIFICATION_ERROR
        )
        return
    
    for index, subcategory in enumerate(subcategories):
        list_item = xbmcgui.ListItem(label=subcategory.name)

        info_tag = list_item.getVideoInfoTag()
        info_tag.setMediaType('video')
        info_tag.setTitle(subcategory.name)
        info_tag.setGenres([subcategory.name])
        url = get_url(action='listing', category=category_id, subcategory=subcategory.id)
        is_folder = True
        xbmcplugin.addDirectoryItem(HANDLE, url, list_item, is_folder)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.endOfDirectory(HANDLE)


def list_videos(category_id: int, subcategory_id: int):
    page = get_vods_internal(category_id, subcategory_id)
    subcategory = get_sub_category_internal(subcategory_id)
    # Set plugin category. It is displayed in some skins as the name
    # of the current section.
    xbmcplugin.setPluginCategory(HANDLE, subcategory.name)
    # Set plugin content. It allows Kodi to select appropriate views
    # for this type of content.
    xbmcplugin.setContent(HANDLE, 'movies')
    # Get the list of videos in the category.
    # Iterate through videos.
    
    if not page:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Failed to get videos',
            xbmcgui.NOTIFICATION_ERROR
        )
        return
    
    videos = page.items
    if not videos:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'No videos found in this category',
            xbmcgui.NOTIFICATION_INFO
        )
        return

    for i in range(len(videos)):
        video = videos[i]
        
        # Create a list item with a text label
        list_item = xbmcgui.ListItem(label=video.title)
        # Set graphics (thumbnail, fanart, banner, poster, landscape etc.) for the list item.
        # Here we use only poster for simplicity's sake.
        # In a real-life plugin you may need to set multiple image types.
        
        list_item.setArt({'poster': f'https:{video.images.field_16x9[0].url}'}) # type: ignore
        # Set additional info for the list item via InfoTag.
        # 'mediatype' is needed for skin to display info for this ListItem correctly.
        info_tag = list_item.getVideoInfoTag()
        info_tag.setMediaType('movie')
        info_tag.setTitle(video.title)
        # log
        info_tag.setGenres(["video.main_category.name"])
        info_tag.setPlot("video.lead")
        info_tag.setYear(video.year)
        # Set 'IsPlayable' property to 'true'.
        # This is mandatory for playable items!
        list_item.setProperty('IsPlayable', 'true')
        # Create a URL for a plugin recursive call.
        # Example: plugin://plugin.video.example/?action=play&video=https%3A%2F%2Fia600702.us.archive.org%2F3%2Fitems%2Firon_mask%2Firon_mask_512kb.mp4
        if video.type_ == MovieType.MOVIE:
            url = get_url(action='play', video=video.id)
            # Add the list item to a virtual Kodi folder.
            # is_folder = False means that this item won't open any sub-list.
            is_folder = False
        else:
            url = get_url(action='serial', category=category_id, subcategory=subcategory_id, video_id=video.id)
            is_folder = True
        # Add our item to the Kodi virtual folder listing.
        xbmcplugin.addDirectoryItem(HANDLE, url, list_item, is_folder)
    # Add sort methods for the virtual folder items
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
    # Finish creating a virtual folder.
    xbmcplugin.endOfDirectory(HANDLE)


def list_episodes(serial_id: int, season_id: int):
    """
    List episodes in a series season
    """
    xbmcplugin.setPluginCategory(HANDLE, 'Episodes')
    xbmcplugin.setContent(HANDLE, 'movies')
    
    season_data = get_season_episodes.sync(client=client, serial_id=serial_id, season_id=season_id)
    if not season_data:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Failed to get episodes',
            xbmcgui.NOTIFICATION_ERROR
        )
        return
    
    for episode in season_data:
        list_item = xbmcgui.ListItem(label=episode.title)
        info_tag = list_item.getVideoInfoTag()
        info_tag.setMediaType('movie')
        info_tag.setTitle(episode.title)
        url = get_url(action='play', video=episode.id)
        is_folder = False
        list_item.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(HANDLE, url, list_item, is_folder)
    
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.endOfDirectory(HANDLE)
    

def list_series(category_id: int, subcategory_id: int, video_id: int):
    """
    List series episodes
    """
    subcategory = get_sub_category_internal(subcategory_id)
    xbmcplugin.setPluginCategory(HANDLE, subcategory.name)
    xbmcplugin.setContent(HANDLE, 'movies')
    
    series = get_series_internal(video_id)
    
    if not series:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Failed to get series info',
            xbmcgui.NOTIFICATION_ERROR
        )
        return
    
    for season in series:
        list_item = xbmcgui.ListItem(label=season.title)
        info_tag = list_item.getVideoInfoTag()
        info_tag.setMediaType('movie')
        info_tag.setTitle(season.title)
        # this will be another folder
        url = get_url(action='episodes', serial_id=video_id, season_id=season.id)
        is_folder = True
        xbmcplugin.addDirectoryItem(HANDLE, url, list_item, is_folder)
        
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.endOfDirectory(HANDLE)

def play_video(path):
    """
    Play a video by the provided path.

    :param path: Fully-qualified video URL
    :type path: str
    """
    # Create a playable item with a path to play.
    # offscreen=True means that the list item is not meant for displaying,
    # only to pass info to the Kodi player
    play_item = xbmcgui.ListItem(offscreen=True)
    play_item.setPath(path)
    # Pass the item to the Kodi player.
    xbmcplugin.setResolvedUrl(HANDLE, True, listitem=play_item)


# Addon info
ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_PATH = ADDON.getAddonInfo('path')

# API Configuration
BASE_URL = "https://epika.lrt.lt/api"
TENANT_UID = "Lh8t"
PLATFORM = "BROWSER"
LANG = "LIT"
class LRTEpikaAPI:
    """API client for LRT Epika"""
    
    @staticmethod
    def get_categories():
        """Get available categories"""
        url = f"{BASE_URL}/items/categories"
        params = {"lang": LANG, "platform": PLATFORM}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            xbmc.log(f"LRT Epika: Error getting categories: {e}", xbmc.LOGERROR)
            return []
    
    @staticmethod
    def get_video_info(video_id):
        """Get video information"""
        url = f"{BASE_URL}/products/vods/{video_id}"
        params = {"lang": LANG, "platform": PLATFORM}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            xbmc.log(f"LRT Epika: Error getting video info: {e}", xbmc.LOGERROR)
            return None
    
    @staticmethod
    def get_playlist(video_id, video_type="MOVIE"):
        """Get playlist with stream URLs"""
        url = f"{BASE_URL}/products/{video_id}/videos/playlist"
        params = {
            "videoType": video_type,
            "platform": PLATFORM,
            "tenantUid": TENANT_UID
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            xbmc.log(f"LRT Epika: Error getting playlist: {e}", xbmc.LOGERROR)
            return None


def play_video_ai(video_id, video_type='MOVIE'):
    """Play a video with DRM support"""
    xbmc.log(f"LRT Epika: Attempting to play video {video_id}", xbmc.LOGINFO)
    
    # Get playlist info
    playlist_data = LRTEpikaAPI.get_playlist(video_id, video_type)
    
    if not playlist_data:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Failed to get stream information',
            xbmcgui.NOTIFICATION_ERROR
        )
        return
    
    # Extract stream URLs
    sources = playlist_data.get('sources', {})
    drm = playlist_data.get('drm', {})
    
    # Prefer DASH for DRM support
    dash_url = None
    if 'DASH' in sources and sources['DASH']:
        dash_url = sources['DASH'][0].get('src', '')
        if dash_url.startswith('//'):
            dash_url = 'https:' + dash_url
    
    if not dash_url:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'No DASH stream available',
            xbmcgui.NOTIFICATION_ERROR
        )
        return
    
    # Get Widevine license URL
    widevine_url = drm.get('WIDEVINE', {}).get('src', '')
    
    xbmc.log(f"LRT Epika: DASH URL: {dash_url}", xbmc.LOGINFO)
    xbmc.log(f"LRT Epika: Widevine URL: {widevine_url}", xbmc.LOGINFO)
    
    # Create play item
    play_item = xbmcgui.ListItem(path=dash_url)
    
    # Get video info for metadata
    video_info = LRTEpikaAPI.get_video_info(video_id)
    if video_info:
        info_tag = play_item.getVideoInfoTag()
        info_tag.setTitle(video_info.get('title', 'Unknown'))
        info_tag.setPlot(video_info.get('description', ''))
        info_tag.setDuration(video_info.get('duration', 0))
    
    # Configure inputstream.adaptive for DRM playback
    play_item.setProperty('inputstream', 'inputstream.adaptive')
    play_item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
    
    # # Limit to 720p for better Raspberry Pi performance
    # play_item.setProperty('inputstream.adaptive.max_resolution_width', '1280')
    # play_item.setProperty('inputstream.adaptive.max_resolution_height', '720')
    
    # # Force software decoding on Raspberry Pi to avoid DRMPRIME issues
    # play_item.setProperty('inputstream.adaptive.stream_selection_type', 'adaptive')
    # play_item.setMimeType('application/dash+xml')
    
    if widevine_url:
        # DRM configuration with proper headers
        license_headers = 'Content-Type=application/octet-stream'
        
        # Add cookies if configured
        cookie_string = ADDON.getSetting('cookies')
        if cookie_string:
            license_headers += f'&Cookie={cookie_string}'
        
        # License key format: URL|headers|post_data|response_data
        license_key = f'{widevine_url}|{license_headers}|R{{SSM}}|'
        
        play_item.setProperty('inputstream.adaptive.license_type', 'com.widevine.alpha')
        play_item.setProperty('inputstream.adaptive.license_key', license_key)
        xbmc.log(f"LRT Epika: License key configured", xbmc.LOGINFO)
    else:
        xbmc.log("LRT Epika: No DRM license URL found", xbmc.LOGWARNING)
    
    
    # Add subtitles if available
    subtitles = playlist_data.get('subtitles', [])
    if subtitles:
        subtitle_urls = []
        for sub in subtitles:
            url = sub.get('url', '')
            if url.startswith('//'):
                url = 'https:' + url
            subtitle_urls.append(url)
        
        if subtitle_urls:
            play_item.setSubtitles(subtitle_urls)
            xbmc.log(f"LRT Epika: Added {len(subtitle_urls)} subtitle(s)", xbmc.LOGINFO)
    
    # Play the video
    xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, play_item)


def router(paramstring):
    """
    Router function that calls other functions
    depending on the provided paramstring

    :param paramstring: URL encoded plugin paramstring
    :type paramstring: str
    """
    # Parse a URL-encoded paramstring to the dictionary of
    # {<parameter>: <value>} elements
    params = dict(parse_qsl(paramstring))
    # Check the parameters passed to the plugin
    if not params:
        # If the plugin is called from Kodi UI without any parameters,
        # display the list of video categories
        list_categories()
    elif params['action'] == 'categories':
        # Display the list of categories (genres)
        list_sub_categories(params['category'])
    elif params['action'] == 'listing':
        # Display the list of videos in a provided category.
        list_videos(int(params['category']), int(params['subcategory']))
    elif params['action'] == 'serial':
        list_series(int(params['category']), int(params['subcategory']), int(params['video_id']))
    elif params['action'] == 'episodes':
        # Display the list of episodes in a provided series season.
        list_episodes(int(params['serial_id']), int(params['season_id']))
    elif params['action'] == 'play':
        # Play a video from a provided URL.
        play_video_ai(params['video'])
    else:
        # If the provided paramstring does not contain a supported action
        # we raise an exception. This helps to catch coding errors,
        # e.g. typos in action names.
        raise ValueError(f'Invalid paramstring: {paramstring}!')


if __name__ == '__main__':
    # Call the router function and pass the plugin call parameters to it.
    # We use string slicing to trim the leading '?' from the plugin call paramstring
    router(sys.argv[2][1:])
