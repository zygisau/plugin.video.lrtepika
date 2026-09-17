# LRT Epika Kodi add-on

Unofficial Kodi 20+ video add-on for [LRT Epika](https://epika.lrt.lt), the Lithuanian National Radio and Television streaming service.

This repository is **not affiliated with or endorsed by LRT**. All catalog and stream content belongs to LRT.

## Status

Version `0.2.0` adds an optional, **default-disabled** Send-to-Epika listener. Version `0.1.0` remains the first catalog/playback release of `plugin.video.lrtepika`.

Implemented in the current branch slice:

- Add-on identity, MIT license, and clean ZIP packaging
- Thin `requests` API client and pure directory mapping helpers
- Root navigation: Featured, Movies, Series, and Search
- Offset pagination and serial → season → episode drill-down
- Search keyboard, typed VOD / SERIAL / EPISODE results, and recent-term history
- Playback: DASH / Widevine, with non-DRM HLS fallback
- Optional authenticated `POST /v1/send` service that resolves public Epika URLs and dispatches existing plugin play/browse routes

Search history is a newest-first JSON list saved as `search_history.json` in the add-on profile (`special://profile/addon_data/plugin.video.lrtepika/` on Kodi).

Live public API notes used by the client (documented deviations from the retired OpenAPI file):

- Catalog and search responses use `{ "meta": { totalCount, firstResult, maxResults }, "items": [...] }`
- Search `meta.totalCount` is the current page size, not a global result total; pagination uses a 31-item lookahead
- Section payloads expose `elements`, not `items`
- Playable movies are typed `VOD` (playlist `videoType` remains `MOVIE`)
- Episode items still request `videoType=EPISODE` first; live Epika currently 404s that type and serves the same assets with `videoType=MOVIE`, so playback retries `MOVIE`
- Playlist DRM objects use uppercase keys such as `WIDEVINE.src`
- Season pages 404 `GET /products/vods/{id}` and are confirmed with `GET /products/vods/seasons/{id}/detail`

## Requirements

- Kodi 20 (Nexus) or newer
- [script.module.requests](https://kodi.wiki/view/Add-on:Requests)
- [inputstream.adaptive](https://kodi.wiki/view/Add-on:InputStream_Adaptive) for DASH and DRM titles
- A working Widevine CDM on the device for protected titles
- Network access to `https://epika.lrt.lt/api`

Anonymous browsing of the public catalog is supported. Accounts, cookies, bookmarks, concerts, and search suggestions are out of scope for 0.2.0.

## Artwork

`resources/images/icon.png` and `resources/images/fanart.jpg` are generic placeholders inherited from the old example plugin (a clapperboard icon and abstract bokeh fanart). They are **not** official LRT branding. No substitute LRT artwork was available under a known license, so binaries were not fabricated.

## Send to Kodi (iPhone Shortcut)

The add-on can expose one authenticated LAN endpoint. It is **off by default**, binds **127.0.0.1** only, and ships **without** an access token. Do not enable it, change the bind address, or punch a firewall hole until you are ready to configure a phone on a trusted home LAN.

Use this only on a **trusted WPA2/WPA3 home Wi-Fi**. Do **not** port-forward, expose the listener to the internet, or put it behind a public tunnel. HTTP Bearer tokens can be stolen on an open or guest network; rotate the token after a lost phone or suspected leak.

### Kodi settings

1. Generate a token of at least 32 random URL-safe bytes, for example:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. In LRT Epika add-on settings → Send to Kodi:
   - Enable Send to Kodi
   - Bind address: this device's LAN IPv4 (not `0.0.0.0`; leave `127.0.0.1` if you only want loopback tests)
   - Port: `8765` unless that port is taken
   - Access token: paste the generated value (the field is hidden)
3. Keep the token out of URLs, screenshots, and shared Shortcut files. After rotating it, update the Shortcut header.

### Shortcut contract

Create an iPhone Shortcut with “Show in Share Sheet”, accepting URLs / Safari web pages:

- URL: `http://raspberrypi.local:8765/v1/send` (or `http://<lan-ipv4>:8765/v1/send`)
- Method: `POST`
- Header `Authorization`: `Bearer REPLACE_WITH_RANDOM_TOKEN`
- Header `Content-Type`: `application/json`
- JSON body field `url`: Shortcut Input

Equivalent request:

```bash
curl --fail-with-body \
  -X POST \
  -H 'Authorization: Bearer REPLACE_WITH_RANDOM_TOKEN' \
  -H 'Content-Type: application/json' \
  --data '{"url":"https://epika.lrt.lt/vaidybiniai-filmai,268/adomas-nori-buti-zmogumi,432486"}' \
  http://127.0.0.1:8765/v1/send
```

`GET /v1/health` uses the same Bearer token and does not query Epika.

A **202** response means the add-on **accepted dispatch** (play or open the matching directory). It does **not** mean the video started, DRM succeeded, or the title is watchable. Later playlist, geo, login, or decoder errors still appear in Kodi.

Movies and episodes open through `Player.Open` on the existing `route=play` plugin URL. Serials open the seasons directory; seasons open that season’s episodes. The listener never guesses an episode and never fetches streams, licenses, or cookies.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
python3 -m compileall -q main.py service.py resources/lib tools
python3 tools/build.py
```

Live read-only API checks are opt-in:

```bash
LRT_EPIKA_LIVE=1 .venv/bin/pytest -q -m live
```

The build writes a deterministic archive:

```text
dist/plugin.video.lrtepika-0.2.0.zip
└── plugin.video.lrtepika/
```

Install that ZIP in Kodi. Do not copy a Git working tree into `~/.kodi/addons`.

## License

MIT. See `LICENSE.txt`.
