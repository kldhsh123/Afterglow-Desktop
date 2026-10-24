param([Parameter(Mandatory=$true)][string]$Application)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AfterglowWindowCheck {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int command);
}
'@
$root = Split-Path $PSScriptRoot -Parent
$testRoot = Join-Path $root ('开发缓存\构建\native-app-check-' + [guid]::NewGuid().ToString('N'))
$oldData = $env:AFTERGLOW_DATA_DIR
$process = $null
try {
  $env:AFTERGLOW_DATA_DIR = $testRoot
  $process = Start-Process -FilePath $Application -PassThru
  $deadline = [DateTime]::UtcNow.AddSeconds(50)
  $names = @()
  $handle = [IntPtr]::Zero
  while ([DateTime]::UtcNow -lt $deadline) {
    $process.Refresh()
    if ($process.HasExited) { throw ('Application exited: ' + $process.ExitCode) }
    $handle = $process.MainWindowHandle
    if ($handle -ne [IntPtr]::Zero) {
      $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
      $children = $element.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
      $names = @($children | ForEach-Object { $_.Current.Name } | Where-Object { $_ } | Select-Object -Unique)
      if (($names -contains '简体中文') -and (($names -contains 'English') -or ($names -contains 'English en-US')) -and (Test-Path -LiteralPath (Join-Path $testRoot '.desktop.lock'))) { break }
    }
    Start-Sleep -Milliseconds 500
  }
  if (-not ($names -contains '简体中文')) { throw ('Language screen is missing: ' + ($names -join ', ')) }
  $pythonChildren = @(Get-CimInstance Win32_Process -Filter ('ParentProcessId = ' + $process.Id) | Where-Object { $_.Name -eq 'python.exe' } | ForEach-Object { $_.ProcessId })
  if (-not $pythonChildren.Count) { throw 'The bundled Python host did not start' }
  if (-not (Test-Path -LiteralPath (Join-Path $testRoot '.desktop.lock'))) { throw 'The desktop manager did not create its isolated workspace' }
  $rect = New-Object AfterglowWindowCheck+RECT
  [AfterglowWindowCheck]::GetWindowRect($handle, [ref]$rect) | Out-Null
  $bitmap = New-Object System.Drawing.Bitmap ($rect.Right-$rect.Left), ($rect.Bottom-$rect.Top)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $dc = $graphics.GetHdc()
  try { [AfterglowWindowCheck]::PrintWindow($handle, $dc, 2) | Out-Null } finally { $graphics.ReleaseHdc($dc) }
  $bitmap.Save((Join-Path $root 'test-results\native-language-screen.png'), [System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose(); $bitmap.Dispose()
  function Invoke-WindowControl([string]$Name, [switch]$Prefix) {
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
    $until = [DateTime]::UtcNow.AddSeconds(10)
    do {
      $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
      $button = $element.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition) | Where-Object { if ($Prefix) { $_.Current.Name.StartsWith($Name) } else { $_.Current.Name -eq $Name } } | Select-Object -First 1
      if ($button) { break }
      if ([DateTime]::UtcNow -gt $until) { throw ('Window control is missing: ' + $Name) }
      Start-Sleep -Milliseconds 100
    } while ($true)
    $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  }
  function Wait-WindowState($Check, [string]$Message) {
    $until = [DateTime]::UtcNow.AddSeconds(10)
    while (-not (& $Check)) {
      if ([DateTime]::UtcNow -gt $until) { throw $Message }
      Start-Sleep -Milliseconds 100
    }
  }
  $english = $names -contains 'Maximize'
  Invoke-WindowControl $(if ($english) { 'Maximize' } else { '最大化' })
  Wait-WindowState { [AfterglowWindowCheck]::IsZoomed($handle) } 'Maximize control failed'
  Invoke-WindowControl $(if ($english) { 'Restore' } else { '还原' })
  Wait-WindowState { -not [AfterglowWindowCheck]::IsZoomed($handle) } 'Restore control failed'
  Invoke-WindowControl $(if ($english) { 'Minimize' } else { '最小化' })
  Wait-WindowState { [AfterglowWindowCheck]::IsIconic($handle) } 'Minimize control failed'
  [AfterglowWindowCheck]::ShowWindow($handle, 9) | Out-Null
  Wait-WindowState { -not [AfterglowWindowCheck]::IsIconic($handle) } 'Restoring the minimized app failed'
  Invoke-WindowControl $(if ($english) { 'Close' } else { '关闭' })
  Invoke-WindowControl $(if ($english) { 'Minimize to tray' } else { '最小化到托盘' }) -Prefix
  Wait-WindowState { -not [AfterglowWindowCheck]::IsWindowVisible($handle) } 'Close choice did not hide the window in the tray'
  $process.Refresh()
  if ($process.HasExited) { throw 'Minimizing from the close dialog exited the application' }
  foreach ($child in $pythonChildren) { if (-not (Get-Process -Id $child -ErrorAction SilentlyContinue)) { throw 'Minimizing stopped the Python host' } }
  [AfterglowWindowCheck]::ShowWindow($handle, 9) | Out-Null
  [AfterglowWindowCheck]::PostMessage($handle, 0x10, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
  Invoke-WindowControl $(if ($english) { 'Exit application' } else { '退出程序' }) -Prefix
  if (-not $process.WaitForExit(25000)) { throw 'Application did not close cleanly' }
  foreach ($child in $pythonChildren) { if (Get-Process -Id $child -ErrorAction SilentlyContinue) { throw 'Bundled Python process remained after closing the app' } }
  @{ ok=$true; languageScreen=$true; nativeControls=$true; bundledHost=$true; cleanShutdown=$true; version=(Get-Item -LiteralPath $Application).VersionInfo.ProductVersion } | ConvertTo-Json -Compress
} finally {
  $env:AFTERGLOW_DATA_DIR = $oldData
  if ($process -and -not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
  if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
