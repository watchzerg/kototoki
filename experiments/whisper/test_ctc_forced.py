import unittest
torch = forced_align = None
try:
    import torch
    from torchaudio.functional import forced_align
except ImportError:
    torch = forced_align = None

from ctc_forced import ForcedRecorder
from run import evaluation


@unittest.skipUnless(torch is not None and forced_align is not None,
                     "Run standard CTC tests in the pinned WhisperX environment")
class ForcedTests(unittest.TestCase):
    def decode(self, text, target, labels, dictionary):
        emission = torch.full((len(labels), max(target) + 1), -12.)
        for index, label in enumerate(labels): emission[index, label] = -.001
        recorder = ForcedRecorder([{"text": text, "start": 5., "end": 5. + len(labels) * .02}], dictionary, 10., device="cpu")
        recorder.observe(torch.empty(len(labels) + 1, len(target) + 1), emission, target, 0, None)
        self.assertIsNone(recorder.records[0]["failure"])
        return recorder

    def test_self_loops_blank_exclusion_source_offset(self):
        recorder = self.decode("AB", [1, 2], [0,1,1,1,0,0,0,0,2,2,2,0], {"a":1,"b":2})
        chars = recorder.derived_segments()[0]["chars"]
        self.assertEqual((chars[0]["start"], chars[0]["end"]), (5.02,5.08))
        self.assertEqual((chars[1]["start"], chars[1]["end"]), (5.16,5.22))
        result = evaluation(recorder.segments, recorder.derived_segments(), 100, character=True)
        self.assertEqual(result["units"][0]["end"],105.08)

    def test_duplicate_tokens_require_blank_separator(self):
        recorder = self.decode("AA", [1,1], [0,1,1,0,0,1,1,0], {"a":1})
        self.assertEqual([(t["start_frame"],t["end_frame"]) for t in recorder.records[0]["tokens"]], [(1,3),(5,7)])

    def test_wildcard_preserved_without_lexical_timestamp(self):
        recorder = self.decode("A?B", [1,3,2], [0,1,1,0,3,3,0,2,2,0], {"a":1,"b":2})
        chars = recorder.derived_segments()[0]["chars"]
        self.assertIsNone(chars[1]["start"])
        self.assertEqual(chars[1]["char"],"?")
        self.assertEqual(chars[1]["evidence_kind"],"wildcard")

    def test_short_sequence_preserves_failure_and_all_text(self):
        recorder = ForcedRecorder([{"text":"AA","start":0,"end":.02}], {"a":1}, 1., device="cpu")
        recorder.observe(torch.zeros(2,3),torch.tensor([[-10.,0.]]),[1,1],0,None)
        self.assertIsNotNone(recorder.records[0]["failure"])
        chars = recorder.derived_segments()[0]["chars"]
        self.assertEqual("".join(c["char"] for c in chars),"AA")
        self.assertTrue(all(c["start"] is None for c in chars))


if __name__ == "__main__": unittest.main()
