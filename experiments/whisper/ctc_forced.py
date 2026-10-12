"""Standard CTC nonblank spans using the pinned TorchAudio 2.8 decoder."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from typing import Any, Iterator

from ctc_transition import TransitionRecorder


class ForcedRecorder(TransitionRecorder):
    def __init__(self, *args: Any, device: str):
        super().__init__(*args)
        self.device = device

    def observe(self, trellis: Any, emission: Any, tokens: list[int], blank_id: int, path: Any) -> None:
        import torch
        from torchaudio.functional import forced_align, merge_tokens
        index = len(self.records)
        if index >= len(self.eligible):
            raise ValueError("Unexpected native forward count for standard CTC mapping")
        segment_index, positions = self.eligible[index]
        record = {"segment_index": segment_index, "frame_count": int(emission.shape[0]),
                  "emission_sha256": hashlib.sha256(emission.numpy().tobytes()).hexdigest(),
                  "emission_shape": list(emission.shape), "blank_id": blank_id,
                  "native_path_failed": path is None, "tokens": [], "failure": None}
        self.records.append(record)
        if len(tokens) != len(positions):
            record["failure"] = "token_character_count_mismatch"
            return
        try:
            inputs = emission.unsqueeze(0).to(self.device)
            targets = torch.tensor([tokens], device=self.device, dtype=torch.int64)
            record["decoder_input_device"] = str(inputs.device)
            if self.device.startswith("cuda") and inputs.device.type != "cuda":
                raise RuntimeError("Standard CTC CPU fallback prohibited")
            labels, scores = forced_align(inputs, targets, blank=blank_id)
            record["decoder_output_device"] = str(labels.device)
            if labels.device != inputs.device:
                raise RuntimeError("Standard CTC decoder output changed device")
            spans = merge_tokens(labels[0], scores[0].exp(), blank=blank_id)
            if len(spans) != len(tokens) or any(s.token != t for s, t in zip(spans, tokens)):
                record["failure"] = "collapsed_path_differs_from_target"
                return
            record["path_sha256"] = hashlib.sha256(labels.detach().cpu().numpy().tobytes()).hexdigest()
            for index, (span, position) in enumerate(zip(spans, positions)):
                known = self.segments[segment_index]["text"][position].lower() in self.dictionary
                record["tokens"].append({"token_index": index, "original_position": position,
                                          "token_id": span.token, "start_frame": span.start, "end_frame": span.end,
                                          "token_probability": span.score,
                                          "evidence_kind": "vocabulary_token" if known else "wildcard",
                                          "lexical_interval_accepted": known})
        except (RuntimeError, ValueError) as error:
            # Preserve the complete text and failure accounting; never decode on
            # a different device as a recovery path.
            record["failure"] = f"{type(error).__name__}: {error}"

    def derived_segments(self) -> list[dict[str, Any]]:
        by_index = {r["segment_index"]: r for r in self.records}
        output = []
        for index, segment in enumerate(self.segments):
            record = by_index.get(index)
            evidence = {t["original_position"]: t for t in record["tokens"]} if record else {}
            chars = []
            for position, char in enumerate(segment["text"]):
                token = evidence.get(position)
                valid = bool(token and token["lexical_interval_accepted"] and record["frame_count"] > 0
                             and 0 <= token["start_frame"] < token["end_frame"] <= record["frame_count"])
                ratio = (segment["end"] - segment["start"]) / record["frame_count"] if record and record["frame_count"] else 0
                chars.append({"char": char, "start": round(segment["start"] + token["start_frame"] * ratio, 3) if valid else None,
                              "end": round(segment["start"] + token["end_frame"] * ratio, 3) if valid else None,
                              "score": token["token_probability"] if token else None,
                              "evidence_kind": token["evidence_kind"] if token else "missing",
                              "time_semantics": "ctc_nonblank_token_span"})
            output.append({"text": segment["text"], "start": segment["start"], "end": segment["end"], "chars": chars})
        return output


@contextmanager
def capture_forced(module: Any, segments: list[dict[str, Any]], dictionary: dict[str, int],
                   duration: float, *, device: str) -> Iterator[ForcedRecorder]:
    recorder = ForcedRecorder(segments, dictionary, duration, device=device)
    original = module.backtrack

    def wrapper(trellis: Any, emission: Any, tokens: list[int], blank_id: int = 0) -> Any:
        native = original(trellis, emission, tokens, blank_id)
        recorder.observe(trellis, emission, tokens, blank_id, native)
        return native

    module.backtrack = wrapper
    try:
        yield recorder
    finally:
        module.backtrack = original
