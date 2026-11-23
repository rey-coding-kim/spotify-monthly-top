"""Import Spotify "Extended streaming history" files into the play history.

Usage: python3 import_history.py ~/Downloads/Spotify\\ Extended\\ Streaming\\ History/Streaming_History_Audio_*.json
"""

import json
import sys
from pathlib import Path

import store

MIN_MS_PLAYED = 30_000  # Spotify counts a stream after 30 seconds of playback.
TRACK_PREFIX = "spotify:track:"
REQUIRED = ("ts", "ms_played", "spotify_track_uri", "master_metadata_track_name")


def read_export(paths: list[str]) -> tuple[list[store.Play], dict[str, dict]]:
    plays, tracks = [], {}
    for path in paths:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(rows, list) or (rows and not all(k in rows[0] for k in REQUIRED)):
            found = sorted(rows[0]) if isinstance(rows, list) and rows else type(rows).__name__
            sys.exit(f"{path}: expected Extended streaming history rows with {REQUIRED}, found {found}")
        for row in rows:
            uri = row["spotify_track_uri"] or ""
            if not uri.startswith(TRACK_PREFIX) or row["ms_played"] < MIN_MS_PLAYED:
                continue
            track_id = uri.removeprefix(TRACK_PREFIX)
            plays.append(store.Play(store.normalize_ts(row["ts"]), track_id, "export"))
            tracks.setdefault(track_id, {
                "name": row["master_metadata_track_name"],
                "artists": row.get("master_metadata_album_artist_name") or "",
                "album": row.get("master_metadata_album_album_name") or "",
                "image": "",
            })
    return plays, tracks


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    exported, export_tracks = read_export(sys.argv[1:])
    if not exported:
        sys.exit("No track plays of 30s or longer found in the given files.")

    tracks = store.load_tracks()
    for track_id, meta in export_tracks.items():
        tracks.setdefault(track_id, meta)
    plays = store.merge_export(store.load_plays(), exported)

    store.save_plays(plays)
    store.save_tracks(tracks)
    store.build_site(plays, tracks)
    start, end = min(p.played_at for p in exported), max(p.played_at for p in exported)
    print(f"Imported {len(exported)} plays from {start} to {end} ({len(plays)} total).")


if __name__ == "__main__":
    main()
