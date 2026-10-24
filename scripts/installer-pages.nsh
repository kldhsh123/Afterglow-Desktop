; Original Afterglow screens using the website's exact palette and typography.
; Native controls keep their keyboard/accessibility/command behavior. The small
; local skin DLL changes painting only; no third-party skin engine is involved.
!include "nsDialogs.nsh"
!include "WordFunc.nsh"
!include "StrFunc.nsh"
${StrRep}
${StrStr}
!insertmacro VersionCompare
LoadLanguageFile "${NSISDIR}/Contrib/Language files/SimpChinese.nlf"
LoadLanguageFile "${NSISDIR}/Contrib/Language files/English.nlf"
!include "${INSTALLER_LOCALES}/zh-CN.nsh"
!include "${INSTALLER_LOCALES}/en-US.nsh"
ChangeUI IDD_INST "${INSTALLER_UI}"
ChangeUI IDD_INSTFILES "${INSTALLER_UI}"
Page custom SetupPage SetupLeave
Page instfiles "" ProgressShow
Page custom FinishPage FinishLeave
UninstPage custom un.ConfirmPage un.ConfirmLeave
UninstPage instfiles "" un.ProgressShow
ShowInstDetails nevershow
ShowUninstDetails nevershow

Var Dialog
Var BrandFont
Var HeadingFont
Var BodyFont
Var SmallFont
Var ImageLocale
Var LogoImage
Var SkinModule
Var BuildControl
Var TitleControl
Var DescriptionControl
Var PathLabel
Var PathControl
Var PathNote
Var BrowseControl
Var ChineseControl
Var EnglishControl
Var InstanceControl
Var InstanceLabel
Var LaunchControl
Var DeleteDataControl
Var ExistingCount
Var InstalledVersion
Var VersionOrder
Var UpgradeMode
Var ExplicitDirectory
Var InstallConfirmed
Var RequestedLanguage
Var LanguageCommand

!macro Skin HANDLE ROLE
  System::Call '"$PLUGINSDIR\appearance\installer-skin.dll"::Attach(p ${HANDLE}, i ${ROLE})'
!macroend
!macro RefreshSkin
  System::Call '"$PLUGINSDIR\appearance\installer-skin.dll"::Refresh(p $HWNDPARENT)'
!macroend
!macro SetCaption HANDLE TEXT FONT COLOR
  ${NSD_SetText} ${HANDLE} "${TEXT}"
  SendMessage ${HANDLE} ${WM_SETFONT} ${FONT} 1
  SetCtlColors ${HANDLE} "${COLOR}" "F5F1E4"
  ${If} "${COLOR}" == "7A8AA0"
    !insertmacro Skin ${HANDLE} 9
  ${ElseIf} "${COLOR}" == "8B5A2B"
    !insertmacro Skin ${HANDLE} 10
  ${EndIf}
!macroend
!macro Footer PRIMARY
  GetDlgItem $0 $HWNDPARENT 3
  ShowWindow $0 ${SW_HIDE}
  GetDlgItem $0 $HWNDPARENT 1
  ${NSD_SetText} $0 "${PRIMARY}"
  SendMessage $0 ${WM_SETFONT} $BodyFont 1
  !insertmacro Skin $0 2
  GetDlgItem $0 $HWNDPARENT 2
  ${NSD_SetText} $0 "$(CancelLabel)"
  SendMessage $0 ${WM_SETFONT} $BodyFont 1
  !insertmacro Skin $0 3
!macroend

