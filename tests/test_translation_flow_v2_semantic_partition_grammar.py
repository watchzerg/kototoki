"""Offline language checks for the immutable partition state grammar.

The small recognizer handles this module's fixed-terminal, reference and choice
productions only. It is independent of the compiler and is not a ggml engine.
"""

from copy import deepcopy
from functools import lru_cache
from itertools import combinations
import json
import re
import unittest

from experiments.translation_flow import v2_semantic_structured as structured
from experiments.translation_flow import v2_semantic_partition_grammar as partition


def accepts_mapping(grammar, text):
    rules = {}
    decoder = json.JSONDecoder()
    for line in grammar.split('\n'):
        if "::=" not in line:
            continue
        name, body = line.split("::=", 1)
        name = name.strip()
        if name in {"ws", "string", "char", "boolean", "unresolved", "root"}:
            continue
        alternatives, tokens, pos = [], [], 0
        while pos < len(body):
            if body[pos].isspace():
                pos += 1
            elif body[pos] == '|':
                alternatives.append(tokens)
                tokens = []
                pos += 1
            elif body[pos] == '"':
                value, count = decoder.raw_decode(body[pos:])
                tokens.append(("literal", value))
                pos += count
            else:
                token = re.match(r"[a-zA-Z][a-zA-Z0-9-]*", body[pos:])
                if token is None:
                    raise AssertionError(f"Unsupported test grammar token: {body[pos:]}")
                tokens.append(("reference", token.group()))
                pos += len(token.group())
        rules[name] = alternatives + [tokens]

    @lru_cache(None)
    def match(name, pos):
        if name == "ws":
            return {pos, pos + 1} if pos < len(text) and text[pos] in " \t\n\r" else {pos}
        ends = set()
        for sequence in rules.get(name, []):
            positions = {pos}
            for kind, value in sequence:
                next_positions = set()
                for start in positions:
                    if kind == "literal":
                        if text.startswith(value, start):
                            next_positions.add(start + len(value))
                    else:
                        next_positions.update(match(value, start))
                positions = next_positions
            ends.update(positions)
        return ends

    return len(text) in match("mapping", 0)


