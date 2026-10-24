"""Regenerate the small resource-only installer UI DLL (no runtime code)."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def build():
    tools = ROOT / "开发缓存/工具链/llvm/usr/lib/llvm-18/bin"
    compiler = shutil.which("llvm-rc") or str(tools / "llvm-rc")
    linker = shutil.which("lld-link") or str(tools / "lld-link")
    env = dict(os.environ)
    libs = ROOT / "开发缓存/工具链/llvm/usr/lib/x86_64-linux-gnu"
    if libs.is_dir():
        env["LD_LIBRARY_PATH"] = str(libs) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    output = ROOT / "src-tauri/icons/installer-ui.dll"
    with tempfile.TemporaryDirectory(prefix="afterglow-ui-") as folder:
        resource = Path(folder) / "installer-ui.res"
        subprocess.run([compiler, "/fo", str(resource), str(ROOT / "scripts/installer-ui.rc")],
                       check=True, env=env)
        subprocess.run([linker, "/dll", "/noentry", "/machine:x86", "/timestamp:0",
                        "/out:" + str(output), "/implib:" + str(Path(folder) / "ui.lib"), str(resource)], check=True, env=env)
    print(output)


if __name__ == "__main__":
    build()
