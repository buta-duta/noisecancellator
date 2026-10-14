import threading

import tkinter as tk
from tkinter import ttk

from clarity.devices import capture_choices, render_choices
from clarity.fxlms import limit_line
from clarity.persist import load_state, save_state
from clarity.wasapi import output_period

HOTKEY_HINT = "Toggle: Num Lock + 8"
_lock = threading.Lock()
_window = None


def _limit_for(device_id, state):
    if (
        state.get("output_id") == device_id
        and state.get("delay_samples") is not None
        and state.get("sample_rate")
    ):
        return limit_line(state["delay_samples"], state["sample_rate"], state.get("delay_kind") or "structural")
    try:
        frames, rate = output_period(device_id)
    except Exception:
        frames, rate = 480, 48000
    return limit_line(frames * 2, rate, "structural")


def open_setup(on_save=None):
    global _window
    with _lock:
        if _window is not None and _window.is_alive():
            return
        _window = threading.Thread(target=_dialog, args=(on_save,), name="clarity-setup", daemon=True)
        _window.start()


def _dialog(on_save=None):
    renders = render_choices()
    captures = capture_choices()
    state = load_state()
    root = tk.Tk()
    root.title("Clarity setup")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0)

    ttk.Label(frame, text="Output").grid(row=0, column=0, sticky="w")
    output = ttk.Combobox(frame, width=72, state="readonly")
    output["values"] = [item[1] for item in renders]
    output.grid(row=1, column=0, sticky="ew", pady=(0, 10))

    ttk.Label(frame, text="Input").grid(row=2, column=0, sticky="w")
    mic = ttk.Combobox(frame, width=72, state="readonly")
    mic["values"] = [item[1] for item in captures]
    mic.grid(row=3, column=0, sticky="ew", pady=(0, 10))

    ttk.Label(frame, text="Mode").grid(row=4, column=0, sticky="w")
    mode = tk.StringVar(value=state.get("mode") if state.get("mode") in ("off", "eq", "anc") else "off")
    modes = ttk.Frame(frame)
    modes.grid(row=5, column=0, sticky="w", pady=(0, 10))
    ttk.Radiobutton(modes, text="Off", variable=mode, value="off").pack(side="left")
    ttk.Radiobutton(modes, text="Clarity EQ", variable=mode, value="eq").pack(side="left", padx=(12, 0))
    ttk.Radiobutton(modes, text="Mic cancellation", variable=mode, value="anc").pack(side="left", padx=(12, 0))

    ttk.Label(frame, text=HOTKEY_HINT).grid(row=6, column=0, sticky="w", pady=(0, 8))
    limit = ttk.Label(frame, text="", wraplength=520)
    limit.grid(row=7, column=0, sticky="w", pady=(0, 12))

    def selected_output():
        index = output.current()
        if index < 0 or index >= len(renders):
            return ""
        return renders[index][0]

    def refresh_limit(_event=None):
        device_id = selected_output()
        if not device_id:
            limit.configure(text="Choose headphones to see the cancellation band.")
            return
        limit.configure(text=_limit_for(device_id, state))

    def choose(box, rows, saved_id, prefer):
        if not rows:
            return
        for index, row in enumerate(rows):
            if row[0] == saved_id:
                box.current(index)
                return
        for index, row in enumerate(rows):
            if prefer(row):
                box.current(index)
                return
        box.current(0)

    choose(output, renders, state.get("output_id") or "", lambda row: row[2] == "phones")
    choose(mic, captures, state.get("input_id") or "", lambda row: row[2] == "headphone")
    output.bind("<<ComboboxSelected>>", refresh_limit)
    refresh_limit()

    saved = {"ok": False}

    def save():
        out_index = output.current()
        in_index = mic.current()
        chosen = mode.get() if mode.get() in ("off", "eq", "anc") else "off"
        if chosen == "anc" and (out_index < 0 or in_index < 0):
            limit.configure(text="Choose headphones and a microphone.")
            return
        if chosen != "off" and renders and out_index < 0:
            limit.configure(text="Choose headphones.")
            return
        payload = {
            "mode": chosen,
            "setup_done": True,
            "armed": chosen if chosen in ("eq", "anc") else (state.get("armed") or "eq"),
        }
        if out_index >= 0:
            payload["output_id"] = renders[out_index][0]
        if in_index >= 0:
            payload["input_id"] = captures[in_index][0]
        save_state(payload)
        saved["ok"] = True
        root.destroy()

    ttk.Button(frame, text="Save", command=save).grid(row=8, column=0, sticky="e")
    root.mainloop()
    if saved["ok"] and on_save is not None:
        on_save()