!macro Appearance PREFIX
Function ${PREFIX}.onGUIInit
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\appearance"
  File /oname=sidebar.bmp "${INSTALLER_SIDEBAR}"
  File /oname=installer-skin.dll "${INSTALLER_SKIN}"
  System::Call 'kernel32::LoadLibraryW(w "$PLUGINSDIR\appearance\installer-skin.dll") p.s'
  Pop $SkinModule
  CreateFont $BrandFont "Georgia" 26 400
  ${If} $LANGUAGE == ${LANG_SIMPCHINESE}
    CreateFont $HeadingFont "宋体" 21 400
    CreateFont $BodyFont "Microsoft YaHei UI" 10 400
    CreateFont $SmallFont "Microsoft YaHei UI" 9 400
  ${Else}
    CreateFont $HeadingFont "Georgia" 21 400
    CreateFont $BodyFont "Segoe UI" 10 400
    CreateFont $SmallFont "Segoe UI" 9 400
  ${EndIf}
  SetCtlColors $HWNDPARENT "1A2F4B" "F5F1E4"
  !insertmacro Skin $HWNDPARENT 11
  ; On older Windows these optional titlebar attributes simply do nothing.
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 35, *i 0xE4F1F5, i 4)'
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 36, *i 0x4B2F1A, i 4)'
  System::Call 'dwmapi::DwmSetWindowAttribute(p $HWNDPARENT, i 33, *i 2, i 4)'
  GetDlgItem $0 $HWNDPARENT 1028
  ShowWindow $0 ${SW_HIDE}
FunctionEnd
Function ${PREFIX}.onGUIEnd
  ; Subclasses must be removed before unloading their code from the process.
  System::Call '"$PLUGINSDIR\appearance\installer-skin.dll"::Detach(p $HWNDPARENT)'
  System::Call 'kernel32::FreeLibrary(p $SkinModule)'
  System::Call 'gdi32::DeleteObject(p $BrandFont)'
  System::Call 'gdi32::DeleteObject(p $HeadingFont)'
  System::Call 'gdi32::DeleteObject(p $BodyFont)'
  System::Call 'gdi32::DeleteObject(p $SmallFont)'
FunctionEnd
!macroend
!insertmacro Appearance ""
!insertmacro Appearance "un"

!macro PageBrand
  SetCtlColors $Dialog "1A2F4B" "F5F1E4"
  !insertmacro Skin $Dialog 1
  ; Restore the original split layout: brand artwork on the left, actions and
  ; fields on the right. The bitmap contains no functional or localized copy.
  ${NSD_CreateBitmap} 0u 0u 168u 312u ""
  Pop $0
  ${NSD_SetStretchedImage} $0 "$PLUGINSDIR\appearance\sidebar.bmp" $LogoImage
  ${NSD_CreateLabel} 204u 26u 165u 20u "$(ReleaseVersion)"
  Pop $BuildControl
  !insertmacro SetCaption $BuildControl "$(ReleaseVersion)" $SmallFont "8B5A2B"
!macroend

Function SetImageLocale
  StrCpy $ImageLocale "zh"
  ${If} $LANGUAGE == ${LANG_ENGLISH}
    StrCpy $ImageLocale "en"
  ${EndIf}
FunctionEnd

