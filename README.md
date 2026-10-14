# Clarity

Windows tray app. Num Lock + 8 toggles a headphone playback EQ through Equalizer APO. Audio that is already playing changes immediately. The default playback device stays where it is.

The silicone seal cuts outside noise. This app does not use a microphone and does not cancel room noise. It keeps playback clear.

## Setup

Windows only. Python 3.12 or newer. From this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Setup creates `.venv`, installs `requirements.txt`, and installs Equalizer APO 1.4.2 on the headphone output if it is not already there. Approve the administrator prompt when it appears. A reboot is not part of setup.

## Run

```powershell
.\.venv\Scripts\python.exe .\main.py
```

Leave that process running. Num Lock alone still toggles the keyboard light. A corner note shows `Clarity on` or `Clarity off` for 1.35 seconds. That note does not appear when a saved on/off state is restored at startup.
