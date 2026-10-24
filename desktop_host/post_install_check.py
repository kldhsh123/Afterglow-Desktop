"""Background check after installation, independent of the launch checkbox.

The installer starts this with bundled pythonw.exe. No network access or model
credentials are needed to finish installing. Results are cached for the app.
"""
import argparse
from pathlib import Path
import sys

# Embeddable Python and -I omit the script directory from module search paths.
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from .repository_updates import RepositoryChecks
except ImportError:
    from repository_updates import RepositoryChecks


def check_after_install(directory):
    root = Path(directory).resolve() / "AfterglowData"
    root.mkdir(parents=True, exist_ok=True)
    checks = RepositoryChecks(root)
    checks._check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path, required=True)
    args = parser.parse_args()
    check_after_install(args.install_dir)