Function .onInit
  SetRegView 64
  StrCpy $InstallConfirmed 0
  StrCpy $EngineState "working"
  StrCpy $EngineStage "preparing"
  StrCpy $EngineError ""
  ${GetOptions} $CMDLINE "/RESULT=" $ResultPath
  ${If} $ResultPath != ""
    ; Keep optional status output readable by Windows INI API clients.
    FileOpen $0 "$ResultPath" w
    FileWriteUTF16LE /BOM $0 "[install]$\r$\n"
    FileClose $0
    Call ReportEngineStatus
  ${EndIf}
  ; The engine owns /S. Keep the compiled UI available for ordinary launches.
  ; Raw GetCommandLineW preserves /D=, which NSIS removes from $CMDLINE.
  System::Call 'kernel32::GetCommandLineW() w.r0'
  ${StrStr} $ExplicitDirectory $0 "/D="
  StrCpy $LANGUAGE ${LANG_ENGLISH}
  System::Call 'kernel32::GetUserDefaultUILanguage() i.r0'
  IntOp $0 $0 & 0x3ff
  ${If} $0 == 4
    StrCpy $LANGUAGE ${LANG_SIMPCHINESE}
  ${EndIf}
  ${GetOptions} $CMDLINE "/LANG=" $0
  ${If} $0 == ${LANG_ENGLISH}
  ${OrIf} $0 == ${LANG_SIMPCHINESE}
    StrCpy $LANGUAGE $0
  ${EndIf}
  Call SetImageLocale
  ${IfNot} ${RunningX64}
    StrCpy $EngineError "$(Need64Bit)"
    Call FailEngine
    MessageBox MB_ICONSTOP|MB_OK "$(Need64Bit)" /SD IDOK
    Abort
  ${EndIf}
  InitPluginsDir
  StrCpy $ExistingCount 0
  StrCpy $0 0
  discover:
    EnumRegKey $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall" $0
    StrCmp $1 "" discovered
    IntOp $0 $0 + 1
    StrCpy $2 $1 17
    StrCmp $2 "AfterglowDesktop-" 0 discover
    ReadRegStr $3 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$1" "InstallLocation"
    IfFileExists "$3\.afterglow-portable" 0 discover
    IfFileExists "$3\Afterglow.exe" 0 discover
    IntOp $ExistingCount $ExistingCount + 1
    WriteINIStr "$PLUGINSDIR\copies.ini" "copies" "$ExistingCount" "$3"
    Goto discover
  discovered:
  ; /D always wins, including updater handoff and independent installations.
  ${If} $ExplicitDirectory == ""
    ${If} $ExistingCount == 1
      ReadINIStr $INSTDIR "$PLUGINSDIR\copies.ini" "copies" "1"
    ${ElseIf} $ExistingCount > 1
      Return
    ${EndIf}
  ${EndIf}
  Call ReadInstalledVersion
FunctionEnd

Function ReadInstalledVersion
  StrCpy $InstalledVersion ""
  StrCpy $VersionOrder ""
  StrCpy $UpgradeMode "install"
  IfFileExists "$INSTDIR\.afterglow-portable" 0 version_done
  ReadINIStr $InstalledVersion "$INSTDIR\installation.ini" "installation" "version"
  ${If} $InstalledVersion == ""
    StrCpy $0 0
    find_version:
      EnumRegKey $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall" $0
      StrCmp $1 "" version_found
      IntOp $0 $0 + 1
      ReadRegStr $2 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$1" "InstallLocation"
      StrCmp $2 $INSTDIR 0 find_version
      ReadRegStr $InstalledVersion HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$1" "DisplayVersion"
    version_found:
  ${EndIf}
  ${If} $InstalledVersion != ""
    ${StrRep} $0 $InstalledVersion "-internal." "."
    ; Stable releases sort after every internal build of the same base version.
    ; 65536 is a comparison sentinel only, never a Windows file-version field.
    ${If} $0 == $InstalledVersion
      StrCpy $0 "$InstalledVersion.65536"
    ${EndIf}
    ${StrRep} $1 "${VERSION}" "-internal." "."
    ${If} $1 == "${VERSION}"
      StrCpy $1 "${VERSION}.65536"
    ${EndIf}
    ${VersionCompare} "$1" "$0" $VersionOrder
    StrCpy $UpgradeMode "update"
    ${If} $VersionOrder == 0
      StrCpy $UpgradeMode "repair"
    ${EndIf}
  ${EndIf}
  version_done:
FunctionEnd

