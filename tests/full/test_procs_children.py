"""子进程随编排器退出（`procs.contained`，ADR-0034「子进程与长任务」）的真实路径：起一个真的父进程，
由它按产品的方式启动 `sleep`，再强杀父进程，核对子进程随之消失、且不在父进程的进程组里。"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest

from kototoki import config, procs

PARENT = """
import subprocess, sys
from kototoki.procs import contained
child = subprocess.Popen(contained(["sleep", "60"]), stdin=subprocess.DEVNULL, start_new_session=True)
print(child.pid, flush=True)
child.wait()
"""


class ContainedChildTests(unittest.TestCase):
    def wait_gone(self, pid: int, timeout_s: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:  # 子进程的父进程已死，由 init 回收；/proc 条目消失或变成僵尸都算结束
                with open(f"/proc/{pid}/stat", encoding="ascii") as stream:
                    if stream.read().rsplit(")", 1)[1].split()[0] == "Z":
                        return True
            except FileNotFoundError:
                return True
            time.sleep(0.05)
        return False

    def test_child_dies_with_killed_parent_and_has_its_own_process_group(self) -> None:
        parent = subprocess.Popen([sys.executable, "-c", PARENT], stdout=subprocess.PIPE, text=True,
                                  cwd=config.REPO_ROOT)
        self.addCleanup(parent.wait)
        child = int(parent.stdout.readline())
        parent.stdout.close()
        try:
            self.assertTrue(procs.pid_alive(child))
            # 等 setpriv 设好 PDEATHSIG 并 exec 成 sleep，再杀父进程；否则测的是启动窗口里的竞态
            deadline = time.monotonic() + 5.0
            while open(f"/proc/{child}/comm", encoding="ascii").read().strip() != "sleep":
                self.assertLess(time.monotonic(), deadline, "setpriv did not exec the child")
                time.sleep(0.01)
            self.assertNotEqual(os.getpgid(child), os.getpgid(parent.pid))  # 终端 Ctrl+C 不直达子进程
            parent.send_signal(signal.SIGKILL)
            self.assertTrue(self.wait_gone(child), "child outlived its SIGKILLed parent")
        finally:
            if procs.pid_alive(child):
                os.kill(child, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
