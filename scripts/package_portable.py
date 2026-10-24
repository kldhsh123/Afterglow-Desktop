"""Assemble a Windows portable folder from a release EXE and prepared resources.

Build the EXE with Tauri CLI, or Cargo --release --features custom-protocol.
The generated folder contains no development data, accounts, or credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_host.versioning import desktop_version


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def windows_x64(path):
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            return False
        stream.seek(0x3c)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        return stream.read(6) == b"PE\0\0\x64\x86"


def assemble(executable, output):
    if output.exists():
        raise ValueError(f"Destination already exists: {output}")
    if not windows_x64(executable):
        raise ValueError("Expected a Windows x64 PE executable")
    resources = ROOT / "src-tauri/resources"
    runtime = resources / "python"
    if not (runtime / "python.exe").is_file() or not (runtime / "afterglow-runtime.json").is_file():
        raise ValueError("Prepare and verify the portable Python resources first")
    catalog = json.loads((resources / "runtime-catalog.json").read_text(encoding="utf-8"))
    entries = catalog.get("components", [])
    if not any(entry.get("id") == "core" and entry.get("bundled") for entry in entries):
        raise ValueError("A verified bundled core is required")
    for entry in entries:
        if entry.get("bundled"):
            package = (resources / entry["bundled"]).resolve()
            if resources.resolve() not in package.parents or digest(package) != entry["sha256"]:
                raise ValueError("Bundled package checksum mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="portable-", dir=output.parent) as temporary:
        stage = Path(temporary) / output.name
        stage.mkdir()
        shutil.copy2(executable, stage / "Afterglow.exe")
        ignored = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".gitkeep")
        shutil.copytree(ROOT / "desktop_host", stage / "desktop_host", ignore=ignored)
        shutil.copytree(ROOT / "locales", stage / "locales", ignore=ignored)
        shutil.copytree(runtime, stage / "python", ignore=ignored)
        # Make the official Python runtime's redistributable VC DLLs available
        # to the Rust/WebView loader too, even on a clean Windows machine.
        for name in ("vcruntime140.dll", "vcruntime140_1.dll"):
            source = runtime / name
            if source.is_file():
                shutil.copy2(source, stage / name)
        shutil.copytree(resources / "packages", stage / "packages", ignore=ignored)
        shutil.copy2(resources / "runtime-catalog.json", stage / "catalog.json")
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", stage / "THIRD_PARTY_NOTICES.md")
        shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
        metadata = json.loads((ROOT / "version.json").read_text())
        version = desktop_version(metadata)
        shutil.copy2(ROOT / "version.json", stage / "version.json")
        (stage / ".afterglow-portable").touch()
        (stage / "START-HERE.txt").write_text(
            "Afterglow Desktop\n\n"
            "运行 Afterglow.exe。首次启动先选择语言，再完成配置。\n"
            "请保留整个文件夹；Python 和 Afterglow 运行组件均已随包提供。\n"
            "每份副本的数据保存在各自的 AfterglowData 文件夹。\n"
            "需要 Microsoft Edge WebView2 Runtime；Windows 11 通常已自带。\n\n"
            "Run Afterglow.exe and choose your language. Keep this entire folder.\n"
            "Python and Afterglow runtime components are included; no separate Python install is needed.\n"
            "Each portable copy stores its own data in AfterglowData.\n"
            "Microsoft Edge WebView2 Runtime is required.\n", encoding="utf-8")
        files = {str(path.relative_to(stage)).replace("\\", "/"): digest(path)
                 for path in sorted(stage.rglob("*")) if path.is_file()}
        (stage / "portable-manifest.json").write_text(json.dumps({
            "format": 1, "platform": "windows-x86_64", "version": version, "files": files,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    metadata = json.loads((ROOT / "version.json").read_text())
    version = desktop_version(metadata)
    parser.add_argument("--output", type=Path, default=ROOT / f"artifacts/Afterglow-{version}-windows-x64-portable")
    args = parser.parse_args()
    print(assemble(args.exe.resolve(), args.output.resolve()))


if __name__ == "__main__":
    main()
