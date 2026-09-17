# LRT Epika Kodi add-on

Unofficial Kodi 20+ video add-on for [LRT Epika](https://epika.lrt.lt), the Lithuanian National Radio and Television streaming service.

This repository is **not affiliated with or endorsed by LRT**. All catalog and stream content belongs to LRT.

## Status

Version `0.1.0` is the first fixed release of `plugin.video.lrtepika`.

Implemented in the current branch slice:

- Add-on identity, MIT license, and clean ZIP packaging
- Thin `requests` API client and pure directory mapping helpers
- Root navigation: Featured, Movies, Series, and a Search placeholder
- Offset pagination and serial → season → episode drill-down
- Playback: DASH / Widevine, with non-DRM HLS fallback

Live public API notes used by the client (documented deviations from the retired OpenAPI file):

- Catalog and search responses use `{ "meta": { totalCount, firstResult, maxResults }, "items": [...] }`
- Section payloads expose `elements`, not `items`
- Playable movies are typed `VOD` (playlist `videoType` remains `MOVIE`)
- Playlist DRM objects use uppercase keys such as `WIDEVINE.src`

Still arriving in later slices of this branch:

- Search keyboard, typed results, and profile search history

## Requirements

- Kodi 20 (Nexus) or newer
- [script.module.requests](https://kodi.wiki/view/Add-on:Requests)
- [inputstream.adaptive](https://kodi.wiki/view/Add-on:InputStream_Adaptive) for DASH and DRM titles
- A working Widevine CDM on the device for protected titles
- Network access to `https://epika.lrt.lt/api`

Anonymous browsing of the public catalog is supported. Accounts, cookies, bookmarks, concerts, and search suggestions are out of scope for 0.1.0.

## Artwork

`resources/images/icon.png` and `resources/images/fanart.jpg` are generic placeholders inherited from the old example plugin (a clapperboard icon and abstract bokeh fanart). They are **not** official LRT branding. No substitute LRT artwork was available under a known license, so binaries were not fabricated.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
python3 -m compileall -q main.py resources/lib tools
python3 tools/build.py
```

Live read-only API checks are opt-in:

```bash
LRT_EPIKA_LIVE=1 .venv/bin/pytest -q -m live
```

The build writes a deterministic archive:

```text
dist/plugin.video.lrtepika-0.1.0.zip
└── plugin.video.lrtepika/
```

Install that ZIP in Kodi. Do not copy a Git working tree into `~/.kodi/addons`.

## License

MIT. See `LICENSE.txt`.
