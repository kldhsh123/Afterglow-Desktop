"""Check cross-build orchestration without compiling or downloading an SDK."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsCrossBuildTests(unittest.TestCase):
    def run_build(self, arguments=(), rewrite_during_build=False):
        with tempfile.TemporaryDirectory(prefix="afterglow-build-test-") as folder:
            root = Path(folder)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(ROOT / "scripts/build_windows_cross.sh", scripts)
            tools = root / "开发缓存/工具链"
            tools.mkdir(parents=True)
            log = root / "commands.log"
            for name in ("node", "npm", "python3", "cargo-xwin", "clang-cl", "lld-link", "llvm-rc"):
                command = tools / name
                command.write_text(
                    '#!/usr/bin/env bash\n'
                    'printf "%s|%s|%s|%s\\n" "${0##*/}" "${XWIN_ARCH:-}" '
                    '"${XWIN_VARIANT:-}" "$*" >> "$BUILD_TEST_LOG"\n'
                    'if [[ "${0##*/}" == node && "${1:-}" == --input-type=module ]]; then echo 0.1.0; fi\n',
                    encoding="utf-8",
                )
                command.chmod(0o755)
            cargo = tools / "cargo-xwin"
            with cargo.open("a", encoding="utf-8") as stream:
                stream.write(
                    'if [[ "$*" == "xwin build "* && "${BUILD_TEST_REWRITE:-}" == 1 ]]; then\n'
                    '  printf "REPLACED_SCRIPT_MUST_NOT_EXECUTE\\n%.0s" {1..1000} > "$BUILD_TEST_SCRIPT"\n'
                    'fi\n'
                )
            executable = root / "cache/windows-msvc-target/x86_64-pc-windows-msvc/release/afterglow-desktop.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"test executable")
            env = dict(os.environ, HOME=str(root), BUILD_TEST_LOG=str(log),
                       AFTERGLOW_BUILD_CACHE=str(root / "cache"),
                       BUILD_TEST_SCRIPT=str(scripts / "build_windows_cross.sh"),
                       BUILD_TEST_REWRITE="1" if rewrite_during_build else "0")
            env.pop("XWIN_ARCH", None)
            env.pop("XWIN_VARIANT", None)
            env.pop("AFTERGLOW_CARGO_HOME", None)
            subprocess.run(["bash", str(scripts / "build_windows_cross.sh"), *arguments],
                           env=env, check=True, capture_output=True, text=True, timeout=10)
            return [line.split("|", 3) for line in log.read_text().splitlines()]

    def test_only_prepares_windows_x64_desktop_dependencies(self):
        calls = [call for call in self.run_build() if call[0] == "cargo-xwin"]
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(call[1:3], ["x86_64", "desktop"])

    def test_prepares_sdk_before_building_frontend(self):
        calls = self.run_build()
        sdk = next((i for i, call in enumerate(calls)
                    if call[0] == "cargo-xwin" and call[3] == "xwin cache xwin"), None)
        frontend = next(i for i, call in enumerate(calls) if call[0] == "npm")
        self.assertIsNotNone(sdk, "SDK preparation must have its own visible build phase")
        self.assertLess(sdk, frontend)

    def test_running_build_uses_loaded_script_when_file_changes(self):
        calls = self.run_build(rewrite_during_build=True)
        self.assertEqual(len([call for call in calls if call[0] == "python3"]), 2)

    def test_package_only_skips_sdk_and_compilation(self):
        calls = self.run_build(arguments=("--package-only",))
        self.assertFalse(any(call[0] in ("cargo-xwin", "npm") for call in calls))
        self.assertEqual(len([call for call in calls if call[0] == "python3"]), 2)

    def test_installer_uses_the_stable_portable_folder_name(self):
        calls = self.run_build(arguments=("--package-only",))
        installer = next(call for call in calls if call[0] == "python3" and 'package_installer.py' in call[3])
        self.assertIn('Afterglow-0.1.0-windows-x64-portable', installer[3])


if __name__ == "__main__":
    unittest.main()
