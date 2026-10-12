"""Offline input, native-piece and legacy-loader contract checks."""
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from experiments.japanese_ctc import run


class Tokenizer:
    word_delimiter_token = "|"
    unk_token_id = 0
    all_special_tokens = ["<unk>", "<pad>"]

    def __init__(self, tokens, ids):
        self.tokens, self.ids = tokens, ids

    def tokenize(self, text):
        return self.tokens

    def convert_tokens_to_ids(self, token):
        return self.ids.get(token, 0)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.identity = {"file_sha256": "file", "pcm_sha256": "pcm", "duration_s": 10}
        self.saved = {"text": "東京", "original_segments": [{"text": "東京", "start": 1, "end": 2}],
                      "input": self.identity.copy(), "offset_s": 50}

    def test_complete_cache_returns_independent_segments(self):
        original = run.validate_cached(self.saved, self.identity, 50)
        original[0]["start"] = 0
        self.assertEqual(self.saved["original_segments"][0]["start"], 1)

    def test_reject_hash_offset_and_text_mismatch(self):
        for key, value in (("text", "京"), ("offset_s", 0), ("status", "failed")):
            bad = {**self.saved, key: value}
            with self.assertRaises(ValueError):
                run.validate_cached(bad, self.identity, 50)
        with self.assertRaises(ValueError):
            run.validate_cached(self.saved, {**self.identity, "pcm_sha256": "changed"}, 50)

    def test_reject_nonfinite_reversed_and_outside_bounds(self):
        for start, end in ((float("nan"), 2), (3, 2), (-1, 2), (1, 11), (False, 2)):
            bad = copy.deepcopy(self.saved)
            bad["original_segments"][0].update(start=start, end=end)
            with self.assertRaises(ValueError):
                run.validate_cached(bad, self.identity, 50)


class PieceTests(unittest.TestCase):
    def test_native_multi_character_piece_retains_original_range(self):
        tokenizer = Tokenizer(["今日", "は", "東京"], {"今日": 3, "は": 4, "東京": 5})
        spans = run.token_spans("今日は東京", tokenizer, 0)
        self.assertEqual([(s["char_start"], s["char_end"]) for s in spans], [(0, 2), (2, 3), (3, 5)])
        self.assertTrue(all(s["lexical_interval_accepted"] for s in spans))

    def test_repeated_piece_mapping_is_monotonic(self):
        spans = run.token_spans("東京東京", Tokenizer(["東京", "東京"], {"東京": 2}), 0)
        self.assertEqual([s["char_start"] for s in spans], [0, 2])

    def test_oov_blank_and_special_tokens_have_no_lexical_evidence(self):
        spans = run.token_spans("A😀", Tokenizer(["A", "😀"], {"A": 1}), 0)
        self.assertTrue(spans[0]["lexical_interval_accepted"])
        self.assertFalse(spans[1]["lexical_interval_accepted"])

    def test_added_token_whitespace_and_delimiter(self):
        spans = run.token_spans(" 東京 です", Tokenizer(["|", "東京", "です"], {"|": 1, "東京": 2, "です": 3}), 0)
        self.assertEqual([(s["char_start"], s["char_end"]) for s in spans], [(0, 1), (1, 3), (4, 6)])

    def test_unmappable_piece_fails_without_invented_mapping(self):
        with self.assertRaises(ValueError):
            run.token_spans("東京", Tokenizer(["とうきょう"], {"とうきょう": 1}), 0)

    def test_complete_units_preserves_every_untimed_character(self):
        timed = [{"char_start": 1, "char_end": 3, "start": 1, "end": 2,
                  "granularity": "word", "time_source": "api", "status": "ok"}]
        units = run.complete_units(" 東京。", timed)
        self.assertEqual(sum(u["char_end"] - u["char_start"] for u in units), 4)
        self.assertEqual(units[1], timed[0])
        self.assertTrue(all(u["start"] is None for u in (units[0], units[2])))


