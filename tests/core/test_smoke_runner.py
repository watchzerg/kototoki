"""`scripts/smoke/run_all.py` 的步骤输出与子进程回收：用临时目录里的假步骤脚本，不跑真实 smoke、不碰 GPU。"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from kototoki import config

_SPEC = importlib.util.spec_from_file_location("smoke_run_all", config.REPO_ROOT / "scripts" / "smoke" / "run_all.py")
run_all = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(run_all)

STEPS = {
    "cjk": 'import sys\nprint("日本語の行 ✓ 中文进度 100%|██████|")\n',
    "bad": 'import sys\nprint("boom")\nsys.exit(3)\n',
    "hang": 'import time\nprint("waiting", flush=True)\ntime.sleep(60)\n',
}


class InterruptOn(io.StringIO):
    """模拟 Ctrl+C：转发到某项子进程输出时抛 KeyboardInterrupt。"""

    def __init__(self, marker: str) -> None:
        super().__init__()
        self.marker = marker

    def write(self, text: str) -> int:
        if text.startswith(self.marker):
            raise KeyboardInterrupt
        return super().write(text)


class SmokeRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        here = self.root / "steps"
        here.mkdir()
        for name, source in STEPS.items():
            (here / f"{name}.py").write_text(source, encoding="utf-8")
        self.lock = self.root / ".local" / "gpu.lock"
        self.processes: list[subprocess.Popen] = []
        real_popen = subprocess.Popen

        def popen(*args: object, **kwargs: object) -> subprocess.Popen:
            process = real_popen(*args, **kwargs)
            self.processes.append(process)
            return process

        for patch in (mock.patch.object(run_all, "HERE", here), mock.patch.object(run_all, "REPO", self.root),
                      mock.patch.object(run_all, "GPU_LOCK", self.lock),
                      mock.patch.object(run_all, "SMOKES", tuple(STEPS)),
                      mock.patch.object(run_all.subprocess, "Popen", popen)):
            patch.start()
            self.addCleanup(patch.stop)

    def run_main(self, stdout: io.TextIOBase, *names: str) -> int:
        with mock.patch.object(sys, "argv", ["run_all.py", *names]), mock.patch.object(sys, "stdout", stdout):
            return run_all.main()

    def test_step_lines_and_cjk_child_output_are_forwarded(self) -> None:
        stdout = io.StringIO()
        self.assertEqual(self.run_main(stdout, "cjk", "bad"), 1)
        text = stdout.getvalue()
        lines = text.splitlines()
        self.assertRegex(lines[0], r"^=== \[1/2\] cjk start \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("[cjk] 日本語の行", text)
        self.assertRegex(text, r"=== \[1/2\] cjk PASS in \d+\.\ds, log .*cjk\.log")
        self.assertRegex(text, r"=== \[2/2\] bad FAIL \(exit 3\) in \d+\.\ds, log .*bad\.log")
        self.assertRegex(text, r"cjk: PASS in \d+\.\ds\nbad: FAIL \(exit 3\) in \d+\.\ds\nresults: ")
        log = next((self.root / ".local" / "smoke").glob("*/cjk.log"))
        self.assertIn("日本語の行", log.read_text(encoding="utf-8"))
        self.assertFalse(self.lock.exists())

    def test_interrupt_reaps_the_running_child_before_the_lock_is_removed(self) -> None:
        stdout = InterruptOn("[hang] ")
        unlinked_while_alive: list[bool] = []
        real_unlink = Path.unlink

        def unlink(path: Path, missing_ok: bool = False) -> None:
            unlinked_while_alive.append(any(process.poll() is None for process in self.processes))
            real_unlink(path, missing_ok=missing_ok)

        with mock.patch.object(Path, "unlink", unlink), self.assertRaises(KeyboardInterrupt):
            self.run_main(stdout, "cjk", "hang", "bad")
        self.assertEqual(len(self.processes), 2)  # bad 没有启动
        self.assertTrue(all(process.poll() is not None for process in self.processes))
        self.assertEqual(unlinked_while_alive, [False])
        self.assertFalse(self.lock.exists())
        summary = stdout.getvalue()
        self.assertRegex(summary, r"cjk: PASS in \d+\.\ds\nhang: not completed\nbad: not completed\nresults: ")


if __name__ == "__main__":
    unittest.main()