Function SetupPage
  ; Always show the target and action, even when a newer setup detects an old
  ; installation. Only the engine's explicit /S option may bypass the wizard.
  nsDialogs::Create 1018
  Pop $Dialog
  !insertmacro PageBrand
  ${NSD_CreateRadioButton} 380u 24u 72u 24u "简体中文"
  Pop $ChineseControl
  SendMessage $ChineseControl ${WM_SETFONT} $SmallFont 1
  !insertmacro Skin $ChineseControl 4
  ${NSD_OnClick} $ChineseControl ChangeLanguage
  ${NSD_CreateRadioButton} 458u 24u 68u 24u "English"
  Pop $EnglishControl
  SendMessage $EnglishControl ${WM_SETFONT} $SmallFont 1
  !insertmacro Skin $EnglishControl 4
  ${NSD_OnClick} $EnglishControl ChangeLanguage
  ${If} $ExistingCount > 1
    ${NSD_CreateLabel} 204u 65u 322u 32u ""
    Pop $TitleControl
    ${NSD_CreateLabel} 204u 106u 322u 32u ""
    Pop $DescriptionControl
    ${NSD_CreateLabel} 204u 147u 322u 13u "$(ExistingLabel)"
    Pop $InstanceLabel
    !insertmacro SetCaption $InstanceLabel "$(ExistingLabel)" $SmallFont "7A8AA0"
    ${NSD_CreateListBox} 204u 166u 322u 48u ""
    Pop $InstanceControl
    ; Preserve registry enumeration order so row index identifies the copy.
    System::Call 'user32::GetWindowLongW(p $InstanceControl, i -16) i.r0'
    IntOp $0 $0 & 0xFFFFFFFD
    System::Call 'user32::SetWindowLongW(p $InstanceControl, i -16, i r0)'
    SendMessage $InstanceControl ${WM_SETFONT} $SmallFont 1
    !insertmacro Skin $InstanceControl 6
    StrCpy $0 1
    StrCpy $2 $ExistingCount
    copies:
      IntCmp $0 $ExistingCount 0 0 copies_done
      ReadINIStr $1 "$PLUGINSDIR\copies.ini" "copies" "$0"
      ${NSD_LB_AddString} $InstanceControl "$1"
      ${If} $1 == $INSTDIR
        IntOp $2 $0 - 1
      ${EndIf}
      IntOp $0 $0 + 1
      Goto copies
    copies_done:
    ${NSD_LB_AddString} $InstanceControl "$(NewCopy)"
    SendMessage $InstanceControl ${LB_SETCURSEL} $2 0
    ${NSD_OnChange} $InstanceControl ChooseInstance
    ${NSD_CreateLabel} 204u 222u 322u 13u ""
    Pop $PathLabel
    ${NSD_CreateDirRequest} 204u 240u 238u 25u "$INSTDIR"
    Pop $PathControl
    ${NSD_CreateButton} 452u 240u 74u 25u "$(BrowseLabel)"
    Pop $BrowseControl
    ${NSD_CreateLabel} 204u 274u 322u 34u ""
    Pop $PathNote
  ${Else}
    ${NSD_CreateLabel} 204u 82u 322u 40u ""
    Pop $TitleControl
    ${NSD_CreateLabel} 204u 138u 322u 44u ""
    Pop $DescriptionControl
    ${NSD_CreateLabel} 204u 200u 322u 13u ""
    Pop $PathLabel
    ${NSD_CreateDirRequest} 204u 220u 238u 26u "$INSTDIR"
    Pop $PathControl
    ${NSD_CreateButton} 452u 220u 74u 26u "$(BrowseLabel)"
    Pop $BrowseControl
    ${NSD_CreateLabel} 204u 261u 322u 42u ""
    Pop $PathNote
  ${EndIf}
  SendMessage $PathControl ${WM_SETFONT} $BodyFont 1
  !insertmacro Skin $PathControl 5
  ${NSD_OnChange} $PathControl PathChanged
  SendMessage $BrowseControl ${WM_SETFONT} $BodyFont 1
  !insertmacro Skin $BrowseControl 3
  ${NSD_OnClick} $BrowseControl BrowseFolder
  Call SetupRefresh
  nsDialogs::Show
  System::Call 'gdi32::DeleteObject(p $LogoImage)'
FunctionEnd

Function ChangeLanguage
  Pop $0
  StrCpy $RequestedLanguage ${LANG_SIMPCHINESE}
  ${If} $0 == $EnglishControl
    StrCpy $RequestedLanguage ${LANG_ENGLISH}
  ${EndIf}
  ${If} $RequestedLanguage == $LANGUAGE
    Return
  ${EndIf}
  ; NSIS resolves its language table after .onInit. Changing $LANGUAGE here
  ; changes the radio state, but leaves LangString and native UI text behind.
  ; Relaunch at the confirmation page; never forward /S or installation consent.
  ; /D must be the final argument and must not be quoted (NSIS syntax).
  ${NSD_GetText} $PathControl $INSTDIR
  StrCpy $LanguageCommand '"$EXEPATH" /LANG=$RequestedLanguage'
  ${If} $ResultPath != ""
    StrCpy $LanguageCommand '$LanguageCommand /RESULT="$ResultPath"'
  ${EndIf}
  ClearErrors
  Exec '$LanguageCommand /D=$INSTDIR'
  ${If} ${Errors}
    MessageBox MB_ICONEXCLAMATION|MB_OK "$(LanguageSwitchFailed)"
    Call SetupRefresh
    Return
  ${EndIf}
  Quit
