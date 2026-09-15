; Tauri's default check only closes the UI executable. The bundled Python
; backend also holds DLLs open and must exit before upgrade/uninstall.
!ifndef VINOTE_MAIN_EXE
  !define VINOTE_MAIN_EXE "vinote.exe"
!endif
!ifndef VINOTE_BACKEND_EXE
  !define VINOTE_BACKEND_EXE "vinote-backend.exe"
!endif
!ifndef VINOTE_APP_NAME
  !define VINOTE_APP_NAME "VINote"
!endif
!macro NSIS_HOOK_PREINSTALL
  !insertmacro CheckIfAppIsRunning "${VINOTE_MAIN_EXE}" "${VINOTE_APP_NAME}"
  !insertmacro CheckIfAppIsRunning "${VINOTE_BACKEND_EXE}" "${VINOTE_APP_NAME} backend"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro CheckIfAppIsRunning "${VINOTE_BACKEND_EXE}" "${VINOTE_APP_NAME} backend"
!macroend
