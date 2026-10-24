param([Parameter(Mandatory=$true)][string]$Installer, [Parameter(Mandatory=$true)][string]$InstallDirectory)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AfterglowInstallerCheck {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
}
'@
function Save-InstallerScreenshot([IntPtr]$Handle, [string]$Name) {
  $rect = New-Object AfterglowInstallerCheck+RECT
  [AfterglowInstallerCheck]::GetWindowRect($Handle, [ref]$rect) | Out-Null
  $bitmap = New-Object System.Drawing.Bitmap ($rect.Right-$rect.Left), ($rect.Bottom-$rect.Top)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $dc = $graphics.GetHdc()
  try { [AfterglowInstallerCheck]::PrintWindow($Handle, $dc, 2) | Out-Null } finally { $graphics.ReleaseHdc($dc) }
  $bitmap.Save((Join-Path (Split-Path $PSScriptRoot -Parent) ('test-results\' + $Name + '.png')), [System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose(); $bitmap.Dispose()
}
$variables = @('AFTERGLOW_UPDATE_INSTALLER', 'AFTERGLOW_UPDATE_DIRECTORY', 'AFTERGLOW_UPDATE_SHA256', 'AFTERGLOW_UPDATE_PARENT', 'AFTERGLOW_UPDATE_LOCALE')
$saved = @{}
foreach ($name in $variables) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
$helper = $null
$parent = $null
$installerProcesses = @()
try {
  $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $parent = Start-Process -FilePath $powershell -ArgumentList '-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 2"' -WindowStyle Hidden -PassThru
  $env:AFTERGLOW_UPDATE_INSTALLER = $Installer
  $env:AFTERGLOW_UPDATE_DIRECTORY = $InstallDirectory
  $env:AFTERGLOW_UPDATE_SHA256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
  $env:AFTERGLOW_UPDATE_PARENT = [string]$parent.Id
  $env:AFTERGLOW_UPDATE_LOCALE = 'zh-CN'
  $script = [IO.File]::ReadAllText((Join-Path (Split-Path $PSScriptRoot -Parent) 'desktop_host\apply_update.ps1'))
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
  $helper = Start-Process -FilePath $powershell -ArgumentList ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand ' + $encoded) -WindowStyle Hidden -PassThru
  $deadline = [DateTime]::UtcNow.AddMinutes(5)
  $observedInstaller = $false
  $captured = @{}
  while (-not $helper.HasExited) {
    if ([DateTime]::UtcNow -gt $deadline) { throw 'Update handoff timed out' }
    $children = @(Get-CimInstance Win32_Process -Filter ('ParentProcessId = ' + $helper.Id) | Where-Object { $_.ExecutablePath -eq $Installer })
    foreach ($child in $children) {
      if (-not $parent.HasExited) { throw 'The installer opened before the parent application closed' }
      $observedInstaller = $true
      if ($installerProcesses -notcontains $child.ProcessId) { $installerProcesses += $child.ProcessId }
      $process = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
      if (-not $process -or $process.MainWindowHandle -eq [IntPtr]::Zero) { continue }
      try {
        $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
        $names = @($window.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition) | ForEach-Object { $_.Current.Name })
        foreach ($stage in @(@('installer-setup', '让 Afterglow 在这里安家'), @('installer-progress', '正在准备 Afterglow'), @('installer-finish', 'Afterglow 已准备好'), @('installer-updated', 'Afterglow 已更新'))) {
          if (-not $captured.ContainsKey($stage[0]) -and $names -contains $stage[1]) {
            Save-InstallerScreenshot $process.MainWindowHandle $stage[0]
            $captured[$stage[0]] = $true
          }
        }
        # Do not launch the application from the finish page during this test.
        $checks = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::CheckBox)))
        foreach ($checkbox in $checks) {
          if ($checkbox.Current.IsEnabled -and -not $checkbox.Current.IsOffscreen) {
            $toggle = $null
            if ($checkbox.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$toggle)) {
              if ($toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On) { $toggle.Toggle() }
            } else {
              $handle = [IntPtr]$checkbox.Current.NativeWindowHandle
              if ($handle -eq [IntPtr]::Zero) { throw 'Installer checkbox has no supported interaction' }
              # NSIS native controls may not expose UI Automation patterns.
              if ([AfterglowInstallerCheck]::SendMessage($handle, 0xF0, [IntPtr]::Zero, [IntPtr]::Zero).ToInt64() -eq 1) {
                [AfterglowInstallerCheck]::SendMessage($handle, 0xF5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
              }
            }
          }
        }
        $next = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, '1')))
        if ($next -and $next.Current.IsEnabled -and -not $next.Current.IsOffscreen) {
          $invoke = $null
          if ($next.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invoke)) {
            $invoke.Invoke()
          } else {
            $handle = [IntPtr]$next.Current.NativeWindowHandle
            if ($handle -eq [IntPtr]::Zero -or -not [AfterglowInstallerCheck]::PostMessage($handle, 0xF5, [IntPtr]::Zero, [IntPtr]::Zero)) { throw 'Could not advance installer wizard' }
          }
        }
      } catch [System.Windows.Automation.ElementNotAvailableException] { }
    }
    Start-Sleep -Milliseconds 400
    $helper.Refresh()
  }
  if ($helper.ExitCode -ne 0) { throw ('Update helper failed: ' + $helper.ExitCode) }
  if (-not $observedInstaller) { throw 'The verified update installer was not opened' }
  if (-not (Test-Path -LiteralPath (Join-Path $InstallDirectory 'Afterglow.exe'))) { throw 'Update removed the application' }
  $applicationPath = Join-Path $InstallDirectory 'Afterglow.exe'
  foreach ($running in @(Get-CimInstance Win32_Process -Filter "Name = 'Afterglow.exe'" | Where-Object { $_.ExecutablePath -eq $applicationPath })) {
    $application = Get-Process -Id $running.ProcessId -ErrorAction SilentlyContinue
    if ($application -and (-not $application.CloseMainWindow() -or -not $application.WaitForExit(15000))) { throw 'The updated test application did not close' }
  }
  @{ ok=$true; verifiedHandoff=$true; waitedForExit=$true; installerWizard=$true } | ConvertTo-Json -Compress
} finally {
  foreach ($name in $variables) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
  foreach ($id in $installerProcesses) { Stop-Process -Id $id -ErrorAction SilentlyContinue }
  if ($helper -and -not $helper.HasExited) { $helper.Kill(); $helper.WaitForExit() }
  if ($parent -and -not $parent.HasExited) { $parent.Kill(); $parent.WaitForExit() }
  # Only this test installation may be closed if the wizard launched it.
  $applicationPath = Join-Path $InstallDirectory 'Afterglow.exe'
  foreach ($running in @(Get-CimInstance Win32_Process -Filter "Name = 'Afterglow.exe'" | Where-Object { $_.ExecutablePath -eq $applicationPath })) {
    $application = Get-Process -Id $running.ProcessId -ErrorAction SilentlyContinue
    if ($application) {
      $application.CloseMainWindow() | Out-Null
      if (-not $application.WaitForExit(15000)) { $application.Kill(); $application.WaitForExit() }
    }
  }
}
