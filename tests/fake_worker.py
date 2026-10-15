"""编排器测试用的假 GPU worker：按计划文件逐文件写出阶段产物，不加载任何模型；身份经 `kototoki.plan` 取得，
PCM SHA256 与真 worker 一样由 `gpu.read_wav` 从 `audio-16k.wav` 算出。

用法同真 worker：`python fake_worker.py <stage> --jobs <jobs.json>`。

环境变量：
- `KOTOTOKI_FAKE_PLAN`：JSON `{stage: {相对路径或 work id: 动作}}`，缺省动作 `ok`。
  动作：`ok`、`fail`（普通异常）、`fatal`（FatalWorkerError）、`crash`（写产物前 `os._exit(3)`）、
  `startup`（`start()` 中抛错）、`empty`（仅 vad：无语音）。
- `KOTOTOKI_FAKE_LOG`：每行一条 JSON 记录——`launch`（pid、文件 id、子进程环境、GPU 锁快照）与 `file`（逐文件）。
- `KOTOTOKI_FAKE_GPU_LOCK`：GPU 锁路径；launch 记录里带锁内容（等编排器写入本 worker 的 pid 后再读）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

# 作为脚本运行时 sys.path[0] 是 tests 目录；把仓库根放进去才能导入 kototoki。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kototoki import artifacts, plan  # noqa: E402
from kototoki.workers import gpu  # noqa: E402
from kototoki.workers.protocol import FatalWorkerError, run_worker  # noqa: E402

# 测试里 `gpu.verify_models` 被打补丁返回同一份映射，编排器与本 worker 算出的身份才一致。
FAKE_MODELS = {"fake-model": "b" * 64}
ENV_KEYS = ("PYTHONUTF8", "HF_HOME", "TORCH_HOME", "HF_HUB_OFFLINE")


def append_log(record: dict) -> None:
    path = os.environ.get("KOTOTOKI_FAKE_LOG")
    if path:
        with open(path, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def lock_snapshot() -> dict | None:
    """编排器在 Popen 之后才把 worker_pid 写进锁；轮询到它出现（最多 10 s）再取快照。

    Windows 上 venv 的 python.exe 是启动器，会再起真正的解释器，`Popen.pid` 可能是父进程，
    所以不比较 pid，只等上一个 worker 的记录被清掉、新的写入。
    """
    path = os.environ.get("KOTOTOKI_FAKE_GPU_LOCK")
    if not path:
        return None
    deadline = time.monotonic() + 10
    while True:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if (data and data.get("worker_pid") is not None) or time.monotonic() > deadline:
            return data
        time.sleep(0.02)


def main(argv: list[str]) -> int:
    stage = argv[1]
    jobs_path = Path(argv[argv.index("--jobs") + 1])
    plan_path = os.environ.get("KOTOTOKI_FAKE_PLAN")
    actions_by_stage = json.loads(Path(plan_path).read_text(encoding="utf-8")) if plan_path and Path(plan_path).is_file() else {}
    by_key = actions_by_stage.get(stage, {})
    actions = {**by_key, **{artifacts.work_id(key): action for key, action in by_key.items()}}

    def start(jobs):
        ids = [file.id for file in jobs.files]
        append_log({"kind": "launch", "stage": stage, "pid": os.getpid(), "ppid": os.getppid(), "ids": ids,
                    "env": {key: os.environ.get(key) for key in ENV_KEYS}, "lock": lock_snapshot()})
        if any(actions.get(i) == "startup" for i in ids):
            raise RuntimeError("fake startup failure")

        def process(job):
            action = actions.get(job.id, "ok")
            append_log({"kind": "file", "stage": stage, "id": job.id, "pid": os.getpid(), "action": action})
            if action == "crash":
                os._exit(3)
            if action == "fatal":
                raise FatalWorkerError("fake fatal error")
            if action == "fail":
                raise RuntimeError("fake failure")
            payload: dict = {"offset_s": 0}
            if stage == "vad":
                payload["chunks"] = [] if action == "empty" else [{"start_s": 0.0, "end_s": 1.0}]
            _, pcm = gpu.read_wav(job.inputs["wav"])  # 与真 worker 一样从 WAV 算 PCM SHA256
            if stage == "vad":
                identity = plan.vad_identity(pcm, FAKE_MODELS)
            elif stage == "asr":
                identity = plan.asr_identity(jobs.config["engine"], pcm, artifacts.sha256_file(job.inputs["vad"]), FAKE_MODELS)
            else:
                identity = plan.align_identity(pcm, artifacts.sha256_file(job.inputs["asr"]), FAKE_MODELS)
            artifacts.write_artifact(job.work_dir / plan.STAGE_OUTPUT[stage], identity, payload)
            return {"stage": stage}

        return process

    return run_worker(jobs_path, start)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
