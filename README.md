# spotify-monthly-top

My most-played Spotify tracks, top 10 per month (Asia/Seoul calendar months).

- `collect.py` runs every 30 minutes in GitHub Actions, pulls the last 50 plays from the Spotify Web API, commits new ones to `data/`, and redeploys Pages.
- `import_history.py` backfills past months from Spotify's "Extended streaming history" export (Account → Privacy → Download your data).
- `docs/` is the GitHub Pages site; `docs/top.json` is generated.

## Setup

1. Spotify app (developer.spotify.com/dashboard): add redirect URI `http://127.0.0.1:8888/callback`. The app owner needs Premium.
2. Repository secrets: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN` (printed by `python3 auth.py`).
3. Pages source: GitHub Actions (`gh api -X POST repos/OWNER/spotify-monthly-top/pages -f build_type=workflow`).

The refresh token expires about six months after login; when the workflow fails with `invalid_grant`, run `auth.py` again.

## Import past months

```sh
git pull --rebase
python3 import_history.py path/to/Streaming_History_Audio_*.json
git add data docs/top.json && git commit -m "Import streaming history" && git push
```

## Test

```sh
python3 -m unittest
```
