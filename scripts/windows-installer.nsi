Unicode true
XPStyle on
ManifestDPIAware true
RequestExecutionLevel user
; Load the small wizard assets without first expanding the complete payload
; into a temporary solid archive. File extraction then happens on the styled
; progress page, after confirmation, instead of a long pre-wizard loading step.
SetCompressor lzma
; Keep the visible UI in the compiled EXE. NSIS strips its dialog resources
; when this is "silent", even if .onInit later calls SetSilent normal.
; Explicit /S remains supported by NSIS's own command-line parser.
SilentInstall normal
SilentUnInstall normal
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "build-config.nsh"
Name "Afterglow ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\Afterglow"
SetFont "Segoe UI" 9
BrandingText "Afterglow Desktop"
Icon "${ICON}"
UninstallIcon "${ICON}"
VIProductVersion "${WINDOWS_VERSION}"
VIAddVersionKey /LANG=1033 "ProductName" "Afterglow Desktop"
VIAddVersionKey /LANG=1033 "FileDescription" "Afterglow Desktop ${VERSION} installer"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Afterglow contributors"
Var InstallId
Var ShortcutName
Var DeleteUserData
Var ResultPath
Var EngineState
Var EngineStage
Var EngineError
!include "${INSTALLER_PAGES}"

; Optional status output for explicit /RESULT automation. Ordinary launches use
; the visible website-styled wizard and require confirmation before installing.
; Write state last so readers do not treat an intermediate stage as success.
Function ReportEngineStatus
  ${If} $ResultPath != ""
    WriteINIStr "$ResultPath" "install" "stage" "$EngineStage"
    WriteINIStr "$ResultPath" "install" "error" "$EngineError"
    WriteINIStr "$ResultPath" "install" "state" "$EngineState"
  ${EndIf}
FunctionEnd

Function FailEngine
  StrCpy $EngineState "failed"
  Call ReportEngineStatus
  SetErrorLevel 2
FunctionEnd

Function DirectoryLeave
  Call ReadInstalledVersion
  ${If} $VersionOrder == 2
    StrCpy $EngineError "$(AlreadyNewer)"
    Call FailEngine
    MessageBox MB_ICONINFORMATION|MB_OK "$(AlreadyNewer)" /SD IDOK
    Abort
  ${EndIf}
  IfFileExists "$INSTDIR\.afterglow-portable" valid
  IfFileExists "$INSTDIR\Afterglow.exe" existing
  FindFirst $0 $1 "$INSTDIR\*"
  loop:
    StrCmp $1 "" empty
    StrCmp $1 "." next
    StrCmp $1 ".." next
    FindClose $0
    StrCpy $EngineError "$(InvalidFolder)"
    Call FailEngine
    MessageBox MB_ICONEXCLAMATION|MB_OK "$(InvalidFolder)" /SD IDOK
    Abort
  next:
    FindNext $0 $1
    Goto loop
  empty:
    FindClose $0
    Return
  existing:
    IfFileExists "$INSTDIR\.afterglow-portable" valid
    StrCpy $EngineError "$(InvalidFolder)"
    Call FailEngine
    MessageBox MB_ICONEXCLAMATION|MB_OK "$(InvalidFolder)" /SD IDOK
    Abort
  valid:
    Call CheckAppClosed
FunctionEnd

!macro CheckClosed PREFIX
Function ${PREFIX}CheckAppClosed
  IfFileExists "$INSTDIR\Afterglow.exe" 0 done
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\Afterglow.exe", i 0x40000000, i 0, p 0, i 3, i 0, p 0) p.r0'
  StrCmp $0 -1 locked
  System::Call 'kernel32::CloseHandle(p r0)'
  Goto done
  locked:
    !if "${PREFIX}" == ""
      StrCpy $EngineError "$(CloseApp)"
      Call FailEngine
    !endif
    MessageBox MB_ICONEXCLAMATION|MB_OK "$(CloseApp)" /SD IDOK
    Abort
  done:
