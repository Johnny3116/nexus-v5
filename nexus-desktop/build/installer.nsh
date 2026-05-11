; Custom NSIS macros for Nexus Desktop installer

!macro customInstall
  ; Write .env to install directory if it doesn't already exist
  IfFileExists "$INSTDIR\.env" env_exists env_missing

  env_missing:
    FileOpen $0 "$INSTDIR\.env" w
    FileWrite $0 "WORKSTATION_TOOL_TOKEN=nexus-wsp-2026-secret$\r$\n"
    FileWrite $0 "WORKSTATION_TOOL_PORT=8889$\r$\n"
    FileWrite $0 "NEXUS_AVATAR_URL=https://nexusbody.tail344870.ts.net:8001$\r$\n"
    FileClose $0

  env_exists:

  ; Create README next to .env so user knows where to edit it
  IfFileExists "$INSTDIR\README-config.txt" done readme_missing

  readme_missing:
    FileOpen $1 "$INSTDIR\README-config.txt" w
    FileWrite $1 "Nexus Desktop — Configuration$\r$\n"
    FileWrite $1 "==============================$\r$\n$\r$\n"
    FileWrite $1 "Edit .env in this folder to configure:$\r$\n$\r$\n"
    FileWrite $1 "  WORKSTATION_TOOL_TOKEN  — Bearer token (must match NexusBody .env)$\r$\n"
    FileWrite $1 "  WORKSTATION_TOOL_PORT   — Tool server port (default: 8889)$\r$\n"
    FileWrite $1 "  NEXUS_AVATAR_URL        — Avatar server URL$\r$\n$\r$\n"
    FileWrite $1 "Prerequisites:$\r$\n"
    FileWrite $1 "  - Tailscale must be installed and connected$\r$\n"
    FileWrite $1 "  - NexusBody must be online and reachable$\r$\n"
    FileWrite $1 "  - Same WORKSTATION_TOOL_TOKEN must be in NexusBody .env$\r$\n"
    FileClose $1

  done:
!macroend

!macro customUnInstall
  ; Remove .env and readme on uninstall (optional — comment out to preserve)
  ; Delete "$INSTDIR\.env"
  ; Delete "$INSTDIR\README-config.txt"
!macroend
