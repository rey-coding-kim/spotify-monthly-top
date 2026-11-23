"""Fetch recent plays from Spotify and rebuild the monthly top-10 data (runs hourly in GitHub Actions)."""

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import store

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
IMAGE_WIDTH = 300
# A long imported history can lack hundreds of images; spread the lookups over runs to stay under quota.
MAX_IMAGE_FETCHES = 25


class SpotifyError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def request_json(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SpotifyError(e.code, f"{req.get_method()} {req.full_url} -> HTTP {e.code}: {body}") from None


def token_request(form: dict, client_id: str, client_secret: str) -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(form).encode(),
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    return request_json(req)


def api_get(path: str, token: str) -> dict:
    return request_json(urllib.request.Request(API_URL + path, headers={"Authorization": f"Bearer {token}"}))


def track_meta(track: dict) -> dict:
    images = track["album"]["images"]
    # None (not "") marks "looked up, has no image" so missing_images() stops retrying it.
    image = min(images, key=lambda i: abs((i.get("width") or 0) - IMAGE_WIDTH))["url"] if images else None
    return {
        "name": track["name"],
        "artists": ", ".join(a["name"] for a in track["artists"]),
        "album": track["album"]["name"],
        "image": image,
    }


def read_config() -> dict:
    names = ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN")
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(f"Missing environment variables: {', '.join(missing)}")
    return {n: os.environ[n] for n in names}


def fill_images(plays: list[store.Play], tracks: dict[str, dict], token: str) -> None:
    for track_id in store.missing_images(plays, tracks)[:MAX_IMAGE_FETCHES]:
        try:
            meta = track_meta(api_get(f"/tracks/{track_id}", token))
        except SpotifyError as e:
            if e.status not in (400, 404):  # rate limit or outage: retry next run
                print(f"::warning::Stopped image lookup: {e}")
                return
            print(f"::warning::No track data for {track_id}: {e}")
            meta = {"image": None}
        tracks[track_id] = {**tracks.get(track_id, {}), **meta}


def main(cfg: dict) -> None:
    try:
        tokens = token_request(
            {"grant_type": "refresh_token", "refresh_token": cfg["SPOTIFY_REFRESH_TOKEN"]},
            cfg["SPOTIFY_CLIENT_ID"],
            cfg["SPOTIFY_CLIENT_SECRET"],
        )
    except SpotifyError as e:
        if "invalid_grant" in str(e):
            sys.exit("Refresh token rejected (invalid_grant). Run auth.py again and update SPOTIFY_REFRESH_TOKEN.")
        raise
    if tokens.get("refresh_token") not in (None, cfg["SPOTIFY_REFRESH_TOKEN"]):
        print("::warning::Spotify issued a new refresh token; if the next run fails, run auth.py again.")
    token = tokens["access_token"]

    tracks = store.load_tracks()
    new = []
    for item in api_get("/me/player/recently-played?limit=50", token)["items"]:
        track = item["track"]
        if track.get("type") != "track" or not track.get("id"):  # local files have no Spotify id
            continue
        tracks[track["id"]] = track_meta(track)
        new.append(store.Play(store.normalize_ts(item["played_at"]), track["id"], "api"))

    plays, added = store.merge_api(store.load_plays(), new)
    store.save_plays(plays)
    fill_images(plays, tracks, token)
    store.save_tracks(tracks)
    store.build_site(plays, tracks)
    print(f"Added {added} plays ({len(plays)} total).")


if __name__ == "__main__":
    main(read_config())
