import json
import os
import time


def app_dir():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(root, "ClarityMode")
    os.makedirs(path, exist_ok=True)
    return path


def _state_path():
    return os.path.join(app_dir(), "state.json")


def _ledger_path():
    return os.path.join(app_dir(), "session_ledger.json")


def load_enabled():
    path = _state_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return bool(data.get("enabled", False))
    except (OSError, json.JSONDecodeError, TypeError):
        return False


def save_enabled(enabled):
    path = _state_path()
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump({"enabled": bool(enabled)}, handle)
    os.replace(temp, path)


def log(message):
    try:
        path = os.path.join(app_dir(), "clarity.log")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(message) + "\n")
    except OSError:
        pass


def load_ledger():
    path = _ledger_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_ledger(data):
    path = _ledger_path()
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def clear_ledger():
    path = _ledger_path()
    try:
        os.remove(path)
    except OSError:
        pass
