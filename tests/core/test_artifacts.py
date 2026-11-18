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
    "format": {"filename": "D:/movies/ep01.mkv", "duration": "10.05", "tags": {"encoder": "x"}},
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
        self.assertEqual(a.work_id("S1\\ep01.mkv"), a.work_id("S1/ep01.mkv"))
        self.assertNotEqual(a.work_id("S1/ep01.mkv"), a.work_id("S1/ep01.mp4"))

    def test_rejects_paths_outside_input_dir(self) -> None:
        for bad in ("/abs/ep.mkv", "../ep.mkv", "C:/ep.mkv", "C:ep.mkv", "S1/ep.mkv:stream", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                a.work_id(bad)

    def test_register_writes_index_under_root_and_is_idempotent(self) -> None:
        work_root = self.root / "work" / "in-abc"
        first = a.register_work_dir(work_root, "S1/ep01.mkv")
        again = a.register_work_dir(work_root, "S1/ep01.mkv")
        self.assertEqual(first, again)
        self.assertEqual(first, work_root / a.work_id("S1/ep01.mkv"))
        self.assertTrue(first.is_dir())
        a.register_work_dir(work_root, "ep02.mkv")
        index = a.read_json(work_root / "index.json")
        self.assertEqual(index, {a.work_id("S1/ep01.mkv"): "S1/ep01.mkv", a.work_id("ep02.mkv"): "ep02.mkv"})

    def test_short_id_collision_is_refused(self) -> None:
        identifier = a.work_id("S1/ep01.mkv")
        a.atomic_write_json(self.root / "index.json", {identifier: "other/file.mkv"})
        with self.assertRaisesRegex(ValueError, "collides"):
            a.register_work_dir(self.root, "S1/ep01.mkv")
        self.assertFalse((self.root / identifier).exists())

    def test_final_path_sits_beside_the_source_and_mirrors_nesting(self) -> None:
        self.assertEqual(a.final_srt_path(self.root, "ep01.mkv"), self.root / "ep01.ja-zh.srt")
        self.assertEqual(a.final_srt_path(self.root, "S1/ep01.mkv"), self.root / "S1" / "ep01.ja-zh.srt")
        self.assertEqual(a.final_srt_path(self.root, "S1/OVA/a.b.mp4"), self.root / "S1" / "OVA" / "a.b.ja-zh.srt")
        self.assertEqual(a.final_srt_path(self.root, "S1\\ep01.mkv"), a.final_srt_path(self.root, "S1/ep01.mkv"))
        self.assertEqual(a.FINAL_SUFFIX, ".ja-zh.srt")


class InputKeyTests(TempCase):
    def test_key_is_name_dash_sha12_of_normcased_resolved_path(self) -> None:
        directory = self.root / "Anime"
        directory.mkdir()
        digest = a.sha256_bytes(os.path.normcase(str(directory.resolve())).encode("utf-8"))[:12]
        self.assertEqual(a.input_key(directory), f"Anime-{digest}")
        self.assertEqual(a.input_key(directory), a.input_key(directory))  # 稳定
        self.assertEqual(a.input_key(directory / ".." / "Anime"), a.input_key(directory))  # 路径先 resolve

    def test_case_variants_share_a_key_only_where_normcase_folds_case(self) -> None:
        # 摘要只受 normcase 影响：大小写不同的同一路径在 Windows 上同键，在区分大小写的平台上异键。
        directory = self.root / "Anime"
        directory.mkdir()
        digest = a.input_key(directory).rsplit("-", 1)[1]
        folded = a.sha256_bytes(os.path.normcase(str(directory.resolve())).encode("utf-8"))[:12]
        self.assertEqual(digest, folded)
        if os.path.normcase("A") == os.path.normcase("a"):
            with mock.patch.object(Path, "resolve", lambda self, strict=False: Path(str(self).upper())):
                self.assertEqual(a.input_key(directory).rsplit("-", 1)[1], digest)

    def test_different_input_dirs_get_different_roots(self) -> None:
        one, two = self.root / "one" / "Anime", self.root / "two" / "Anime"
        one.mkdir(parents=True)
        two.mkdir(parents=True)
        self.assertNotEqual(a.input_key(one), a.input_key(two))
        self.assertTrue(a.input_key(one).startswith("Anime-") and a.input_key(two).startswith("Anime-"))
        work = self.root / "work"
        self.assertNotEqual(a.work_root(work, one), a.work_root(work, two))
        self.assertEqual(a.work_root(work, one), work / a.input_key(one))

    def test_drive_root_is_named_root(self) -> None:
        anchor = Path(self.root.anchor)
        self.assertTrue(a.input_key(anchor).startswith("root-"))

    def test_cache_paths_are_shared_under_work_dir(self) -> None:
        self.assertEqual(a.cache_dir(self.root), self.root / "cache")
        self.assertEqual(a.model_cache_path(self.root), self.root / "cache" / "model-verification.json")

    def test_record_input_writes_absolute_path_once(self) -> None:
        directory = self.root / "in"
        directory.mkdir()
        work_root = self.root / "work" / a.input_key(directory)
        a.record_input(work_root, directory)
        self.assertEqual(a.read_json(work_root / "input.json"), {"input_dir": str(directory.resolve())})
        a.atomic_write_json(work_root / "input.json", {"input_dir": "marker"})
        a.record_input(work_root, directory)  # 已有则不动
        self.assertEqual(a.read_json(work_root / "input.json"), {"input_dir": "marker"})


class IdentityTests(TempCase):
    def video(self) -> Path:
        path = self.root / "in/S1/ep01.mkv"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"video")
        return path

    def test_probe_fingerprint_drops_filename_and_tags(self) -> None:
        fingerprint = a.probe_fingerprint(PROBE)
        self.assertEqual(fingerprint["format_duration"], "10.05")
        self.assertEqual(fingerprint["streams"][1], {
            "index": 1, "codec_name": "aac", "channels": 2, "channel_layout": "stereo",
            "sample_rate": "48000", "start_time": "0.021", "duration": "10.0"})
        self.assertNotIn("D:/movies", json.dumps(fingerprint))
        self.assertNotIn("tags", json.dumps(fingerprint))

    def test_video_identity_ignores_location_and_tracks_size_mtime_probe(self) -> None:
        video = self.video()
        identity = a.video_identity(self.root / "in", "S1/ep01.mkv", PROBE)
        self.assertEqual(identity["relative_path"], "S1/ep01.mkv")
        self.assertNotIn(str(self.root), json.dumps(identity))
        retagged = json.loads(json.dumps(PROBE))
        retagged["format"]["filename"] = "E:/elsewhere.mkv"
        retagged["streams"][1]["tags"] = {}
        self.assertEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", retagged), identity)
        changed = json.loads(json.dumps(PROBE))
        changed["streams"][1]["channels"] = 6
        self.assertNotEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", changed), identity)
        stat = video.stat()
        os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        self.assertNotEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", PROBE), identity)

    def test_derived_identity_requires_digests(self) -> None:
        identity = a.derived_identity(upstream={"pcm": SHA_A}, recipe_hash=SHA_B, models={"seg": SHA_C},
                                      config={"seed": 7})
        self.assertEqual(identity, {"upstream": {"pcm": SHA_A}, "recipe_hash": SHA_B,
                                    "models": {"seg": SHA_C}, "config": {"seed": 7}})
        for kwargs in ({"upstream": {}, "recipe_hash": SHA_B},
                       {"upstream": {"pcm": "D:/x/audio-16k.wav"}, "recipe_hash": SHA_B},
                       {"upstream": {"pcm": SHA_A}, "recipe_hash": "v1"},
                       {"upstream": {"pcm": SHA_A}, "recipe_hash": SHA_B, "models": {"seg": "/models/seg.bin"}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                a.derived_identity(**kwargs)


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

    def test_mismatch_is_replaced_in_place(self) -> None:
        path = self.root / a.ASR
        a.write_artifact(path, self.identity(), {"offset_s": 0, "text": "旧"})
        a.write_artifact(path, self.identity(recipe_hash=SHA_C), {"offset_s": 0, "text": "新"})
        self.assertEqual(a.read_json(path)["text"], "新")
        self.assertTrue(a.is_current(path, self.identity(recipe_hash=SHA_C)))
        self.assertEqual([p.name for p in self.root.iterdir()], [a.ASR])

    def test_corrupt_or_foreign_artifact_is_not_current(self) -> None:
        path = self.root / a.ALIGN
        path.write_text("{truncated", encoding="utf-8")
        self.assertFalse(a.is_current(path, self.identity()))
        path.write_text("[]", encoding="utf-8")
        self.assertFalse(a.is_current(path, self.identity()))

    def test_local_time_artifacts_require_offset(self) -> None:
        for name in (a.VAD, a.ASR, a.ALIGN):
            for payload in ({}, {"offset_s": None}, {"offset_s": True}, {"offset_s": float("nan")}):
                with self.subTest(name=name, payload=payload), self.assertRaises(ValueError):
                    a.write_artifact(self.root / name, self.identity(), payload)
        a.write_artifact(self.root / a.JA_CUES, self.identity(), {"cues": []})
        with self.assertRaises(ValueError):
            a.write_artifact(self.root / a.JA_CUES, self.identity(), {"identity": {}})

    def test_cross_audit_artifacts_are_outside_the_stage_chain(self) -> None:
        names = (a.ASR_W0, a.ASR_X0, a.ASR_JUDGE)
        self.assertEqual(names, ("asr-w0.json", "asr-x0.json", "asr-judge.json"))
        for name in names:
            self.assertNotIn(name, a.STAGE_ARTIFACTS)
            self.assertNotIn(name, a.LOCAL_TIME_ARTIFACTS)
            (self.root / name).write_text("{}", encoding="utf-8")
        a.write_failure(self.root, "asr", RuntimeError("boom"))
        self.assertEqual(a.read_json(self.root / a.FAILURE)["completed"], [])

    def test_failure_lists_existing_stage_artifacts(self) -> None:
        a.write_artifact(self.root / a.VAD, self.identity(), {"offset_s": 0})
        (self.root / a.PROBE).write_text("{}", encoding="utf-8")
        a.write_failure(self.root, "asr", RuntimeError("boom"))
        failure = a.read_json(self.root / a.FAILURE)
        self.assertEqual((failure["stage"], failure["error_type"], failure["message"]), ("asr", "RuntimeError", "boom"))
        self.assertEqual(failure["completed"], [a.PROBE, a.VAD])

    def test_embedded_subtitle_record_is_listed_as_completed(self) -> None:
        self.assertEqual(a.JA_EMBEDDED, "ja-embedded.json")
        a.write_artifact(self.root / a.JA_EMBEDDED, self.identity(), {"cues": 1})
        a.write_failure(self.root, "names", RuntimeError("boom"))
        self.assertEqual(a.read_json(self.root / a.FAILURE)["completed"], [a.JA_EMBEDDED])

    def test_name_artifacts_are_named_and_the_table_is_listed_as_completed(self) -> None:
        self.assertEqual(a.NAME_TABLE, "name-table.json")
        self.assertFalse(hasattr(a, "NAMES_APPLY"))  # 发布时替换已删除（原 ADR-0019，现见 ADR-0028「表的使用与校对」）
        self.assertIn(a.NAME_TABLE, a.STAGE_ARTIFACTS)
        a.write_artifact(self.root / a.NAME_TABLE, self.identity(), {"entries": []})
        a.write_failure(self.root, "names", RuntimeError("boom"))
        self.assertEqual(a.read_json(self.root / a.FAILURE)["completed"], [a.NAME_TABLE])


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

    def test_size_or_mtime_change_rehashes(self) -> None:
        a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        stat = self.model.stat()
        os.utime(self.model, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        self.assertEqual(a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)["method"], "computed")
        stat = self.model.stat()
        self.model.write_bytes(b"weightz")  # 同大小、改内容，mtime 恢复原值：缓存仍命中（size+mtime 语义）
        os.utime(self.model, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)["method"],
                         "cached-size-mtime")
        self.model.write_bytes(b"weights!")
        os.utime(self.model, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # 只改大小
        with self.assertRaisesRegex(ValueError, "mismatch"):
            a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        self.assertEqual(self.calls, 3)

    def test_cached_digest_must_equal_expected(self) -> None:
        a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            a.verify_model(self.model, SHA_A, self.cache, hasher=self.hasher)
        self.assertEqual(self.calls, 2)

    def test_mismatch_is_not_cached(self) -> None:
        with self.assertRaises(ValueError):
            a.verify_model(self.model, SHA_A, self.cache, hasher=self.hasher)
        self.assertFalse(self.cache.exists())


class PublishRecordTests(TempCase):
    def test_record_published_is_audit_only_content(self) -> None:
        work = self.root / "abc"
        work.mkdir()
        final = self.root / "in" / "ep01.ja-zh.srt"
        a.record_published(work, final, SHA_A, {"ja_cues": SHA_B}, "translate/srt-aaaaaaaaaaaa")
        record = a.read_json(work / a.PUBLISHED)
        self.assertEqual(set(record), {"final", "sha256", "sources", "translate_dir", "published_at_utc"})
        self.assertEqual((record["final"], record["sha256"]), (str(final), SHA_A))
        self.assertEqual((record["sources"], record["translate_dir"]), ({"ja_cues": SHA_B}, "translate/srt-aaaaaaaaaaaa"))
        self.assertTrue(record["published_at_utc"])

    def test_record_requires_a_digest(self) -> None:
        with self.assertRaises(ValueError):
            a.record_published(self.root, self.root / "x.ja-zh.srt", "not-a-digest", {}, "translate/x")


class AtomicWriteTests(TempCase):
    def test_replace_retries_permission_error_then_succeeds(self) -> None:
        calls, sleeps = [], []

        def flaky(source: Path, target: Path) -> None:
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("in use")
            os.replace(source, target)

        source, target = self.root / "s", self.root / "t"
        source.write_text("x", encoding="utf-8")
        a.replace_with_retry(source, target, replace=flaky, sleep=sleeps.append)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.1, 0.2])
        self.assertEqual(target.read_text(encoding="utf-8"), "x")

    def test_replace_gives_up_after_limit(self) -> None:
        def locked(source: Path, target: Path) -> None:
            raise PermissionError("in use")

        sleeps: list[float] = []
        with self.assertRaises(PermissionError):
            a.replace_with_retry(self.root / "s", self.root / "t", replace=locked, sleep=sleeps.append)
        self.assertEqual(len(sleeps), a.REPLACE_ATTEMPTS - 1)
        self.assertLessEqual(max(sleeps), 0.5)

    def test_failed_write_leaves_target_and_no_temp_file(self) -> None:
        target = self.root / "out.json"
        a.atomic_write_json(target, {"v": 1})
        with mock.patch.object(a, "replace_with_retry", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                a.atomic_write_json(target, {"v": 2})
        self.assertEqual(a.read_json(target), {"v": 1})
        self.assertEqual([p.name for p in self.root.iterdir()], ["out.json"])

    def test_text_is_utf8_without_bom_and_lf(self) -> None:
        target = self.root / "x.txt"
        a.atomic_write_text(target, "日本語\n中文\n")
        self.assertEqual(target.read_bytes(), "日本語\n中文\n".encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
