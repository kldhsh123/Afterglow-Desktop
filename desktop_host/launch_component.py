"""Load a versioned upstream component without modifying its source tree."""
import os
import runpy
import sys
from pathlib import Path

component = Path(sys.argv[1]).resolve()
arguments = sys.argv[2:]
for name in ("app", "deps"):
    path = component / name
    if path.is_dir():
        sys.path.insert(0, str(path))
if os.name == "nt":
    dll_handles = [os.add_dll_directory(str(folder)) for folder in (component / "deps").glob("*.libs")]
if arguments and arguments[0] == "-m":
    module = arguments[1]
    sys.argv = [module, *arguments[2:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)
else:
    entry = component / "app" / "main.py"
    sys.argv = [str(entry), *arguments]
    runpy.run_path(str(entry), run_name="__main__")