FunctionEnd

Function SetupRefresh
  ${NSD_GetText} $PathControl $INSTDIR
  Call ReadInstalledVersion
  !insertmacro SetCaption $BuildControl "$(ReleaseVersion)" $SmallFont "8B5A2B"
  ${If} $UpgradeMode == "update"
    !insertmacro SetCaption $TitleControl "$(SetupUpdateTitle)" $HeadingFont "1A2F4B"
    !insertmacro SetCaption $DescriptionControl "$(SetupUpdateDescription)" $SmallFont "7A8AA0"
  ${Else}
    !insertmacro SetCaption $TitleControl "$(SetupTitle)" $HeadingFont "1A2F4B"
    !insertmacro SetCaption $DescriptionControl "$(SetupDescription)" $SmallFont "7A8AA0"
  ${EndIf}
  !insertmacro SetCaption $PathLabel "$(FolderLabel)" $SmallFont "1A2F4B"
  !insertmacro SetCaption $PathNote "$(FolderNote)" $SmallFont "7A8AA0"
  ${NSD_SetText} $BrowseControl "$(BrowseLabel)"
  ${NSD_Uncheck} $ChineseControl
  ${NSD_Uncheck} $EnglishControl
  ${If} $LANGUAGE == ${LANG_ENGLISH}
    ${NSD_Check} $EnglishControl
  ${Else}
    ${NSD_Check} $ChineseControl
  ${EndIf}
  ${If} $UpgradeMode == "repair"
    !insertmacro Footer "$(RepairLabel)"
  ${ElseIf} $UpgradeMode == "update"
    !insertmacro Footer "$(UpdateLabel)"
  ${Else}
    !insertmacro Footer "$(InstallLabel)"
  ${EndIf}
  !insertmacro RefreshSkin
FunctionEnd

Function PathChanged
  Pop $0
  Call SetupRefresh
FunctionEnd
Function BrowseFolder
  Pop $0
  nsDialogs::SelectFolderDialog "$(FolderLabel)" "$INSTDIR"
  Pop $0
  ${If} $0 != error
    ${NSD_SetText} $PathControl "$0"
  ${EndIf}
FunctionEnd
Function ChooseInstance
  Pop $0
  SendMessage $InstanceControl ${LB_GETCURSEL} 0 0 $0
  ${If} $0 < 0
    Return
  ${EndIf}
  ${If} $0 < $ExistingCount
    IntOp $0 $0 + 1
    ReadINIStr $0 "$PLUGINSDIR\copies.ini" "copies" "$0"
  ${Else}
    StrCpy $0 "$LOCALAPPDATA\Programs\Afterglow"
    ; A fresh copy must not accidentally select the default existing folder.
    StrCpy $1 2
    next_copy:
      IfFileExists "$0\*" 0 new_copy
      StrCpy $0 "$LOCALAPPDATA\Programs\Afterglow-$1"
      IntOp $1 $1 + 1
      Goto next_copy
    new_copy:
  ${EndIf}
  ${NSD_SetText} $PathControl "$0"
FunctionEnd
Function SetupLeave
  ${NSD_GetText} $PathControl $INSTDIR
  Call DirectoryLeave
  StrCpy $InstallConfirmed 1
FunctionEnd

