"""Run the local website and API together; stop both cleanly with Ctrl+C."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "website" / "web"


def node_binary() -> str:
    configured = os.environ.get("NODE_BINARY")
    if configured and Path(configured).is_file():
        return configured
    installed = shutil.which("node")
    if installed:
        return installed
    candidates = sorted((ROOT / ".tools" / "node").glob("node-v*-win-x64/node.exe"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return str(candidates[0])
    raise RuntimeError("需要 Node.js 24 LTS；安装后加入 PATH，或设置 NODE_BINARY。")


def port_available(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true", help="使用已构建的 Next.js 生产版本")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--api-port", type=int, default=8000)
    args = parser.parse_args()
    for port in (args.port, args.api_port):
        if not 1 <= port <= 65535 or not port_available(port):
            raise RuntimeError(f"端口 {port} 无效或已被占用；请使用 --port / --api-port 指定其它端口。")
    node = node_binary()
    next_cli = WEB / "node_modules" / "next" / "dist" / "bin" / "next"
    if not next_cli.is_file():
        raise RuntimeError("前端依赖尚未安装；请在 website/web 目录执行 npm ci。")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "NEXT_TELEMETRY_DISABLED": "1",
           "API_BASE_URL": f"http://127.0.0.1:{args.api_port}"}
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    children: list[subprocess.Popen] = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "website.api.app:app",
                                "--host", "127.0.0.1", "--port", str(args.api_port)],
                               cwd=ROOT, env=env, creationflags=flags)
        children.append(api)
        for _ in range(120):
            if api.poll() is not None:
                raise RuntimeError("API 启动失败，请查看上方错误。")
            try:
                with urlopen(env["API_BASE_URL"] + "/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError("API 未就绪，请检查 PostgreSQL 和发布数据。")
        if args.production:
            standalone = WEB / ".next" / "standalone"
            if not (standalone / "server.js").is_file():
                raise RuntimeError("请先在 website/web 执行 npm run build。")
            shutil.copytree(WEB / ".next" / "static", standalone / ".next" / "static", dirs_exist_ok=True)
            env.update(PORT=str(args.port), HOSTNAME="127.0.0.1")
            frontend_command = [node, str(standalone / "server.js")]
            frontend_cwd = standalone
        else:
            frontend_command = [node, str(next_cli), "dev", "--hostname", "127.0.0.1", "--port", str(args.port)]
            frontend_cwd = WEB
        frontend = subprocess.Popen(frontend_command, cwd=frontend_cwd, env=env, creationflags=flags)
        children.append(frontend)
        print(f"\n大师赛档案：http://127.0.0.1:{args.port}\n按 Ctrl+C 同时停止网站与 API。\n", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(.5)
        return next((child.returncode for child in children if child.returncode), 1)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
