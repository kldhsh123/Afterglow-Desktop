"""Bootstrap built-in extensions even under Windows' isolated embeddable Python."""
import asyncio
import json
import os
from pathlib import Path
import runpy
import sys


def main():
    # Credentials travel over the inherited private pipe, never command arguments.
    config = json.loads(sys.stdin.readline())
    extension = config["extension"]
    if extension not in {"qq", "weixin"}:
        raise ValueError("Unknown extension")
    root = Path(__file__).resolve().parent
    source = root / "builtin" / extension
    deps = Path(config["component"]) / "deps"
    sys.path[:0] = [str(root), str(source), str(deps)]
    dll_handles = []
    if os.name == "nt":
        for folder in deps.glob("*.libs"):
            dll_handles.append(os.add_dll_directory(str(folder)))
    # Do not inherit developer model credentials or unrelated adapter settings.
    for key in list(os.environ):
        if key.startswith(("AFTERGLOW_", "QQ_BOT_", "WEIXIN_")) or key.endswith(("_API_KEY", "_API_URL", "_MODEL")):
            os.environ.pop(key)
    os.environ.update(config["environment"])
    sys.argv = [str(source / "main.py"), *( ["--login"] if config.get("login") else [])]
    module = runpy.run_path(str(source / "main.py"), run_name="desktop_builtin")
    try:
        return asyncio.run(module["main"]())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