!macro ProgressAppearance PREFIX TITLE DESCRIPTION
Function ${PREFIX}ProgressShow
  FindWindow $Dialog "#32770" "" $HWNDPARENT
  SetCtlColors $Dialog "1A2F4B" "F5F1E4"
  !insertmacro Skin $Dialog 1
  GetDlgItem $0 $Dialog 8000
  !insertmacro SetCaption $0 "$(ReleaseVersion)" $SmallFont "8B5A2B"
  GetDlgItem $0 $Dialog 8001
  !insertmacro SetCaption $0 "${TITLE}" $HeadingFont "1A2F4B"
  GetDlgItem $0 $Dialog 8002
  !insertmacro SetCaption $0 "${DESCRIPTION}" $SmallFont "7A8AA0"
  ${If} "${PREFIX}" == "un."
    ${If} $DeleteUserData == 1
      ${NSD_SetText} $0 "$(RemovingDataDescription)"
    ${EndIf}
  ${ElseIf} $UpgradeMode != "install"
    ${NSD_SetText} $0 "$(UpdatingDescription)"
    GetDlgItem $0 $Dialog 8001
    ${NSD_SetText} $0 "$(UpdatingTitle)"
  ${EndIf}
  GetDlgItem $0 $Dialog 8003
  !insertmacro SetCaption $0 "$INSTDIR" $SmallFont "8B5A2B"
  GetDlgItem $0 $Dialog 1031
  ${NSD_SetStretchedImage} $0 "$PLUGINSDIR\appearance\sidebar.bmp" $LogoImage
  GetDlgItem $0 $Dialog 1004
  !insertmacro Skin $0 8
  !insertmacro Footer "$(InstallingTitle)"
  GetDlgItem $0 $HWNDPARENT 1
  ; NSIS owns disabling/enabling Next while work runs. Hiding it permanently
  ; prevented ordinary fallback installs from ever reaching the finish page.
  ShowWindow $0 ${SW_SHOW}
  !insertmacro RefreshSkin
FunctionEnd
!macroend
!insertmacro ProgressAppearance "" "$(InstallingTitle)" "$(InstallingDescription)"
!insertmacro ProgressAppearance "un." "$(RemovingTitle)" "$(RemovingDescription)"

Function FinishPage
  nsDialogs::Create 1018
  Pop $Dialog
  !insertmacro PageBrand
  ${NSD_CreateLabel} 204u 82u 322u 40u ""
  Pop $TitleControl
  ${NSD_CreateLabel} 204u 138u 322u 48u ""
  Pop $DescriptionControl
  ${If} $UpgradeMode == "install"
    !insertmacro SetCaption $TitleControl "$(FinishTitle)" $HeadingFont "1A2F4B"
    !insertmacro SetCaption $DescriptionControl "$(FinishDescription)" $SmallFont "7A8AA0"
  ${Else}
    !insertmacro SetCaption $TitleControl "$(UpdateFinishTitle)" $HeadingFont "1A2F4B"
    !insertmacro SetCaption $DescriptionControl "$(UpdateFinishDescription)" $SmallFont "7A8AA0"
  ${EndIf}
  ${NSD_CreateLabel} 204u 208u 322u 40u "$INSTDIR"
  Pop $0
  !insertmacro SetCaption $0 "$INSTDIR" $SmallFont "8B5A2B"
  ${NSD_CreateCheckbox} 204u 264u 322u 24u "$(LaunchLabel)"
  Pop $LaunchControl
  SendMessage $LaunchControl ${WM_SETFONT} $BodyFont 1
  !insertmacro Skin $LaunchControl 7
  ; Opening the application is opt-in on the finish page.
  ${NSD_Uncheck} $LaunchControl
  !insertmacro Footer "$(DoneLabel)"
  GetDlgItem $0 $HWNDPARENT 1
  ShowWindow $0 ${SW_SHOW}
  GetDlgItem $0 $HWNDPARENT 2
  ShowWindow $0 ${SW_HIDE}
  nsDialogs::Show
  System::Call 'gdi32::DeleteObject(p $LogoImage)'
FunctionEnd
Function FinishLeave
  ${NSD_GetState} $LaunchControl $0
  ${If} $0 == ${BST_CHECKED}
    Exec '"$INSTDIR\Afterglow.exe"'
  ${EndIf}
