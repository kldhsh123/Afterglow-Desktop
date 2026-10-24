$ErrorActionPreference = 'Stop'
$installer = $env:AFTERGLOW_UPDATE_INSTALLER
$installDir = $env:AFTERGLOW_UPDATE_DIRECTORY
$expectedHash = $env:AFTERGLOW_UPDATE_SHA256
$parentProcessId = [int]$env:AFTERGLOW_UPDATE_PARENT
try {
  if (-not (Test-Path -LiteralPath $installer -PathType Leaf) -or $expectedHash -notmatch '^[a-f0-9]{64}$') { throw 'The staged update is missing or invalid' }
  if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedHash) { throw 'The staged update checksum changed' }
  $parentProcess = Get-Process -Id $parentProcessId -ErrorAction SilentlyContinue
  if ($parentProcess -and -not $parentProcess.WaitForExit(90000)) { throw 'Afterglow did not close in time' }
  if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedHash) { throw 'The staged update checksum changed' }
  $language = if ($env:AFTERGLOW_UPDATE_LOCALE -eq 'en-US') { '1033' } else { '2052' }
  $process = Start-Process -FilePath $installer -ArgumentList ('/LANG=' + $language + ' /D=' + $installDir) -PassThru
  $process.WaitForExit()
  if ($process.ExitCode -ne 0) { throw ('Installer exited with code ' + $process.ExitCode) }
} catch {
  $message = $_.Exception.Message
  try { Set-Content -LiteralPath (Join-Path (Split-Path $installer -Parent) 'last-update-error.txt') -Value $message -Encoding UTF8 } catch {}
  Add-Type -AssemblyName System.Windows.Forms
  $notice = if ($env:AFTERGLOW_UPDATE_LOCALE -eq 'en-US') { 'The update did not finish. Open Afterglow to try again. Your conversations and settings are preserved.' } else { '更新未完成。请重新打开 Afterglow 后重试，聊天记录和配置会保留。' }
  [System.Windows.Forms.MessageBox]::Show($notice, 'Afterglow') | Out-Null
  exit 1
}
