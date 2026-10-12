"""Small synthetic GGUF checks; optional native no-allocation loader test."""

import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from .inspect_gguf import inspect


def fixture(path: Path, legacy_bias: bool) -> None:
    """Write synthetic zeros, never derived weights, for loader-name testing."""
    def string(value: str) -> bytes:
        raw = value.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    def encode(kind, value):
        if kind == 8:
            return string(value)
        if kind == 4:
            return struct.pack("<I", value)
        if kind == 6:
            return struct.pack("<f", value)
        if kind == 7:
            return struct.pack("<?", value)
        if kind == 9:
            item_type, values = value
            return struct.pack("<IQ", item_type, len(values)) + b"".join(encode(item_type, item) for item in values)
        if kind == 5:
            return struct.pack("<i", value)
        raise ValueError(kind)

    metadata = {
        "general.architecture": (8, "hy_v3"), "general.name": (8, "synthetic-loader-only-no-inference"),
        "hy_v3.block_count": (4, 1), "hy_v3.context_length": (4, 128), "hy_v3.embedding_length": (4, 128),
        "hy_v3.feed_forward_length": (4, 32), "hy_v3.attention.head_count": (4, 1), "hy_v3.attention.head_count_kv": (4, 1),
        "hy_v3.attention.key_length": (4, 128), "hy_v3.attention.value_length": (4, 128), "hy_v3.rope.dimension_count": (4, 128),
        "hy_v3.rope.freq_base": (6, 10000.0), "hy_v3.attention.layer_norm_rms_epsilon": (6, 0.00001),
        "hy_v3.expert_count": (4, 2), "hy_v3.expert_used_count": (4, 1), "hy_v3.expert_feed_forward_length": (4, 32),
        "hy_v3.expert_shared_feed_forward_length": (4, 32), "hy_v3.expert_weights_norm": (7, True), "hy_v3.expert_weights_scale": (6, 1.0),
        "hy_v3.expert_gating_func": (4, 2), "tokenizer.ggml.model": (8, "llama"),
        "tokenizer.ggml.tokens": (9, (8, ["<unk>", "<s>", "</s>", "x"])),
        "tokenizer.ggml.scores": (9, (6, [0.0] * 4)), "tokenizer.ggml.token_type": (9, (5, [2, 3, 3, 1])),
        "tokenizer.ggml.bos_token_id": (4, 1), "tokenizer.ggml.eos_token_id": (4, 2), "tokenizer.ggml.unknown_token_id": (4, 0),
    }
    tensors = {"token_embd.weight": [128, 4], "output.weight": [128, 4], "output_norm.weight": [128]}
    for suffix in ("attn_q.weight", "attn_k.weight", "attn_v.weight", "attn_output.weight"):
        tensors["blk.0." + suffix] = [128, 128]
    for suffix in ("attn_norm.weight", "attn_q_norm.weight", "attn_k_norm.weight", "ffn_norm.weight"):
        tensors["blk.0." + suffix] = [128]
    tensors["blk.0.ffn_gate_inp.weight"] = [128, 2]
    tensors["blk.0.exp_probs_b" + (".bias" if legacy_bias else "")] = [2]
    tensors["blk.0.ffn_down_exps.weight"] = [32, 128, 2]
    for suffix in ("ffn_up_exps.weight", "ffn_gate_exps.weight"):
        tensors["blk.0." + suffix] = [128, 32, 2]
    tensors["blk.0.ffn_down_shexp.weight"] = [32, 128]
    for suffix in ("ffn_up_shexp.weight", "ffn_gate_shexp.weight"):
        tensors["blk.0." + suffix] = [128, 32]
    header = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(metadata))
    header += b"".join(string(key) + struct.pack("<I", kind) + encode(kind, value) for key, (kind, value) in metadata.items())
    offset = 0
    data = bytearray()
    for name, shape in tensors.items():
        header += string(name) + struct.pack("<I", len(shape)) + b"".join(struct.pack("<Q", size) for size in shape) + struct.pack("<IQ", 0, offset)
        count = 1
        for size in shape:
            count *= size
        length = count * 4
        data.extend(b"\0" * length)
        data.extend(b"\0" * (-len(data) % 32))
        offset = len(data)
    header += b"\0" * (-len(header) % 32)
    with path.open("xb") as stream:
        stream.write(header)
        stream.write(data)


class CompatTests(unittest.TestCase):
    def test_descriptor_inspection_and_native_name_compatibility(self):
        root = Path(__file__).resolve().parents[2] / ".local/translation-evaluation/20261006-v1/hy30-compat/synthetic-tests"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            for legacy in (False, True):
                path = Path(directory) / ("legacy.gguf" if legacy else "canonical.gguf")
                fixture(path, legacy)
                record = inspect(path)
                self.assertEqual(record["tensor_count"], 19)
                router = [item for item in record["tensors"] if "exp_probs_b" in item["name"]]
                self.assertEqual(router[0]["shape"], [2])
                self.assertTrue(router[0]["name"].endswith(".bias") == legacy)
                checker = os.environ.get("LLAMA_NO_ALLOC_CHECKER")
                cpu = os.environ.get("LLAMA_NO_ALLOC_CPU_BACKEND")
                if checker and cpu:
                    result = subprocess.run([checker, cpu, str(path)], capture_output=True, text=True, encoding="utf-8")
                    (root / ("legacy-native.log" if legacy else "canonical-native.log")).write_text(result.stdout + result.stderr, encoding="utf-8")
                    self.assertEqual(result.returncode, 0, result.stderr[-3000:])
                    self.assertIn("PASS: metadata and all tensor descriptors", result.stdout)


if __name__ == "__main__":
    unittest.main()