class PartitionGrammarTests(unittest.TestCase):
    def fixture(self, text="是。是。", count=2):
        ids = [f"s{i}" for i in range(count)]
        window = {"id": "synthetic", "source_language": "ja", "target_language": "zh-Hans",
                  "context": [{"id": sid, "text": "源文"} for sid in ids], "translate_ids": ids}
        content = None if count == 1 else json.dumps({"boundaries": [
            {"join": True, "evidence_ids": ids, "uncertain": True} for _ in ids[1:]]})
        plan = structured.parse_plan(content, window)
        return window, plan, {"u1": text}

    @staticmethod
    def response(texts, unit="u1", ids=None):
        ids = [f"s{i}" for i in range(len(texts))] if ids is None else ids
        return {"segments": [{"unit_id": unit, "source_id": sid, "text": text}
                             for sid, text in zip(ids, texts, strict=True)]}

    @staticmethod
    def encode(obj):
        return json.dumps(obj, ensure_ascii=False)

    def test_all_nonblank_cut_choices_accepted_without_punctuation_heuristic(self):
        for text, count in (("是。是。", 2), ("a b c", 3), ("A\t B\nC", 2), ("a\u0301🌧️b", 3),
                            ("\u0085甲\u2028乙\u2029", 2), ("甲\x00乙", 2)):
            window, plan, native = self.fixture(text, count)
            built = partition.build_mapping_grammar(window, plan, native)
            for cuts in combinations(range(1, len(text)), count - 1):
                bounds = (0, *cuts, len(text))
                parts = [text[a:b] for a, b in zip(bounds, bounds[1:])]
                response = self.encode(self.response(parts))
                expected = all(piece.strip() for piece in parts)
                with self.subTest(text=text, cuts=cuts):
                    self.assertEqual(accepts_mapping(built["grammar"], response), bool(expected))
                    if expected:
                        mapped = partition.parse_mapping(response, window, plan, native)
                        self.assertEqual("".join(mapped["translations"].values()), text)

    def test_immutable_json_escaping_quotes_slashes_controls_and_nonbmp(self):
        text = ' 甲"\\\t🌧️\n乙\b\f\r。 '
        window, plan, native = self.fixture(text)
        parts = [text[:8], text[8:]]
        response = self.encode(self.response(parts))
        grammar = partition.mapping_grammar(window, plan, native)
        self.assertTrue(accepts_mapping(grammar, response))
        mapped = partition.parse_mapping(response, window, plan, native)
        self.assertEqual(mapped["source_span_to_target_span"][0]["target_spans"], [[0, 8]])
        self.assertEqual(mapped["translations"]["s0"] + mapped["translations"]["s1"], text)
        self.assertNotEqual(len(text), len(text.encode("utf-16-le")) // 2)
        self.assertIn('ws ::= [ \\t\\n\\r]?', grammar)

    def test_deletion_replacement_reordering_and_whole_paragraph_copy_rejected(self):
        window, plan, native = self.fixture("是。后面。")
        grammar = partition.mapping_grammar(window, plan, native)
        for parts in (("是", "后面。"), ("是。", "后面！"), ("后面。", "是。"),
                      (native["u1"], native["u1"]), ("是。", " ")):
            response = self.encode(self.response(parts))
            with self.subTest(parts=parts):
                self.assertFalse(accepts_mapping(grammar, response))
                with self.assertRaises(ValueError):
                    partition.parse_mapping(response, window, plan, native)

    def test_source_identity_order_is_fixed_including_escaped_ids(self):
        window, plan, native = self.fixture("甲乙")
        escaped = 's"\\日'
        window["context"][0]["id"] = escaped
        window["translate_ids"][0] = escaped
        plan["units"][0]["source_ids"][0] = escaped
        plan["units"][0]["evidence_ids"][0] = escaped
        grammar = partition.mapping_grammar(window, plan, native)
        response = self.response(["甲", "乙"], ids=[escaped, "s1"])
        self.assertTrue(accepts_mapping(grammar, self.encode(response)))
        for rows in (response["segments"][:1], list(reversed(response["segments"])),
                     response["segments"] + [response["segments"][0]]):
            self.assertFalse(accepts_mapping(grammar, self.encode({"segments": rows})))

    def test_multiple_units_with_singleton_preserve_unit_local_offsets(self):
        window, _, _ = self.fixture(count=5)
        decisions = {"boundaries": [{"join": join, "evidence_ids": ["s0"], "uncertain": False}
                                    for join in (True, False, False, True)]}
        plan = structured.parse_plan(self.encode(decisions), window)
        native = {"u1": "甲。乙。", "u2": " 单独。 ", "u3": "🌧️雨。"}
        rows = self.response(["甲。", "乙。"])["segments"]
        rows += self.response(["🌧️", "雨。"], "u3", ["s3", "s4"])["segments"]
        response = self.encode({"segments": rows})
        built = partition.build_mapping_grammar(window, plan, native)
        self.assertTrue(accepts_mapping(built["grammar"], response))
        result = partition.parse_mapping(response, window, plan, native)
        self.assertEqual(result["translations"]["s2"], native["u2"])
        self.assertEqual(result["source_span_to_target_span"][-1]["target_spans"], [[2, 4]])
        self.assertEqual(built["diagnostics"]["multi_cue_unit_count"], 2)
        self.assertEqual(result["mapping_provenance"]["protocol"], partition.PROTOCOL)
        self.assertFalse(result["mapping_provenance"]["semantic_correspondence_verified"])
        self.assertNotIn("grammar_applied", result["mapping_provenance"])
        reversed_units = self.encode({"segments": rows[2:] + rows[:2]})
        self.assertFalse(accepts_mapping(built["grammar"], reversed_units))

    def test_too_few_nonblank_characters_only_allows_explicit_unresolved(self):
        window, plan, native = self.fixture(" 甲 \n", count=3)
        built = partition.build_mapping_grammar(window, plan, native)
        self.assertEqual(built["grammar"].splitlines()[0], "root ::= unresolved")
        self.assertFalse(built["diagnostics"]["mapping_feasible"])
        self.assertEqual(built["diagnostics"]["infeasible_unit_ids"], ["u1"])
        self.assertEqual(built["diagnostics"]["state_count"], 0)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            partition.parse_mapping('{"unresolved":true,"reason":"无法对应"}', window, plan, native)

    def test_singleton_no_mapping_generation_or_grammar(self):
        window, plan, native = self.fixture("🌧️。", count=1)
        self.assertFalse(partition.mapping_required(window, plan))
        result = partition.parse_mapping(None, window, plan, native)
        self.assertFalse(result["mapping_provenance"]["model_mapping_required"])
        with self.assertRaisesRegex(ValueError, "unnecessary"):
            partition.build_mapping_grammar(window, plan, native)
        with self.assertRaises(ValueError):
            partition.mapping_prompt(window, plan, native)

    def test_caps_fail_explicitly_without_text_truncation_or_fallback(self):
        window, plan, native = self.fixture("甲乙丙丁", count=3)
        original = deepcopy(native)
        for kwargs in ({"max_states": 1}, {"max_grammar_bytes": 100}):
            with self.assertRaises(partition.GrammarComplexityError) as caught:
                partition.build_mapping_grammar(window, plan, native, **kwargs)
            diagnostics = caught.exception.diagnostics
            limit = next(iter(kwargs))
            self.assertEqual(diagnostics["exceeded_limit"], limit)
            observed = "state_count" if limit == "max_states" else "grammar_bytes"
            self.assertGreater(diagnostics[observed], kwargs[limit])
            self.assertEqual(diagnostics["native_codepoint_count"], len(native["u1"]))
            self.assertFalse(diagnostics["native_text_truncated"])
            if limit == "max_states":
                self.assertIsNone(diagnostics["grammar_bytes"])
                self.assertEqual(diagnostics["state_count_scope"],
                                 "completed-units-plus-current-discovered-states")
        self.assertEqual(native, original)
        for limit in (0, -1, True, 2.5):
            with self.assertRaises(ValueError):
                partition.build_mapping_grammar(window, plan, native, max_states=limit)

    def test_state_growth_is_linear_in_cues_times_native_codepoints(self):
        for length in (16, 32, 64):
            window, plan, native = self.fixture("甲" * length, count=5)
            built = partition.build_mapping_grammar(window, plan, native)
            self.assertLessEqual(built["diagnostics"]["state_count"], 2 * 5 * (length + 1))
            self.assertEqual(built["diagnostics"]["grammar_bytes"], len(built["grammar"].encode("utf-8")))
            self.assertNotIn("char+", next(line for line in built["grammar"].splitlines() if line.startswith("mapping ::= ")))

    def test_json_syntax_whitespace_cannot_loop_or_mutate_native_whitespace(self):
        window, plan, native = self.fixture(" 甲 乙 ")
        grammar = partition.mapping_grammar(window, plan, native)
        response = self.encode(self.response([" 甲 ", "乙 "]))
        self.assertTrue(accepts_mapping(grammar, response))
        self.assertFalse(accepts_mapping(grammar, response + "\t" * 4096))
        self.assertFalse(accepts_mapping(grammar, response.replace('"segments": ', '"segments":  ')))

    def test_planning_wrapper_only_bounds_syntax_whitespace_preserves_decisions(self):
        window, plan, native = self.fixture("甲乙")
        grammar = partition.planning_grammar(window)
        self.assertEqual(grammar.replace(r"ws ::= [ \t\n\r]?", r"ws ::= [ \t\n\r]*"),
                         structured.planning_grammar(window))
        decisions = {"boundaries": [{"join": True, "evidence_ids": ["s0", "s1"], "uncertain": True}]}
        parsed = partition.parse_planning(self.encode(decisions), window)
        self.assertEqual(parsed["semantic_plan"], plan)
        self.assertEqual(parsed["planning_provenance"]["protocol"], partition.PLANNING_PROTOCOL)
        self.assertEqual(parsed["planning_provenance"]["planning_grammar_variant"],
                         "syntax-whitespace-zero-or-one-v1")
        self.assertEqual(partition.planning_prompt(window), structured.planning_prompt(window))
        self.assertEqual(partition.native_prompt(window, plan), structured.native_prompt(window, plan))
        self.assertEqual(partition.mapping_prompt(window, plan, native), structured.mapping_prompt(window, plan, native))
        self.assertTrue(partition.planning_required(window))
        with self.assertRaisesRegex(ValueError, "unresolved"):
            partition.parse_planning('{"unresolved":true,"reason":"不明确"}', window)
        single_window, single_plan, _ = self.fixture("甲", count=1)
        self.assertFalse(partition.planning_required(single_window))
        self.assertEqual(partition.parse_plan(None, single_window), single_plan)

    def test_protected_fields_and_non_unicode_scalar_native_rejected(self):
        window, plan, native = self.fixture("甲乙")
        contaminated = dict(window, reference={"s0": "forbidden"})
        with self.assertRaisesRegex(ValueError, "frozen model-input"):
            partition.mapping_grammar(contaminated, plan, native)
        with self.assertRaisesRegex(ValueError, "Unicode scalar"):
            partition.mapping_grammar(window, plan, {"u1": "甲\ud800乙"})


if __name__ == "__main__":
    unittest.main()