FunctionEnd
!macroend
!insertmacro CheckClosed ""
!insertmacro CheckClosed "un."

Function RequireInstallConfirmation
  ; An ordinary launch must pass SetupLeave before any runtime installation,
  ; file replacement, registry write or shortcut creation can begin.
  IfSilent confirmed
  StrCmp $InstallConfirmed 1 confirmed
  SetErrorLevel 2
  Abort
  confirmed:
FunctionEnd

Section "WebView2"
  Call RequireInstallConfirmation
  Call DirectoryLeave
  StrCpy $EngineStage "runtime"
  Call ReportEngineStatus
  SetDetailsPrint none
  SetRegView 64
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  StrCmp $0 "" 0 webview_done
  ReadRegStr $0 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  StrCmp $0 "" 0 webview_done
  SetRegView 32
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  StrCmp $0 "" 0 webview_done
  ReadRegStr $0 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  StrCmp $0 "" 0 webview_done
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=MicrosoftEdgeWebview2Setup.exe "${WEBVIEW_BOOTSTRAPPER}"
  ExecWait '$\"$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe$\" /silent /install' $0
  StrCmp $0 0 webview_done
  StrCpy $EngineError "$(WebviewFailed)"
  Call FailEngine
  MessageBox MB_ICONEXCLAMATION|MB_OK "$(WebviewFailed)" /SD IDOK
  Abort
  webview_done:
  SetRegView 64
SectionEnd

