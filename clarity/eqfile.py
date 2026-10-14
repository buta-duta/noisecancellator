import os

from clarity.dsp import clarity_config
from clarity.persist import app_dir


def eq_path():
    override = os.environ.get("CLARITY_EQ_FILE")
    if override:
        return override
    folder = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "EqualizerAPO", "config")
    if os.path.isdir(folder):
        return os.path.join(folder, "clarity.txt")
    return os.path.join(app_dir(), "clarity.txt")


def write_eq(enabled):
    path = eq_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    text = clarity_config(enabled)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    return path
