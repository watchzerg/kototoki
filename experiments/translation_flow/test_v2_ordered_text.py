"""Offline generated-language and worker checks; no native engine claim."""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
from itertools import product
import ast
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from experiments.translation_demo import adapters
from . import v2_id_text as protocol, v2_recipes as recipes, v2_worker as worker


def accepts_generated_grammar(grammar, text):
    """Recognize literals, character classes, references and choices independently.

    This parses the emitted GBNF subset. It is not llama.cpp compilation, token
    masking, or a substitute for future real-engine qualification.
    """
    rules = {}
    decoder = json.JSONDecoder()
    for line in grammar.splitlines():
        name, body = line.split("::=", 1)
        alternatives, tokens, pos = [], [], 0
        while pos < len(body):
            char = body[pos]
            if char.isspace():
                pos += 1
            elif char == "|":
                alternatives.append(tokens)
                tokens = []
                pos += 1
            elif char == '"':
                value, count = decoder.raw_decode(body[pos:])
                tokens.append(("literal", value))
                pos += count
            elif char == "[":
                start = pos
                pos += 1
                escaped = False
                while pos < len(body):
                    if body[pos] == "]" and not escaped:
                        pos += 1
                        break
                    escaped = body[pos] == "\\" and not escaped
                    pos += 1
                tokens.append(("class", re.compile(body[start:pos])))
            else:
                match = re.match(r"[a-z][a-z0-9-]*", body[pos:])
                if match is None:
                    raise AssertionError("Unsupported offline grammar production")
                tokens.append(("reference", match.group()))
                pos += len(match.group())
        rules[name.strip()] = alternatives + [tokens]

    @lru_cache(None)
    def match_rule(name, pos):
        ends = set()
        for sequence in rules[name]:
            positions = {pos}
            for kind, value in sequence:
                next_positions = set()
                for start in positions:
                    if kind == "literal" and text.startswith(value, start):
                        next_positions.add(start + len(value))
                    elif kind == "class" and start < len(text) and value.fullmatch(text[start]):
                        next_positions.add(start + 1)
                    elif kind == "reference":
                        next_positions.update(match_rule(value, start))
                positions = next_positions
            ends.update(positions)
        return ends

    return len(text) in match_rule("root", 0)


def window():
    return {"id": "synthetic-window", "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": uid, "text": "合成台詞"} for uid in ["readonly-before", "x1", "x2", "x3", "x4", "x5", "readonly-after"]],
            "translate_ids": ["x1", "x2", "x3", "x4", "x5"]}


def settings(recipe="id-text-ordered", **changes):
    return {"label": "synthetic", "recipe": recipe, "sampling": "official", "cache_prompt": True,
            "n_predict": 4096, "seed": 20261008, "max_attempts": 2, **changes}


def valid_text(ids=None):
    return "\n".join("[[" + uid + "]]synthetic" for uid in (ids or window()["translate_ids"]))


class FakeClient:
    def __init__(self, outputs, tokens=7):
        self.outputs = list(outputs)
        self.tokens = tokens
        self.requests = []
        self.last_exchange = None

    def tokenize(self, prompt):
        return list(range(self.tokens))

    def complete(self, request):
        self.requests.append(deepcopy(request))
        return {"content": self.outputs.pop(0), "timings": {"cache_n": 0}, "tokens_evaluated": self.tokens,
                "generation_settings": {k: v for k, v in request.items() if k not in {"prompt", "grammar", "stream", "stop", "cache_prompt"}}}


