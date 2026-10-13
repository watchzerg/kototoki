#!/usr/bin/env python3
"""持有主机级文件锁运行一条命令；只依赖标准库。

full 测试会占用端口、桌面焦点等主机资源，不同 worktree 甚至不同项目同时运行会互相干扰。
`gate-full` 与 `test-full` 都经本脚本串行：锁文件默认在 ~/.cache/gate-full.lock，可用环境变量
GATE_LOCK_FILE 覆盖。使用 flock，锁只由本进程持有：命令作为子进程运行且不继承锁的文件描述符，
命令退出后本进程随即退出并释放锁，命令留下的后台进程不会继续占锁；锁文件记录的 pid 即本进程。
收到 SIGINT/SIGTERM 时转发给命令并等待其退出（终端 Ctrl-C 已同时送达命令时不重复转发）。

用法：with_lock.py [--timeout 秒] 命令 [参数...]
等待时每 30 秒打印持有者；超时退出码 75（稍后重试），不视为命令失败；等待中被中断退出码 130。
命令被信号终止时退出码为 128 + 信号编号，其余情况返回命令自身的退出码。
"""

import argparse
import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

EXIT_TEMPFAIL = 75
EXIT_INTERRUPTED = 130
REPORT_EVERY = 30


def main() -> int:
    parser = argparse.ArgumentParser(description="持有主机级文件锁运行命令。")
    parser.add_argument("--timeout", type=float, help="等待秒数，默认一直等待")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="要运行的命令")
    args = parser.parse_args()
    if not args.command:
        parser.error("缺少要运行的命令")

    lock_path = Path(os.environ.get("GATE_LOCK_FILE") or Path.home() / ".cache/gate-full.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # os.open 默认不可继承（O_CLOEXEC）；子进程与其后台后代都拿不到锁。
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)

    try:
        if not acquire(fd, lock_path, args.timeout):
            return EXIT_TEMPFAIL
    except KeyboardInterrupt:
        print(f"已中断：未取得主机锁 {lock_path}，命令未运行。", file=sys.stderr)
        return EXIT_INTERRUPTED

    return run(args.command, fd)


def acquire(fd: int, lock_path: Path, timeout: float | None) -> bool:
    """非阻塞轮询取锁；超时返回 False。等待期间每 30 秒打印一次持有者。"""
    started = time.monotonic()
    last_report = started - REPORT_EVERY
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            pass
        waited = time.monotonic() - started
        if timeout is not None and waited >= timeout:
            print(
                f"错误：等待 {lock_path} 超过 {timeout:g} 秒；{holder(fd)}。稍后重试。",
                file=sys.stderr,
            )
            return False
        if time.monotonic() - last_report >= REPORT_EVERY:
            print(f"等待主机锁 {lock_path}（已等 {waited:.0f} 秒）；{holder(fd)}", flush=True)
            last_report = time.monotonic()
        time.sleep(1)


def run(command: list[str], fd: int) -> int:
    """登记持有者后以子进程运行命令并转发 SIGINT/SIGTERM。

    返回命令退出码，被信号终止时为 128 + 信号编号。先装信号处理再登记，
    外部看到持有者信息后发来的信号一定会转发给命令。
    """
    child: subprocess.Popen[bytes] | None = None
    pending: list[int] = []

    def forward(signum: int, _frame: object) -> None:
        if signum == signal.SIGINT and terminal_delivers_sigint():
            return
        if child is None:
            pending.append(signum)
        else:
            child.send_signal(signum)

    signal.signal(signal.SIGINT, forward)
    signal.signal(signal.SIGTERM, forward)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    info = f"pid={os.getpid()} time={stamp} cwd={os.getcwd()} cmd={' '.join(command)}\n"
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, info.encode())
    try:
        child = subprocess.Popen(command, close_fds=True)
    except OSError as exc:
        print(f"错误：无法执行 {command[0]}：{exc}", file=sys.stderr)
        return 1
    for signum in pending:
        child.send_signal(signum)
    code = child.wait()
    return 128 - code if code < 0 else code


def terminal_delivers_sigint() -> bool:
    """本进程在终端前台进程组时，Ctrl-C 已直接送达同组的命令，不必重复转发。"""
    try:
        return os.tcgetpgrp(sys.stdin.fileno()) == os.getpgrp()
    except OSError, ValueError, AttributeError:
        return False


def holder(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    info = os.read(fd, 4096).decode(errors="replace").strip()
    return f"持有者 {info}" if info else "持有者未知"


if __name__ == "__main__":
    sys.exit(main())