FunctionEnd

Function un.ConfirmPage
  nsDialogs::Create 1018
  Pop $Dialog
  !insertmacro PageBrand
  ${NSD_CreateRadioButton} 380u 24u 72u 24u "简体中文"
  Pop $ChineseControl
  SendMessage $ChineseControl ${WM_SETFONT} $SmallFont 1
  !insertmacro Skin $ChineseControl 4
  ${NSD_OnClick} $ChineseControl un.ChangeLanguage
  ${NSD_CreateRadioButton} 458u 24u 68u 24u "English"
  Pop $EnglishControl
  SendMessage $EnglishControl ${WM_SETFONT} $SmallFont 1
  !insertmacro Skin $EnglishControl 4
  ${NSD_OnClick} $EnglishControl un.ChangeLanguage
  ${If} $LANGUAGE == ${LANG_ENGLISH}
    ${NSD_Check} $EnglishControl
  ${Else}
    ${NSD_Check} $ChineseControl
  ${EndIf}
  ${NSD_CreateLabel} 204u 76u 322u 40u ""
  Pop $0
  !insertmacro SetCaption $0 "$(RemoveTitle)" $HeadingFont "1A2F4B"
  ${NSD_CreateLabel} 204u 130u 322u 48u ""
  Pop $0
  !insertmacro SetCaption $0 "$(RemoveDescription)" $SmallFont "7A8AA0"
  ${NSD_CreateLabel} 204u 188u 322u 34u "$INSTDIR"
  Pop $0
  !insertmacro SetCaption $0 "$INSTDIR" $SmallFont "8B5A2B"
  ${NSD_CreateCheckbox} 204u 235u 322u 23u "$(DeleteDataLabel)"
  Pop $DeleteDataControl
  SendMessage $DeleteDataControl ${WM_SETFONT} $BodyFont 1
  !insertmacro Skin $DeleteDataControl 7
  ${If} $DeleteUserData == 1
    ${NSD_Check} $DeleteDataControl
  ${Else}
    ${NSD_Uncheck} $DeleteDataControl
  ${EndIf}
  ${NSD_CreateLabel} 232u 263u 294u 44u ""
  Pop $0
  !insertmacro SetCaption $0 "$(DeleteDataHint)" $SmallFont "7A8AA0"
  !insertmacro Footer "$(RemoveLabel)"
  nsDialogs::Show
  System::Call 'gdi32::DeleteObject(p $LogoImage)'
FunctionEnd
Function un.ConfirmLeave
  Call un.CheckAppClosed
  ${NSD_GetState} $DeleteDataControl $0
  StrCpy $DeleteUserData 0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $DeleteUserData 1
  ${EndIf}
FunctionEnd

Function un.ChangeLanguage
  Pop $0
  StrCpy $RequestedLanguage ${LANG_SIMPCHINESE}
  ${If} $0 == $EnglishControl
    StrCpy $RequestedLanguage ${LANG_ENGLISH}
  ${EndIf}
  ${If} $RequestedLanguage == $LANGUAGE
    Return
  ${EndIf}
  ${NSD_GetState} $DeleteDataControl $1
  ; Launch the installed uninstaller, not the running temporary copy. NSIS
  ; creates its own new temporary copy and retains this installation's path.
  ; DELETE_SELECTED only restores the visible checkbox; the new wizard still
  ; requires Uninstall. It never enables data deletion for silent removal.
  ClearErrors
  Exec '"$INSTDIR\Uninstall.exe" /LANG=$RequestedLanguage /DELETE_SELECTED=$1'
  ${If} ${Errors}
    MessageBox MB_ICONEXCLAMATION|MB_OK "$(LanguageSwitchFailed)"
    ${NSD_Uncheck} $ChineseControl
    ${NSD_Uncheck} $EnglishControl
    ${If} $LANGUAGE == ${LANG_ENGLISH}
      ${NSD_Check} $EnglishControl
    ${Else}
      ${NSD_Check} $ChineseControl
    ${EndIf}
    Return
  ${EndIf}
  Quit
FunctionEnd
