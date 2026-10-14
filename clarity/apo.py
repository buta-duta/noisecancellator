import subprocess


def apo_loaded():
    try:
        completed = subprocess.run(
            ["tasklist", "/m", "EqualizerAPO.dll"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=0x08000000,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = f"{completed.stdout}\n{completed.stderr}"
    if "No tasks are running" in text:
        return False
    return "EqualizerAPO.dll" in text