class OrderedStageTests(unittest.TestCase):
    def test_observed_failure_classes_rejected_by_parser_and_generated_language(self):
        ids = window()["translate_ids"]
        good = valid_text(ids)
        bad = {
            "extra-readonly": good + "\n[[readonly-after]]synthetic",
            "duplicate-target": good + "\n[[x5]]synthetic",
            "empty-body": good.replace("[[x3]]synthetic", "[[x3]]"),
            "inline-marker": good.replace("\n[[x3]]", "[[x3]]"),
            "omitted-target": "\n".join(good.splitlines()[:-1]),
            "interior-empty-subtitle-line": good.replace("[[x3]]synthetic", "[[x3]]synthetic\n\nsynthetic"),
        }
        grammar = protocol.ordered_grammar(ids)
        self.assertTrue(accepts_generated_grammar(grammar, good))
        for name, content in bad.items():
            with self.subTest(name=name):
                self.assertFalse(accepts_generated_grammar(grammar, content))
                with self.assertRaises(ValueError):
                    protocol.parse_ordered_text(content, ids)

    def test_strict_order_unknown_ids_preamble_json_and_extra_padding_rejected(self):
        ids = ["a", "b"]
        for content in ("[[b]]B\n[[a]]A", "[[a]]A\n[[unknown]]B", "intro\n[[a]]A\n[[b]]B",
                        '{"translations":{"a":"A","b":"B"}}', "\n[[a]]A\n[[b]]B", "[[a]]A\n[[b]]B\n\n"):
            self.assertFalse(accepts_generated_grammar(protocol.ordered_grammar(ids), content))
            with self.assertRaises(ValueError):
                protocol.parse_ordered_text(content, ids)

    def test_unicode_quotes_backslashes_single_ascii_brackets_and_spaces_preserved(self):
        bodies = ['  中文🌧️a\u0301 [x] [] ][ [ ] "q" \\ | ```  ', "【日本語】『台詞』🙂", "\t\u3000甲\u3000\t", "[", "]"]
        grammar = protocol.ordered_grammar(["a"])
        for body in bodies:
            text = "[[a]]" + body
            self.assertTrue(accepts_generated_grammar(grammar, text))
            self.assertEqual(protocol.parse_ordered_text(text, ["a"]), {"a": body})

    def test_reserved_double_brackets_empty_unicode_whitespace_and_line_breaks_rejected(self):
        for body in ["[[", "]]", "a[[b", "a]]b", "", " \t\u3000\u00a0", "a\ud800b"] + ["a" + char + "b" for char in protocol._LINE_BREAKS]:
            text = "[[a]]" + body
            self.assertFalse(accepts_generated_grammar(protocol.ordered_grammar(["a"]), text))
            with self.assertRaises(ValueError):
                protocol.parse_ordered_text(text, ["a"])

    def test_parser_and_generated_grammar_agree_on_small_unicode_bracket_language(self):
        grammar = protocol.ordered_grammar(["a"])
        for length in range(4):
            for chars in product("[]a \t甲", repeat=length):
                text = "[[a]]" + "".join(chars)
                try:
                    protocol.parse_ordered_text(text, ["a"])
                    expected = True
                except ValueError:
                    expected = False
                self.assertEqual(accepts_generated_grammar(grammar, text), expected, repr(chars))

    def test_lf_grammar_and_explicit_crlf_transport_framing_parser(self):
        content = "[[a]]A\n[[b]]B\n"
        self.assertTrue(accepts_generated_grammar(protocol.ordered_grammar(["a", "b"]), content))
        self.assertFalse(accepts_generated_grammar(protocol.ordered_grammar(["a", "b"]), content.replace("\n", "\r\n")))
        self.assertEqual(protocol.parse_ordered_text(content.replace("\n", "\r\n"), ["a", "b"]), {"a": "A", "b": "B"})

    def test_unicode_whitespace_table_matches_runtime_strip_semantics(self):
        actual = {chr(code) for code in range(0x110000) if chr(code).isspace()}
        self.assertEqual(actual, set(protocol._UNICODE_WHITESPACE))

    def test_legacy_flex_functions_and_version_are_exactly_unchanged(self):
        # Frozen from the original v4 flex protocol; independent of staging paths.
        expected = {'_ids': 'a8d28a3b138fb330ddfe075dfb5febd8fa8338e7d936be637b46c58fb3754c49', 'render_prompt': '5739d1910f2ccf45123430178eecc71df5bd9faf181c7182b722340c43922ad5', 'parse_id_text': '4809b86247b999597e56cfa39f71e8dc6a7ca40059368bf8fef0883398b7cb9d'}
        after = ast.parse(Path(protocol.__file__).read_text())
        for name, digest in expected.items():
            node = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(hashlib.sha256(ast.dump(node).encode()).hexdigest(), digest)
        self.assertEqual(protocol.VERSION, "id-text-exact-markers-flex-v1")
        legacy = "[[a]]\nfirst\nsecond\n\n[[b]]last"
        self.assertEqual(protocol.parse_id_text(legacy, ["a", "b"]), {"a": "first\nsecond", "b": "last"})

    def test_new_request_has_exact_ordered_text_grammar_and_legacy_flex_has_none(self):
        ids = window()["translate_ids"]
        request = recipes.completion_request(settings(), [1, 2], ids)
        self.assertEqual(request["grammar"], protocol.ordered_grammar(ids))
        self.assertNotIn('"translations"', request["grammar"])
        self.assertNotIn("readonly-after", request["grammar"])
        self.assertNotIn("grammar", recipes.completion_request(settings("id-text-flex"), [1, 2], ids))
        self.assertEqual(recipes.completion_request(settings("c0"), [1, 2], ids)["grammar"], adapters.id_grammar(ids))

    def test_worker_delivers_plaintext_and_preserves_native_grammar_request_identity(self):
        client = FakeClient([valid_text()])
        budget = worker.Budget({"max_translation_calls": 2, "max_judge_calls": 0, "max_estimated_tokens": 100000, "max_wall_seconds": 100})
        row = worker.run_window(client, window(), settings(), 8192, budget, {"verified": False, "first_response_checked": False})
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(row["native_protocol"], protocol.ORDERED_VERSION)
        self.assertEqual(row["translations"], {uid: "synthetic" for uid in window()["translate_ids"]})
        self.assertEqual(client.requests[0]["grammar"], protocol.ordered_grammar(window()["translate_ids"]))
        self.assertEqual(row["attempts"][0]["request_sha256"], worker.object_hash(client.requests[0]))
        self.assertEqual(row["auxiliary_seconds"], 0)
        self.assertEqual(budget.translation_calls, 1)

    def test_worker_rejects_bad_native_even_if_transport_ignores_grammar(self):
        client = FakeClient([valid_text() + "\n[[readonly-after]]synthetic"] * 2)
        budget = worker.Budget({"max_translation_calls": 2, "max_judge_calls": 0, "max_estimated_tokens": 100000, "max_wall_seconds": 100})
        row = worker.run_window(client, window(), settings(), 8192, budget, {"verified": False, "first_response_checked": False})
        self.assertEqual(row["status"], "translation_failed")
        self.assertEqual(row["translations"], {})
        self.assertEqual(len(client.requests), 2)

    def test_budget_guard_stops_before_dispatch_without_source_truncation(self):
        client = FakeClient([], tokens=4033)
        budget = worker.Budget({"max_translation_calls": 2, "max_judge_calls": 0, "max_estimated_tokens": 100000, "max_wall_seconds": 100})
        row = worker.run_window(client, window(), settings(), 8192, budget, {"verified": False, "first_response_checked": False})
        self.assertEqual(row["error_kind"], "budget")
        self.assertEqual(client.requests, [])

    def test_new_review_rejected_without_modifying_legacy_options(self):
        with self.assertRaisesRegex(ValueError, "single nonJSON"):
            recipes.render_window("id-text-ordered", window(), settings(review=True))
        with self.assertRaisesRegex(ValueError, "single nonJSON"):
            recipes.validate_options(settings(review=True), set(window()["translate_ids"]))
        recipes.validate_options(settings("base-json", review=True), set(window()["translate_ids"]))

    def test_exact_session_plan_loads_new_recipe_and_source_order(self):
        stage = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=stage) as temporary:
            root = Path(temporary)
            inputs = root / "inputs.jsonl"
            inputs.write_text(json.dumps(window(), ensure_ascii=False) + "\n", encoding="utf-8")
            item = {**settings(), "inputs": "inputs.jsonl", "input_sha256": worker.sha256(inputs)}
            plan = {"schema": worker.SCHEMA, "stage": "qualification", "lane": "P-flow",
                    "budgets": {"max_translation_calls": 2, "max_judge_calls": 0,
                                "max_estimated_tokens": 100000, "max_wall_seconds": 100},
                    "experiment_identity": {"source_manifest_sha256": "0" * 64, "split": "screening",
                                            "seed": item["seed"], "recipe_id": item["label"],
                                            "source_order_sha256": worker.object_hash([window()["id"]])},
                    "cache_reset": {"method": "fresh-managed-server", "verification": "first-completion-cache-n-zero"},
                    "workloads": [item]}
            path = root / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            _, loaded = worker.load_plan(path)
            self.assertEqual(loaded[0][0]["recipe"], "id-text-ordered")
            self.assertEqual(loaded[0][2], [window()])

    def test_prompt_only_declares_new_layout_and_source_target_data(self):
        prompt = recipes.render_window("id-text-ordered", window(), settings())
        self.assertIn("同一行", prompt)
        self.assertIn("普通单个方括号", prompt)
        self.assertIn(json.dumps(window()["translate_ids"], ensure_ascii=False), prompt)
        self.assertIn("也可以从标记的下一行开始", protocol.render_prompt(window()))


if __name__ == "__main__":
    unittest.main()
