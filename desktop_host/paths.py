"""Installation identity and a process lock for independent desktop copies."""
import hashlib
import os
from pathlib import Path
import sys

try:
    from .i18n import tr
except ImportError:
    from i18n import tr


def installation_key(directory: Path, windows=None) -> str:
    value = str(directory.resolve()).replace("\\", "/").rstrip("/")
    if windows is True or (windows is None and os.name == "nt"):
        value = value.casefold()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def data_directory(install_dir: Path, app_data: Path, override=None) -> Path:
    if override is not None:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError(tr("host.absolute_data_directory"))
        return path.resolve()
    if (install_dir / ".afterglow-portable").is_file():
        return install_dir.resolve() / "AfterglowData"
    return app_data.resolve() / "installations" / installation_key(install_dir)


class DataDirectoryLock:
    """Keep two managers from writing the same installation's files."""
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.stream = (directory / ".desktop.lock").open("a+b")
        try:
            self.stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                # Windows locking allows a byte range beyond the current EOF.
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError(tr("host.data_directory_in_use")) from None

    def close(self):
        if not self.stream.closed:
            self.stream.close()