Section "Afterglow"
  Call RequireInstallConfirmation
  Call DirectoryLeave
  StrCpy $EngineStage "files"
  Call ReportEngineStatus
  ReadINIStr $InstallId "$INSTDIR\installation.ini" "installation" "id"
  ReadINIStr $ShortcutName "$INSTDIR\installation.ini" "installation" "shortcut"
  ${If} $InstallId == ""
    System::Call 'ole32::CoCreateGuid(g .r0) i.r1'
    ${If} $1 != 0
      StrCpy $EngineError "$(InstallFailed)"
      Call FailEngine
      Abort
    ${EndIf}
    StrCpy $InstallId $0
  ${EndIf}
  ${If} $ShortcutName == ""
    StrCpy $ShortcutName "Afterglow"
    StrCpy $0 1
    shortcuts:
      IfFileExists "$SMPROGRAMS\$ShortcutName.lnk" shortcuts_taken
      IfFileExists "$DESKTOP\$ShortcutName.lnk" 0 shortcuts_done
    shortcuts_taken:
      IntOp $0 $0 + 1
      StrCpy $ShortcutName "Afterglow ($0)"
      Goto shortcuts
    shortcuts_done:
  ${EndIf}
  ClearErrors
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD}/*"
  ${If} ${Errors}
    StrCpy $EngineError "$(CopyFailed)"
    Call FailEngine
    Abort
  ${EndIf}
  StrCpy $EngineStage "registration"
  Call ReportEngineStatus
  ClearErrors
  WriteINIStr "$INSTDIR\installation.ini" "installation" "id" "$InstallId"
  WriteINIStr "$INSTDIR\installation.ini" "installation" "shortcut" "$ShortcutName"
  WriteINIStr "$INSTDIR\installation.ini" "installation" "version" "${VERSION}"
  WriteINIStr "$INSTDIR\installation.ini" "installation" "language" "$LANGUAGE"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\$ShortcutName.lnk" "$INSTDIR\Afterglow.exe"
  CreateShortcut "$DESKTOP\$ShortcutName.lnk" "$INSTDIR\Afterglow.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-$InstallId" "DisplayName" "$ShortcutName (${VERSION})"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-$InstallId" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-$InstallId" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-$InstallId" "DisplayIcon" "$INSTDIR\Afterglow.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-$InstallId" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-$InstallId" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-$InstallId" "NoRepair" 1
  ${If} ${Errors}
    StrCpy $EngineError "$(RegistrationFailed)"
    Call FailEngine
    Abort
  ${EndIf}
SectionEnd

Function un.onInit
  SetRegView 64
  ; Even silent removal preserves user data; deletion requires an explicit
  ; selection on the confirmation page of this installation's uninstaller.
  StrCpy $DeleteUserData 0
  StrCpy $LANGUAGE ${LANG_ENGLISH}
  System::Call 'kernel32::GetUserDefaultUILanguage() i.r0'
  IntOp $0 $0 & 0x3ff
  ${If} $0 == 4
    StrCpy $LANGUAGE ${LANG_SIMPCHINESE}
  ${EndIf}
  ReadINIStr $0 "$INSTDIR\installation.ini" "installation" "language"
  ${If} $0 == ${LANG_ENGLISH}
  ${OrIf} $0 == ${LANG_SIMPCHINESE}
    StrCpy $LANGUAGE $0
  ${EndIf}
  ${GetOptions} $CMDLINE "/LANG=" $0
  ${If} $0 == ${LANG_ENGLISH}
  ${OrIf} $0 == ${LANG_SIMPCHINESE}
    StrCpy $LANGUAGE $0
  ${EndIf}
  IfSilent un_language_done
  ${GetOptions} $CMDLINE "/DELETE_SELECTED=" $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $DeleteUserData 1
  ${EndIf}
  un_language_done:
  StrCpy $ImageLocale "zh"
  ${If} $LANGUAGE == ${LANG_ENGLISH}
    StrCpy $ImageLocale "en"
  ${EndIf}
FunctionEnd

Function .onInstSuccess
  ; Run once after installation even when "open Afterglow" is not selected.
  ; pythonw avoids a console flash; a slow or offline check cannot block setup.
  IfFileExists "$INSTDIR\python\pythonw.exe" 0 checks_done
  IfFileExists "$INSTDIR\desktop_host\post_install_check.py" 0 checks_done
  Exec '"$INSTDIR\python\pythonw.exe" -I "$INSTDIR\desktop_host\post_install_check.py" --install-dir "$INSTDIR"'
  checks_done:
  StrCpy $EngineStage "complete"
  StrCpy $EngineState "complete"
  StrCpy $EngineError ""
  Call ReportEngineStatus
  SetErrorLevel 0
FunctionEnd

Function .onInstFailed
  ${If} $EngineError == ""
    StrCpy $EngineError "$(InstallFailed)"
  ${EndIf}
  Call FailEngine
FunctionEnd

Function un.onUninstSuccess
  SetAutoClose true
FunctionEnd

Section "Uninstall"
  Call un.CheckAppClosed
  ReadINIStr $InstallId "$INSTDIR\installation.ini" "installation" "id"
  ReadINIStr $ShortcutName "$INSTDIR\installation.ini" "installation" "shortcut"
  ${If} $InstallId != ""
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowDesktop-$InstallId"
    ; Remove only this copy's opt-in startup entry, even when data is retained.
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AfterglowDesktop-$InstallId"
  ${EndIf}
  ${If} $ShortcutName != ""
    Delete "$SMPROGRAMS\$ShortcutName.lnk"
    Delete "$DESKTOP\$ShortcutName.lnk"
  ${EndIf}
  !include "uninstall-files.nsh"
  Delete "$INSTDIR\installation.ini"
  Delete "$INSTDIR\Uninstall.exe"
  ${If} $DeleteUserData == 1
    ; This directory belongs only to the copy being removed. Never delete the
    ; installation root recursively or touch a sibling installation's data.
    RMDir /r "$INSTDIR\AfterglowData"
    IfFileExists "$INSTDIR\AfterglowData\*" 0 data_removed
    MessageBox MB_ICONEXCLAMATION|MB_OK "$(DeleteDataFailed)" /SD IDOK
    Goto data_done
    data_removed:
    Delete "$INSTDIR\.afterglow-portable"
    data_done:
  ${EndIf}
  ; Retained data prevents this nonrecursive removal, as intended.
  RMDir "$INSTDIR"
SectionEnd
