!define version "r7"

!include "AddToPath.nsh"

InstallDir "$PROGRAMFILES\ftldat"
OutFile "ftldat ${version}.exe"
ShowInstDetails show
ShowUninstDetails show

Section
	SetOutPath $INSTDIR
	File /r dist\*
	WriteUninstaller $INSTDIR\uninstaller.exe
	CreateDirectory "$SMPROGRAMS\ftldat"
	CreateShortCut "$SMPROGRAMS\ftldat\Uninstall ftldat.lnk" \
					"$INSTDIR\uninstaller.exe"
	Push $INSTDIR
	Call AddToPath
SectionEnd

Section "Uninstall"
	Push $INSTDIR
    Call un.RemoveFromPath
	RMDir /r $INSTDIR
	RMDir /r "$SMPROGRAMS\ftldat"
SectionEnd
