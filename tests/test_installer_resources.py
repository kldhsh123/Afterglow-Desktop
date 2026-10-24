"""Regression check for the emitted NSIS PE, without executing any EXE."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.check_installer_resources import verify_installer_ui

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_NSIS = ROOT / '开发缓存/工具链/nsis/usr'
MAKENSIS = shutil.which('makensis') or str(BUNDLED_NSIS / 'bin/makensis')


class InstallerConfirmationTests(unittest.TestCase):
    def test_version_comparison_orders_stable_after_internal_and_detects_repairs(self):
        pages = (ROOT / 'scripts/installer-pages.nsh').read_text()
        compare = pages.split('Function ReadInstalledVersion\n', 1)[1].split('FunctionEnd', 1)[0]
        self.assertIn('StrCpy $0 "$InstalledVersion.65536"', compare)
        self.assertIn('StrCpy $1 "${VERSION}.65536"', compare)
        self.assertIn('${VersionCompare} "$1" "$0" $VersionOrder', compare)
        self.assertIn('StrCpy $UpgradeMode "repair"', compare)

    def test_language_switch_reopens_confirmation_and_keeps_selected_directory(self):
        pages = (ROOT / 'scripts/installer-pages.nsh').read_text()
        switch = pages.split('Function ChangeLanguage\n', 1)[1].split('FunctionEnd', 1)[0]
        init = pages.split('Function .onInit\n', 1)[1].split('FunctionEnd', 1)[0]
        self.assertIn('${GetOptions} $CMDLINE "/LANG=" $0', init)
        self.assertIn('${NSD_GetText} $PathControl $INSTDIR', switch)
        self.assertIn('Exec \'$LanguageCommand /D=$INSTDIR\'', switch)
        self.assertIn('/LANG=$RequestedLanguage', switch)
        self.assertNotIn('StrCpy $LANGUAGE', switch)
        commands = '\n'.join(line.split(';', 1)[0] for line in switch.splitlines())
        self.assertNotIn(' /S', commands)
        self.assertNotIn('Call SetupLeave', switch)
        self.assertNotIn('StrCpy $InstallConfirmed 1', switch)

    def test_uninstaller_offers_both_languages_and_retains_explicit_delete_choice(self):
        pages = (ROOT / 'scripts/installer-pages.nsh').read_text()
        engine = (ROOT / 'scripts/windows-installer.nsi').read_text()
        page = pages.split('Function un.ConfirmPage\n', 1)[1].split('FunctionEnd', 1)[0]
        switch = pages.split('Function un.ChangeLanguage\n', 1)[1].split('FunctionEnd', 1)[0]
        init = engine.split('Function un.onInit\n', 1)[1].split('FunctionEnd', 1)[0]
        self.assertIn('${NSD_OnClick} $ChineseControl un.ChangeLanguage', page)
        self.assertIn('${NSD_OnClick} $EnglishControl un.ChangeLanguage', page)
        self.assertIn('${NSD_GetState} $DeleteDataControl $1', switch)
        self.assertIn('"$INSTDIR\\Uninstall.exe" /LANG=$RequestedLanguage /DELETE_SELECTED=$1', switch)
        self.assertNotIn(' /S', switch)
        self.assertIn('StrCpy $DeleteUserData 0', init)
        self.assertLess(init.index('IfSilent un_language_done'), init.index('"/DELETE_SELECTED="'))
        self.assertIn('"/LANG="', init)
        self.assertNotIn('Call un.CheckAppClosed', init)

    def test_normal_install_and_update_cannot_skip_confirmation(self):
        pages = (ROOT / 'scripts/installer-pages.nsh').read_text()
        engine = (ROOT / 'scripts/windows-installer.nsi').read_text()
        setup = pages.split('Function SetupPage\n', 1)[1].split('FunctionEnd', 1)[0]
        leave = pages.split('Function SetupLeave\n', 1)[1].split('FunctionEnd', 1)[0]
        finish = pages.split('Function FinishPage\n', 1)[1].split('FunctionEnd', 1)[0]
        self.assertNotIn('Abort', setup)
        self.assertNotIn('AutoUpgrade', pages)
        self.assertIn('Call DirectoryLeave\n  StrCpy $InstallConfirmed 1', leave)
        self.assertIn('${NSD_Uncheck} $LaunchControl', finish)
        for section in ('WebView2', 'Afterglow'):
            self.assertIn('Section "' + section + '"\n  Call RequireInstallConfirmation', engine)
        gate = engine.split('Function RequireInstallConfirmation\n', 1)[1].split('FunctionEnd', 1)[0]
        self.assertIn('StrCmp $InstallConfirmed 1 confirmed', gate)
        self.assertIn('Abort', gate)


@unittest.skipUnless(Path(MAKENSIS).is_file(), 'NSIS compiler is not installed')
class InstallerResourceTests(unittest.TestCase):
    def test_compiled_dialog_check_catches_silent_resource_stripping(self):
        env = dict(os.environ)
        if MAKENSIS == str(BUNDLED_NSIS / 'bin/makensis'):
            env['NSISDIR'] = str(BUNDLED_NSIS / 'share/nsis')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for mode in ('normal', 'silent'):
                with self.subTest(mode=mode):
                    artifact = folder / (mode + '-do-not-run.exe')
                    script = folder / (mode + '.nsi')
                    script.write_text(f'''Unicode true
Name "Afterglow compile-only regression fixture"
OutFile "{artifact}"
SilentInstall {mode}
SilentUnInstall {mode}
Page instfiles
Section
SectionEnd
''')
                    result = subprocess.run([MAKENSIS, '-V2', str(script)], env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    if mode == 'silent':
                        with self.assertRaisesRegex(ValueError, 'missing dialog resources 105, 106'):
                            verify_installer_ui(artifact)
                    else:
                        verify_installer_ui(artifact)


if __name__ == '__main__':
    unittest.main()
