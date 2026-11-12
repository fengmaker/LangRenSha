"""Prepare final JSON and preview the local website without a database or API."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "website/web"
sys.path.insert(0, str(ROOT))


def node_binary() -> str:
    configured = os.environ.get("NODE_BINARY")
    if configured and Path(configured).is_file():
        return configured
    installed = shutil.which("node")
    if installed:
        return installed
    candidates = sorted((ROOT / ".tools/node").glob("node-v*-win-x64/node.exe"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return str(candidates[0])
    raise RuntimeError("未找到 Node.js；请加入 PATH 或设置 NODE_BINARY。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1..65535 之间")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    node = node_binary()
    next_cli = WEB / "node_modules/next/dist/bin/next"
    if not next_cli.is_file():
        raise RuntimeError("请先在 website/web 执行 npm ci。")
    from website.static_publish.export_static import export_direct_snapshot
    result = export_direct_snapshot(ROOT, WEB / "public/data")
    print(f"已准备本地静态数据：{result['release_id']}", flush=True)
    env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1", "NEXT_PUBLIC_BASE_PATH": ""}
    # Development serves real IDs through the existing client routes. Only the
    # explicit publishing build enables Next's output:export shell generation.
    env.pop("NEXT_PUBLIC_SITE_MODE", None)
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    frontend = subprocess.Popen([node, str(next_cli), "dev", "--hostname", "127.0.0.1",
                                 "--port", str(args.port)], cwd=WEB, env=env, creationflags=flags)
    def interrupt(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    print(f"大师赛档案：http://127.0.0.1:{args.port}；Ctrl+C 停止。", flush=True)
    try:
        return frontend.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if frontend.poll() is None:
            frontend.terminate()
            try:
                frontend.wait(timeout=8)
            except subprocess.TimeoutExpired:
                frontend.kill()
                frontend.wait()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
