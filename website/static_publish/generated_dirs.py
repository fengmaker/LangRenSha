"""Rename generated publishing directories despite brief Windows file locks."""

from pathlib import Path
import time


def rename_generated_directory(source: Path, destination: Path) -> None:
    # Windows also reports access denied when a child has an open handle
    # without delete sharing, for example while a scanner checks new output.
    for attempt in range(7):
        try:
            source.rename(destination)
            return
        except OSError as error:
            if getattr(error, "winerror", None) not in {5, 32}:
                raise
            if attempt == 6:
                raise RuntimeError(
                    f"Windows 持续阻止目录替换，重试 6 次后仍失败：{source} -> {destination}。"
                    f"请释放相关目录占用并检查访问权限后重试。原始错误：{error}"
                ) from error
            if attempt == 0:
                print(f"Windows 暂时拒绝目录替换，等待后重试：{source} -> {destination}", flush=True)
            time.sleep(0.1 * 2 ** attempt)
