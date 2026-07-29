import os
import sys
import atexit
from pathlib import Path

PID_FILE = Path("./data/fisherquant.pid")


def _pid_alive(pid: int) -> bool:
    """判断进程是否存活（Windows 用 tasklist）。"""
    if not pid:
        return False
    try:
        import subprocess

        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        return str(pid) in out
    except Exception:
        return False


def _already_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        return False
    return _pid_alive(pid)


if _already_running():
    sys.stderr.write(
        f"另一实例已在运行（PID 见 {PID_FILE}）。为避免双进程并发写同一 DuckDB 文件"
        "导致数据库损坏、缓存被清空，本进程已退出。请先停止旧实例再启动。\n"
    )
    sys.exit(1)

PID_FILE.write_text(str(os.getpid()))


def _cleanup_pid() -> None:
    try:
        if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
            PID_FILE.unlink()
    except Exception:
        pass


atexit.register(_cleanup_pid)

from fisher.dash_app.app import app

if __name__ == "__main__":
    # use_reloader=False：Werkzeug 热重载会起父+子两个进程，双双打开 DuckDB
    # 独占锁必然冲突；曾导致抢锁失败方误判「库损坏」而清库（symbol_dict 与
    # 缓存全丢、搜索无结果）。日常运行必须单进程持锁。
    app.run(host="0.0.0.0", port=8050, debug=False)
