"""llama-server 并行槽位探针（票据 07）：同一真实配方，串行与 `-np P` 并行各生成一次，比较墙钟与输出。

不改 v3／v4 代码：运行时替换 `translation_v3.server.server_command` 的 `-np 1`（总上下文 8192 不变，每槽
8192／P；v4 的 mbr8 单请求最多 1243 token，P≤4 都放得下，KV 显存不变），并把 `translation_v3.generate._multi_sample`
换成同批 N 个样本按 P 个线程并发请求的版本（样本序号、seed、记录顺序与串行相同，选择器不变）。P＝1 时两处都不替换，
等于 v4 原样生成。之后照常调用 v4 的 `generate` 命令。

命令（仓库根目录，`.venv`；GPU 作业）：
  python -X utf8 -m experiments.quality_v5.parallel_probe --parallel 2 -- --root ROOT generate --recipe mbr4c --seed 20261011 --set dev
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import sys
from typing import Any


def patch(parallel: int) -> None:
    from experiments.translation_v3 import generate as G
    from experiments.translation_v3 import recipes as R
    from experiments.translation_v3 import server as S

    original_command = S.server_command

    def server_command(*args: Any, **kwargs: Any) -> list[str]:
        command = original_command(*args, **kwargs)
        index = command.index("-np")
        return command[:index + 1] + [str(parallel)] + command[index + 2:]

    def multi_sample(client: Any, prompt: str, grammar: str, seed: int, ids: list[str], recipe: Any,
                     cache_state: dict[str, Any], row: dict[str, Any], info: dict[str, Any],
                     batch_index: int) -> dict[str, str]:
        from experiments.translation_v3.mbr import select

        records = [{"stage": "translation", "batch_index": batch_index, "sample": k} for k in range(recipe.candidates)]
        row["requests"].extend(records)

        def one(k: int) -> Any:
            try:
                return G.run_step(client, prompt, grammar, R.sample_seed(seed, k),
                                  lambda text: R.parse_translation(text, ids), cache_state, records[k], recipe.sampling)
            except G.StepFailed as exc:
                return exc

        with ThreadPoolExecutor(max_workers=parallel) as pool:
            results = list(pool.map(one, range(recipe.candidates)))
        samples, failed, last = [], [], None
        for k, result in enumerate(results):
            if isinstance(result, G.StepFailed):
                if result.kind in G.INFRA_KINDS or result.kind == "context":
                    raise result
                failed.append({"sample": k, "kind": result.kind})
                last = result
            else:
                samples.append(result)
        if not samples:
            assert last is not None
            raise last
        selected, choice = select(recipe.selector, samples, ids)
        info.update(candidates=samples, failed_samples=failed, selection=choice, parallel_slots=parallel)
        return selected

    S.server_command = server_command
    G._multi_sample = multi_sample


def main() -> int:
    parser = argparse.ArgumentParser(description="llama-server 并行槽位探针（票据 07）")
    parser.add_argument("--parallel", type=int, required=True)
    parser.add_argument("v4_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.parallel > 1:
        patch(args.parallel)
    from experiments.translation_v4.cli import main as v4_main

    v4_args = args.v4_args[1:] if args.v4_args[:1] == ["--"] else args.v4_args
    return v4_main(v4_args)


if __name__ == "__main__":
    sys.exit(main())
