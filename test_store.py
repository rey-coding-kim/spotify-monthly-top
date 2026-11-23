import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import collect
import store
from store import Play


class StoreTest(unittest.TestCase):
    def test_normalize_ts_drops_milliseconds(self):
        self.assertEqual(store.normalize_ts("2026-11-23T05:12:33.589Z"), "2026-11-23T05:12:33Z")
        self.assertEqual(store.normalize_ts("2023-01-01T12:34:56Z"), "2023-01-01T12:34:56Z")
        with self.assertRaises(ValueError):
            store.normalize_ts("2023-01-01 12:34")

    def test_month_uses_korea_time(self):
        self.assertEqual(store.month_of("2026-10-31T15:30:00Z"), "2026-11")
        self.assertEqual(store.month_of("2026-10-31T14:59:59Z"), "2026-10")

    def test_top_orders_by_count_then_recency(self):
        plays = [
            Play("2026-11-01T00:00:00Z", "a", "api"),
            Play("2026-11-02T00:00:00Z", "a", "api"),
            Play("2026-11-03T00:00:00Z", "b", "api"),
            Play("2026-11-05T00:00:00Z", "c", "api"),
            Play("2026-12-01T00:00:00Z", "b", "api"),
        ]
        tops = store.top_by_month(plays)
        self.assertEqual(tops["2026-11"], [("a", 2), ("c", 1), ("b", 1)])
        self.assertEqual(tops["2026-12"], [("b", 1)])

    def test_top_keeps_ten(self):
        plays = [Play(f"2026-11-01T00:00:{i:02d}Z", f"t{i}", "api") for i in range(15)]
        self.assertEqual(len(store.top_by_month(plays)["2026-11"]), store.TOP_N)

    def test_merge_api_dedups_and_skips_export_range(self):
        existing = [Play("2026-11-01T00:00:00Z", "a", "export"), Play("2026-11-02T00:00:00Z", "b", "api")]
        new = [
            Play("2026-10-31T00:00:00Z", "x", "api"),  # covered by the export
            Play("2026-11-02T00:00:00Z", "b", "api"),  # already stored
            Play("2026-11-03T00:00:00Z", "c", "api"),
            Play("2026-11-03T00:00:00Z", "c", "api"),
        ]
        merged, added = store.merge_api(existing, new)
        self.assertEqual(added, 1)
        self.assertEqual(merged[-1], Play("2026-11-03T00:00:00Z", "c", "api"))

    def test_merge_export_replaces_its_range(self):
        existing = [
            Play("2026-01-01T00:00:00Z", "old", "api"),
            Play("2026-02-01T00:00:00Z", "dup", "api"),
            Play("2026-04-01T00:00:00Z", "later", "api"),
        ]
        exported = [Play("2026-01-15T00:00:00Z", "e1", "export"), Play("2026-03-01T00:00:00Z", "e2", "export")]
        merged = store.merge_export(existing, exported)
        self.assertEqual(sorted(p.track_id for p in merged), ["e1", "e2", "later", "old"])

    def test_site_data_newest_month_first(self):
        plays = [Play("2026-10-01T00:00:00Z", "a", "api"), Play("2026-11-01T00:00:00Z", "a", "api")]
        data = store.site_data(plays, {"a": {"name": "Song", "image": ""}})
        self.assertEqual([m["month"] for m in data["months"]], ["2026-11", "2026-10"])
        self.assertEqual(data["months"][0]["tracks"][0], {"id": "a", "plays": 1, "name": "Song", "image": ""})
        self.assertEqual(store.missing_images(plays, {"a": {"image": ""}}), ["a"])
        self.assertEqual(store.missing_images(plays, {"a": {"image": None}}), [])


class CollectTest(unittest.TestCase):
    def test_track_meta_picks_image_near_300px(self):
        track = {
            "name": "Song",
            "artists": [{"name": "A"}, {"name": "B"}],
            "album": {"name": "Album", "images": [
                {"url": "big", "width": 640}, {"url": "mid", "width": 300}, {"url": "small", "width": 64},
            ]},
        }
        self.assertEqual(collect.track_meta(track), {"name": "Song", "artists": "A, B", "album": "Album", "image": "mid"})

    def test_main_saves_plays_and_survives_a_deleted_track(self):
        recent_track = {"type": "track", "id": "new", "name": "New", "artists": [{"name": "A"}],
                        "album": {"name": "Al", "images": [{"url": "img", "width": 300}]}}

        def fake_request(req):
            url = req.full_url
            if url == collect.TOKEN_URL:
                return {"access_token": "token"}
            if "recently-played" in url:
                return {"items": [
                    {"played_at": "2026-11-20T10:00:00.123Z", "track": recent_track},
                    {"played_at": "2026-11-20T09:00:00.000Z", "track": {"type": "track", "id": None}},
                ]}
            if url.endswith("/tracks/gone"):
                raise collect.SpotifyError(404, "not found")
            raise AssertionError(f"unexpected request {url}")

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            paths = {"PLAYS_DIR": tmp / "plays", "TRACKS_FILE": tmp / "tracks.json", "SITE_FILE": tmp / "top.json"}
            with mock.patch.multiple(store, **paths), mock.patch.object(collect, "request_json", fake_request):
                store.save_plays([Play("2026-11-01T00:00:00Z", "gone", "export")])
                store.save_tracks({"gone": {"name": "Gone", "image": ""}})
                collect.main({"SPOTIFY_CLIENT_ID": "id", "SPOTIFY_CLIENT_SECRET": "s", "SPOTIFY_REFRESH_TOKEN": "r"})
                plays = store.load_plays()
                tracks = store.load_tracks()
            site = json.loads(paths["SITE_FILE"].read_text(encoding="utf-8"))

        self.assertIn(Play("2026-11-20T10:00:00Z", "new", "api"), plays)
        self.assertEqual(len(plays), 2)
        self.assertIsNone(tracks["gone"]["image"])
        self.assertEqual(tracks["new"]["image"], "img")
        self.assertEqual([t["id"] for t in site["months"][0]["tracks"]], ["new", "gone"])


if __name__ == "__main__":
    unittest.main()
