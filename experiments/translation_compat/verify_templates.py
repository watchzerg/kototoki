"""Compare adapters against actual GGUF Jinja for single-user native prompts."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from experiments.translation_demo import adapters
from experiments.translation_demo.gguf import metadata


FAMILIES = {
    "hy-mt2-7b-q8": "hy-mt2",
    "hy-mt2-30b-a3b-q3-k-m": "hy-mt2-30b",
    "tower-plus-9b-q8": "tower-plus",
}
BOUNDS = {
    "hy-mt2": ("<|startoftext|>", "<|extra_0|>"),
    "hy-mt2-30b": ("<｜hy_begin▁of▁sentence｜><｜reasoning_mode｜>reasoning_effort:no_think<｜hy_User｜>", "<｜hy_Assistant｜><think></think>"),
    "tower-plus": ("<bos><start_of_turn>user\n", "<end_of_turn>\n<start_of_turn>model\n"),
}
WINDOW = {
    "id": "synthetic-template-check",
    "source_language": "ja", "target_language": "zh-Hans",
    "context": [{"id": "s0", "text": "明日、駅で待ってる。"}, {"id": "s1", "text": '渡さないで。「鍵」は二つある。'}],
    "translate_ids": ["s1"],
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    import jinja2
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, default=Path(".local/manifests/translation-download-plan.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assets = json.loads(args.assets.read_text(encoding="utf-8-sig"))
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, extensions=["jinja2.ext.loopcontrols"])

    def raise_exception(message):
        raise ValueError(message)

    env.globals["raise_exception"] = raise_exception
    checks = []
    for asset in assets:
        if asset["id"] not in FAMILIES:
            continue
        family = FAMILIES[asset["id"]]
        model = Path(asset["directory"]) / asset["file"]
        gguf = metadata(model)
        template = gguf["tokenizer.chat_template"]
        rendered = adapters.render(family, WINDOW)
        prefix, suffix = BOUNDS[family]
        if not rendered.startswith(prefix) or not rendered.endswith(suffix):
            raise ValueError("Adapter wrapping changed; inspect before verifying")
        task = rendered[len(prefix):-len(suffix)]
        flags = {"add_generation_prompt": True, "tools": None}
        if family == "hy-mt2-30b":
            flags["reasoning_effort"] = "no_think"
        special_tokens = {"bos_token": "<bos>" if family == "tower-plus" else "<|startoftext|>", "eos_token": "<end_of_turn>" if family == "tower-plus" else "<|eos|>"}
        if family == "hy-mt2-30b":
            special_tokens = {"bos_token": "<｜hy_begin▁of▁sentence｜>", "eos_token": "<eos:6124c78e>"}
        native = env.from_string(template).render(messages=[{"role": "user", "content": task}], **flags, **special_tokens)
        padded_task = " \n" + task + "\n "
        whitespace_native = env.from_string(template).render(messages=[{"role": "user", "content": padded_task}], **flags, **special_tokens)
        whitespace_adapter = adapters.wrap(family, padded_task)
        checks.append({
            "candidate": asset["id"], "family": family, "model_sha256": asset["sha256"],
            "model_size_verified": model.stat().st_size == asset["size"],
            "template_sha256": sha(template), "flags": flags, "messages": [{"role": "user", "content": task}],
            "special_token_kwargs": special_tokens, "native_jinja_rendered": native, "adapter_rendered": rendered,
            "exact_bytes_equal": native.encode("utf-8") == rendered.encode("utf-8"),
            "native_prompt_sha256": sha(native), "adapter_prompt_sha256": sha(rendered),
            "whitespace_diagnostic": {"exact_equal": whitespace_native == whitespace_adapter, "note_zh": "仅 Tower 模板会 trim user.content；当前真实 Adapter task 无首尾空白，主比较不受影响。" if whitespace_native != whitespace_adapter else "无差异。"},
        })
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(), "scope": "read-only single-user native-wrapper verification; synthetic source only; no GPU/inference",
        "python_executable": sys.executable, "jinja2_version": jinja2.__version__,
        "environment": {"class": "ImmutableSandboxedEnvironment", "trim_blocks": True, "lstrip_blocks": True, "extensions": ["jinja2.ext.loopcontrols"]},
        "adapter_source_sha256": hashlib.sha256(Path(adapters.__file__).read_bytes()).hexdigest(),
        "all_current_prompts_equal": len(checks) == 3 and all(check["exact_bytes_equal"] for check in checks), "checks": checks,
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    for check in checks:
        print(check["candidate"], "exact-bytes-equal", check["exact_bytes_equal"], "whitespace-diagnostic-equal", check["whitespace_diagnostic"]["exact_equal"])
    return 0 if output["all_current_prompts_equal"] else 1


if __name__ == "__main__":
    sys.exit(main())
