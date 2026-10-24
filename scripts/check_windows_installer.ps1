param([Parameter(Mandatory=$true)][string]$Installer, [switch]$CheckApp, [switch]$CheckUpdate)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$root = Split-Path $PSScriptRoot -Parent
$testRoot = Join-Path $root ('开发缓存\构建\installer-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$copies = @((Join-Path $testRoot 'copy one'), (Join-Path $testRoot '副本二'))
$ids = @()
$shortcutPaths = @()
$desktopFolder = [Environment]::GetFolderPath('DesktopDirectory')
$shortcutShell = New-Object -ComObject WScript.Shell
function Wait-InstallerProcess($Process, [string]$Label) {
  $deadline = [DateTime]::UtcNow.AddMinutes(5)
  while (-not $Process.WaitForExit(5000)) {
    if ([DateTime]::UtcNow -ge $deadline) { $Process.Kill(); $Process.WaitForExit(); throw ($Label + ' timed out') }
    Write-Output ($Label + ' is still running')
  }
  if ($Process.ExitCode -ne 0) { throw ($Label + ' failed: ' + $Process.ExitCode) }
}
try {
  foreach ($copy in $copies) {
    Write-Output ('Installing into ' + $copy)
    $process = Start-Process -FilePath $Installer -ArgumentList ("/S /D=" + $copy) -PassThru
    Wait-InstallerProcess $process 'Install'
    if (-not (Test-Path -LiteralPath (Join-Path $copy 'Afterglow.exe'))) { throw 'Selected installation path was not used' }
    if (-not (Test-Path -LiteralPath (Join-Path $copy '.afterglow-portable'))) { throw 'Isolation marker is missing' }
    $line = Get-Content -LiteralPath (Join-Path $copy 'installation.ini') | Where-Object { $_ -like 'id=*' }
    $id = $line.Substring(3)
    if (-not $id) { throw 'Installation registry identity is missing' }
    $ids += $id
    $shortcutLine = Get-Content -LiteralPath (Join-Path $copy 'installation.ini') | Where-Object { $_ -like 'shortcut=*' }
    $shortcutName = $shortcutLine.Substring(9)
    $shortcutPath = Join-Path $desktopFolder ($shortcutName + '.lnk')
    if (-not (Test-Path -LiteralPath $shortcutPath)) { throw 'Desktop shortcut is missing' }
    if ($shortcutShell.CreateShortcut($shortcutPath).TargetPath -ne (Join-Path $copy 'Afterglow.exe')) { throw 'Desktop shortcut points to another installation' }
    $shortcutPaths += $shortcutPath
    if (-not (Test-Path -LiteralPath ('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-' + $id))) { throw 'Uninstall registration is missing' }
    $data = Join-Path $copy 'AfterglowData'
    New-Item -ItemType Directory -Path $data | Out-Null
    Set-Content -LiteralPath (Join-Path $data 'preserve-me.txt') -Value 'installer test data'
  }
  if ($shortcutPaths[0] -eq $shortcutPaths[1]) { throw 'Separate installations share a desktop shortcut' }
  if ($ids[0] -eq $ids[1]) { throw 'Separate installations share an identity' }
  if ($CheckApp) { & (Join-Path $PSScriptRoot 'check_windows_app.ps1') -Application (Join-Path $copies[0] 'Afterglow.exe') }
  if ($CheckUpdate) {
    & (Join-Path $PSScriptRoot 'check_windows_update.ps1') -Installer $Installer -InstallDirectory $copies[0]
  } else {
    $upgrade = Start-Process -FilePath $Installer -ArgumentList ("/S /D=" + $copies[0]) -PassThru
    Wait-InstallerProcess $upgrade 'In-place upgrade'
  }
  $line = Get-Content -LiteralPath (Join-Path $copies[0] 'installation.ini') | Where-Object { $_ -like 'id=*' }
  if ($line.Substring(3) -ne $ids[0]) { throw 'In-place upgrade changed installation identity' }
  if (-not (Test-Path -LiteralPath (Join-Path $copies[0] 'AfterglowData\preserve-me.txt'))) { throw 'In-place upgrade removed user data' }

  for ($index=0; $index -lt $copies.Count; $index++) {
    $copy = $copies[$index]
    $uninstaller = Join-Path $copy 'Uninstall.exe'
    $process = Start-Process -FilePath $uninstaller -ArgumentList ("/S _?=" + $copy) -PassThru
    Wait-InstallerProcess $process 'Uninstall'
    if (Test-Path -LiteralPath (Join-Path $copy 'Afterglow.exe')) { throw 'Program was not uninstalled' }
    if (Test-Path -LiteralPath $shortcutPaths[$index]) { throw 'Desktop shortcut was not removed' }
    if (-not (Test-Path -LiteralPath (Join-Path $copy 'AfterglowData\preserve-me.txt'))) { throw 'Uninstall removed user data' }
    if (Test-Path -LiteralPath ('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-' + $ids[$index])) { throw 'Uninstall registration was not removed' }
  }
  @{ ok=$true; selectedDirectories=2; independentInstallations=$true; desktopShortcuts=$true; dataPreserved=$true } | ConvertTo-Json -Compress
} finally {
  # All files here were created by this test in its unique cache directory.
  foreach ($copy in $copies) {
    $uninstaller = Join-Path $copy 'Uninstall.exe'
    if ((Test-Path -LiteralPath (Join-Path $copy 'Afterglow.exe')) -and (Test-Path -LiteralPath $uninstaller)) {
      try {
        $cleanup = Start-Process -FilePath $uninstaller -ArgumentList ("/S _?=" + $copy) -PassThru
        Wait-InstallerProcess $cleanup 'Cleanup'
      } catch { Write-Warning ('Test cleanup failed: ' + $_) }
    }
  }
  try { Remove-Item -LiteralPath $testRoot -Recurse -Force } catch { Write-Warning ('Test directory retained: ' + $testRoot + ': ' + $_) }
}
