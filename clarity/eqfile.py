import os

from clarity.dsp import clarity_config


def eq_path():
    override = os.environ.get("CLARITY_EQ_FILE")
    if override:
        return override
    folder = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "EqualizerAPO", "config")
    return os.path.join(folder, "clarity.txt")


def write_eq(enabled):
    path = eq_path()
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        raise OSError(f"Equalizer APO config folder is missing: {folder}")
    text = clarity_config(enabled)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    sibling = os.path.join(folder, "config.txt")
    if os.path.isfile(sibling):
        try:
            os.utime(sibling, None)
        except OSError:
            pass
    return path