class LoaderTests(unittest.TestCase):
    def test_mms_loader_selects_jpn_and_local_only(self):
        events = []
        tokenizer = types.SimpleNamespace(set_target_lang=lambda lang: events.append(("tokenizer", lang)),
                                          get_vocab=lambda: {"<pad>": 0, "あ": 1}, target_lang="jpn")
        processor = types.SimpleNamespace(tokenizer=tokenizer)
        model = types.SimpleNamespace(config=types.SimpleNamespace(pad_token_id=0, vocab_size=2),
                                      lm_head=types.SimpleNamespace(out_features=2), target_lang="jpn")
        model.load_adapter = lambda *a, **kw: events.append(("adapter", a, kw))
        model.float = lambda: model
        model.to = lambda device: model
        model.eval = lambda: model
        processor_class = types.SimpleNamespace(from_pretrained=lambda *a, **kw: (events.append(("processor", kw)), processor)[1])
        model_class = types.SimpleNamespace(from_pretrained=lambda *a, **kw: (events.append(("model", kw)), model)[1])
        with patch.dict("sys.modules", transformers=types.SimpleNamespace(Wav2Vec2Processor=processor_class, Wav2Vec2ForCTC=model_class)):
            with patch.object(run, "verify_mms_head", return_value={"head_weight_exact_match": True,
                                                                   "head_bias_exact_match": True}) as verify:
                _, metadata = run.load_mms("local", "cuda:0")
                verify.assert_called_once_with(model, "local")
        self.assertEqual(metadata["dictionary"]["あ"], 1)
        self.assertIn(("adapter", ("jpn",), {"local_files_only": True}), events)
        self.assertTrue(all(row[1]["local_files_only"] for row in events if row[0] in {"processor", "model"}))
        self.assertEqual(next(row[1]["target_lang"] for row in events if row[0] == "model"), None)
        self.assertLess(next(i for i, row in enumerate(events) if row[0] == "model"),
                        next(i for i, row in enumerate(events) if row[0] == "adapter"))
        self.assertTrue(metadata["mms_adapter_verification"]["head_weight_exact_match"])

    def test_mms_head_must_exactly_equal_local_adapter(self):
        class Tensor:
            dtype = "float32"
            def __init__(self, values): self.values = values
            def detach(self): return self
            def cpu(self): return self
            def to(self, **kwargs): return self
        class Checkpoint:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def get_tensor(self, key): return Tensor([1, 2] if key.endswith("weight") else [3])
        model = types.SimpleNamespace(lm_head=types.SimpleNamespace(weight=Tensor([1, 2]), bias=Tensor([3])))
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "adapter.jpn.safetensors").write_bytes(b"synthetic adapter")
            with patch.dict("sys.modules", torch=types.SimpleNamespace(equal=lambda a, b: a.values == b.values),
                            safetensors=types.SimpleNamespace(safe_open=lambda *a, **kw: Checkpoint())):
                evidence = run.verify_mms_head(model, directory)
                self.assertTrue(evidence["head_weight_exact_match"] and evidence["head_bias_exact_match"])
                model.lm_head.bias = Tensor([99])
                with self.assertRaisesRegex(ValueError, "bias differs"):
                    run.verify_mms_head(model, directory)

    def test_legacy_loader_restores_after_failure(self):
        def original(*a, **kw):
            raise ValueError("load failure")
        whisperx = types.SimpleNamespace(load_align_model=original)
        with self.assertRaises(ValueError):
            with run.observed_loader(whisperx, "jonatas", {}):
                whisperx.load_align_model("ja", "cuda:0", model_name="local")
        self.assertIs(whisperx.load_align_model, original)


class CliTests(unittest.TestCase):
    def test_default_native_recipe_options_are_explicit(self):
        args = run.parser().parse_args(["--candidate", "reazon", "--route", "W1", "--audio", "a",
            "--asr-result", "b", "--align-model", "c", "--output", "d", "--zero-pad-seconds", ".5"])
        self.assertEqual((args.padding, args.zero_pad_seconds, args.tokenization), (0, .5, "auto"))


if __name__ == "__main__":
    unittest.main()
