"""Inspect PE dialogs without loading or executing an installer.

NSIS may successfully compile an EXE after removing its visible UI resources.
Check the emitted artifact, not just whether makensis returned exit status zero.
"""
from pathlib import Path
import struct


def dialog_ids(path: Path) -> set[int]:
    with path.open('rb') as stream:
        def read(offset, size):
            stream.seek(offset)
            data = stream.read(size)
            if len(data) != size:
                raise ValueError('Truncated installer PE resources')
            return data

        if read(0, 2) != b'MZ':
            raise ValueError('Installer is not a Windows PE file')
        pe = struct.unpack('<I', read(0x3c, 4))[0]
        if read(pe, 4) != b'PE\0\0':
            raise ValueError('Invalid installer PE header')
        section_count = struct.unpack('<H', read(pe + 6, 2))[0]
        optional_size = struct.unpack('<H', read(pe + 20, 2))[0]
        optional = pe + 24
        magic = struct.unpack('<H', read(optional, 2))[0]
        if magic not in (0x10b, 0x20b) or section_count > 96:
            raise ValueError('Unsupported installer PE format')
        directories = optional + (96 if magic == 0x10b else 112)
        resource_rva, resource_size = struct.unpack('<II', read(directories + 16, 8))
        if not resource_rva or not resource_size:
            return set()
        root = None
        for index in range(section_count):
            section = optional + optional_size + index * 40
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack('<IIII', read(section + 8, 16))
            if virtual_address <= resource_rva < virtual_address + min(virtual_size, raw_size):
                root = raw_offset + resource_rva - virtual_address
                break
        if root is None:
            raise ValueError('Installer resource section is missing')

        def entries(relative):
            if relative + 16 > resource_size:
                raise ValueError('Invalid installer resource directory')
            named, ids = struct.unpack('<HH', read(root + relative + 12, 4))
            count = named + ids
            if count > 8192 or relative + 16 + count * 8 > resource_size:
                raise ValueError('Invalid installer resource entries')
            return [struct.unpack('<II', read(root + relative + 16 + index * 8, 8)) for index in range(count)]

        for kind, directory in entries(0):
            if kind == 5 and directory & 0x80000000:  # RT_DIALOG
                return {name for name, child in entries(directory & 0x7fffffff)
                        if not name & 0x80000000 and child & 0x80000000}
        return set()


def verify_installer_ui(path: Path) -> None:
    missing = {105, 106} - dialog_ids(path)
    if missing:
        raise ValueError('Installer has no usable visible UI (missing dialog resources '
                         + ', '.join(map(str, sorted(missing)))
                         + '). Keep SilentInstall/SilentUnInstall normal and rebuild; do not run this artifact.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer', type=Path)
    args = parser.parse_args()
    verify_installer_ui(args.installer)
    print('Installer window and progress resources: OK (no installer execution)')
