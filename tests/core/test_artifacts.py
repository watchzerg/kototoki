from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kototoki import artifacts as a

SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
PROBE = {
    "streams": [{"index": 0, "codec_name": "h264", "duration": "10.0", "tags": {"title": "x"}},
                {"index": 1, "codec_name": "aac", "channels": 2, "channel_layout": "stereo",
                 "sample_rate": "48000", "start_time": "0.021", "duration": "10.0", "tags": {"language": "jpn"}}],
    "format": {"filename": "/srv/movies/ep01.mkv", "duration": "10.05", "tags": {"encoder": "x"}},
}


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class WorkDirTests(TempCase):
    def test_work_id_is_sha12_of_posix_relative_path_with_extension(self) -> None:
        self.assertEqual(a.work_id("S1/ep01.mkv"), a.sha256_bytes(b"S1/ep01.mkv")[:12])
        self.assertNotEqual(a.work_id("S1/ep01.mkv"), a.work_id("S1/ep01.mp4"))

    def test_final_path_sits_beside_the_source_and_mirrors_nesting(self) -> None:
        self.assertEqual(a.final_srt_path(self.root, "ep01.mkv"), self.root / "ep01.ja-zh.srt")
        self.assertEqual(a.final_srt_path(self.root, "S1/ep01.mkv"), self.root / "S1" / "ep01.ja-zh.srt")


class InputKeyTests(TempCase):

    def test_different_input_dirs_get_different_roots(self) -> None:
        one, two = self.root / "one" / "Anime", self.root / "two" / "Anime"
        one.mkdir(parents=True)
        two.mkdir(parents=True)
        self.assertNotEqual(a.input_key(one), a.input_key(two))
        self.assertTrue(a.input_key(one).startswith("Anime-") and a.input_key(two).startswith("Anime-"))
        work = self.root / "work"
        self.assertNotEqual(a.work_root(work, one), a.work_root(work, two))
        self.assertEqual(a.work_root(work, one), work / a.input_key(one))


class IdentityTests(TempCase):
    def video(self) -> Path:
        path = self.root / "in/S1/ep01.mkv"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"video")
        return path

    def test_video_identity_ignores_location_and_tracks_size_mtime_probe(self) -> None:
        video = self.video()
        identity = a.video_identity(self.root / "in", "S1/ep01.mkv", PROBE)
        self.assertEqual(identity["relative_path"], "S1/ep01.mkv")
        self.assertNotIn(str(self.root), json.dumps(identity))
        retagged = json.loads(json.dumps(PROBE))
        retagged["format"]["filename"] = "/srv/elsewhere.mkv"
        retagged["streams"][1]["tags"] = {}
        self.assertEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", retagged), identity)
        changed = json.loads(json.dumps(PROBE))
        changed["streams"][1]["channels"] = 6
        self.assertNotEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", changed), identity)
        stat = video.stat()
        os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        self.assertNotEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", PROBE), identity)


class ArtifactTests(TempCase):
    def identity(self, **changes: object) -> dict:
        base = {"upstream": {"pcm": SHA_A}, "recipe_hash": SHA_B, "models": {}, "config": {}}
        return {**base, **changes}

    def test_is_current_matches_and_invalidates(self) -> None:
        path = self.root / a.VAD
        self.assertFalse(a.is_current(path, self.identity()))
        a.write_artifact(path, self.identity(), {"offset_s": 0, "windows": []})
        self.assertTrue(a.is_current(path, self.identity()))
        for changed in (self.identity(recipe_hash=SHA_C), self.identity(upstream={"pcm": SHA_C}),
                        self.identity(models={"seg": SHA_C}), self.identity(config={"seed": 1})):
            with self.subTest(changed=changed):
                self.assertFalse(a.is_current(path, changed))

    def test_failure_lists_existing_stage_artifacts(self) -> None:
        a.write_artifact(self.root / a.VAD, self.identity(), {"offset_s": 0})
        (self.root / a.PROBE).write_text("{}", encoding="utf-8")
        a.write_failure(self.root, "asr", RuntimeError("boom"))
        failure = a.read_json(self.root / a.FAILURE)
        self.assertEqual((failure["stage"], failure["error_type"], failure["message"]), ("asr", "RuntimeError", "boom"))
        self.assertEqual(failure["completed"], [a.PROBE, a.VAD])


class ModelVerificationTests(TempCase):
    def setUp(self) -> None:
        super().setUp()
        self.model = self.root / "model.bin"
        self.model.write_bytes(b"weights")
        self.expected = a.sha256_bytes(b"weights")
        self.cache = a.model_cache_path(self.root / "work")
        self.calls = 0

    def hasher(self, path: Path) -> str:
        self.calls += 1
        return a.sha256_file(path)

    def test_cache_hit_skips_hashing(self) -> None:
        first = a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        second = a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        self.assertEqual((first["method"], second["method"]), ("computed", "cached-size-mtime"))
        self.assertEqual(self.calls, 1)
        self.assertEqual(second["sha256"], self.expected)


class AtomicWriteTests(TempCase):
    def test_failed_write_leaves_target_and_no_temp_file(self) -> None:
        target = self.root / "out.json"
        a.atomic_write_json(target, {"v": 1})
        with mock.patch("os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                a.atomic_write_json(target, {"v": 2})
        self.assertEqual(a.read_json(target), {"v": 1})
        self.assertEqual([p.name for p in self.root.iterdir()], ["out.json"])


if __name__ == "__main__":
    unittest.main()
