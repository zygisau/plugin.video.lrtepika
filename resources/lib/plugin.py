# MIT License
"""Kodi plugin bootstrap.

Navigation, search, and playback routes are implemented in a later slice.
This module only provides a safe empty directory so the add-on can load.
"""


def run(argv):
    """Start the plugin with Kodi's `sys.argv` vector."""
    handle = int(argv[1]) if len(argv) > 1 else -1
    import xbmcplugin

    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
