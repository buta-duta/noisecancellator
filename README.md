# Clarity

Windows tray app. Num Lock + 8 toggles headphone playback. The default playback device stays where it is. Already-playing audio keeps going.

Setup chooses the headphone output, the input, and one mode: Off, Clarity EQ, or Mic cancellation. Clarity EQ writes an Equalizer APO curve and does not open the microphone. Mic cancellation opens the chosen microphone and plays an opposing signal through the headphones. The headphone microphone is the primary reference because it sits near the ear. The laptop microphone array is the weaker reference. This is not AirPods Pro: those use microphones and a chip inside the ear cup, and this app only softens steady low rumble through Windows. The setup window states the band that the measured delay can support.

Off closes the microphone and bypasses the EQ.

## Setup

Windows only. Python 3.12 or newer. From this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Setup creates `.venv`, installs `requirements.txt`, and installs Equalizer APO 1.4.2 on the headphone output if it is not already there. It tries SFX/EFX, then SFX/MFX, then LFX/GFX, restarting Windows Audio between attempts, and stops when `EqualizerAPO.dll` is loaded. It does not register capture devices. Approve the administrator prompt when it appears. A reboot is not part of setup.

The first time the tray app runs, and any time you choose Setup in the tray, it asks for the headphone output, the headphone mic or the laptop mic array, and the mode. The choice is saved.

## Run

```powershell
.\.venv\Scripts\python.exe .\main.py
```

Leave that process running. Hold Num Lock and press 8, or press 8 within a moment of tapping Num Lock. The number row and the numpad both count. Num Lock alone still toggles the keyboard light. A corner note and a tray notification show `Clarity on` or `Clarity off` for 1.35 seconds. That note does not appear when a saved on/off state is restored at startup. If Equalizer APO is not loaded, the app says to run `setup.ps1` and does not claim cancellation is active.
