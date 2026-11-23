"""Play history storage and monthly top-10 aggregation."""

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PLAYS_DIR = ROOT / "data" / "plays"
TRACKS_FILE = ROOT / "data" / "tracks.json"
SITE_FILE = ROOT / "docs" / "top.json"
KST = ZoneInfo("Asia/Seoul")
TOP_N = 10
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FIELDS = ("played_at", "track_id", "source")


class Play(NamedTuple):
    played_at: str  # UTC, TS_FORMAT
    track_id: str
    source: str  # "api" or "export"


def normalize_ts(ts: str) -> str:
    """Drop sub-second precision: the API sends milliseconds, exports do not."""
    if not ts.endswith("Z"):
        raise ValueError(f"expected a UTC timestamp ending in 'Z', got {ts!r}")
    return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").strftime(TS_FORMAT)


def month_of(played_at: str) -> str:
    utc = datetime.strptime(played_at, TS_FORMAT).replace(tzinfo=timezone.utc)
    return utc.astimezone(KST).strftime("%Y-%m")


def load_plays() -> list[Play]:
    plays = []
    for path in sorted(PLAYS_DIR.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError(f"{path}: expected columns {FIELDS}, found {reader.fieldnames}")
            plays.extend(Play(**row) for row in reader)
    return plays


def save_plays(plays: list[Play]) -> None:
    by_month = defaultdict(list)
    for play in plays:
        by_month[month_of(play.played_at)].append(play)
    PLAYS_DIR.mkdir(parents=True, exist_ok=True)
    for path in PLAYS_DIR.glob("*.csv"):
        if path.stem not in by_month:
            path.unlink()
    for month, rows in by_month.items():
        with (PLAYS_DIR / f"{month}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(FIELDS)
            writer.writerows(sorted(rows))


def merge_api(plays: list[Play], new: list[Play]) -> tuple[list[Play], int]:
    """Add API plays not seen yet and newer than any imported export."""
    export_end = max((p.played_at for p in plays if p.source == "export"), default="")
    seen = {(p.played_at, p.track_id) for p in plays}
    added = []
    for play in new:
        key = (play.played_at, play.track_id)
        if play.played_at > export_end and key not in seen:
            seen.add(key)
            added.append(play)
    return plays + added, len(added)


def merge_export(plays: list[Play], exported: list[Play]) -> list[Play]:
    """An export is the source of truth for the time range it covers."""
    if not exported:
        return plays
    start = min(p.played_at for p in exported)
    end = max(p.played_at for p in exported)
    kept = [p for p in plays if not start <= p.played_at <= end]
    return kept + list(dict.fromkeys(exported))


def top_by_month(plays: list[Play]) -> dict[str, list[tuple[str, int]]]:
    counts = defaultdict(Counter)
    last_played = {}
    for play in plays:
        month = month_of(play.played_at)
        counts[month][play.track_id] += 1
        key = (month, play.track_id)
        last_played[key] = max(last_played.get(key, ""), play.played_at)
    return {
        month: sorted(
            counter.items(),
            key=lambda item: (item[1], last_played[(month, item[0])]),
            reverse=True,
        )[:TOP_N]
        for month, counter in counts.items()
    }


def load_tracks() -> dict[str, dict]:
    if not TRACKS_FILE.exists():
        return {}
    tracks = json.loads(TRACKS_FILE.read_text(encoding="utf-8"))
    if not isinstance(tracks, dict):
        raise ValueError(f"{TRACKS_FILE}: expected an object keyed by track id, found {type(tracks).__name__}")
    return tracks


def save_tracks(tracks: dict[str, dict]) -> None:
    TRACKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKS_FILE.write_text(json.dumps(tracks, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def missing_images(plays: list[Play], tracks: dict[str, dict]) -> list[str]:
    """Top-10 tracks never looked up; image None means looked up and none exists."""
    ids = {tid for top in top_by_month(plays).values() for tid, _ in top}
    return sorted(tid for tid in ids if tracks.get(tid, {}).get("image", "") == "")


def site_data(plays: list[Play], tracks: dict[str, dict]) -> dict:
    tops = top_by_month(plays)
    return {
        "last_play": max((p.played_at for p in plays), default=None),
        "months": [
            {
                "month": month,
                "tracks": [{"id": tid, "plays": n, **tracks.get(tid, {})} for tid, n in tops[month]],
            }
            for month in sorted(tops, reverse=True)
        ],
    }


def build_site(plays: list[Play], tracks: dict[str, dict]) -> None:
    SITE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SITE_FILE.write_text(json.dumps(site_data(plays, tracks), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
