"""FM1 microphone companion. Run with --no-asio to skip ASIO discovery."""
import os
import sys
import subprocess


def select_driver():
    # Some installed ASIO drivers crash PortAudio during enumeration. Probe
    # in a separate process before loading the DLL into the desktop app.
    os.environ.pop("SD_ENABLE_ASIO", None)
    if os.name != "nt" or "--no-asio" in sys.argv:
        return "Using Windows audio."
    try:
        probe = subprocess.run(
            [sys.executable, "-c", "import sounddevice as s; "
             "raise SystemExit(0 if any(a['name']=='ASIO' and a['devices'] "
             "for a in s.query_hostapis()) else 1)"],
            env={**os.environ, "SD_ENABLE_ASIO": "1"}, timeout=12,
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return "ASIO discovery timed out. Using Windows audio."
    if probe.returncode == 0:
        os.environ["SD_ENABLE_ASIO"] = "1"
        return "ASIO available."
    return "ASIO unavailable. Using Windows audio."


if __name__ == "__main__":
    driver_status = select_driver()

import queue
import ctypes
import threading
import time
import tkinter as tk
from collections import deque
from contextlib import ExitStack
from tkinter import ttk

import numpy as np
import pygame.midi as midi
import sounddevice as sd

from trainer import name, pitch


def route(mic, channel, speaker, port, stop, report):
    # PortAudio loads the Focusrite ASIO COM driver on the calling thread.
    # Device enumeration on the Tk thread does not initialize this worker.
    with ExitStack() as cleanup:
        if os.name == "nt":
            ole = ctypes.windll.ole32
            result = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
            if result >= 0:
                cleanup.callback(ole.CoUninitialize)
            elif result != -2147417850:  # RPC_E_CHANGED_MODE: COM is already initialized.
                raise OSError(f"Windows audio initialization failed (HRESULT {result:#x}).")
        _route(mic, channel, speaker, port, stop, report)


def _route(mic, channel, speaker, port, stop, report):
    device = sd.query_devices(mic)
    asio = sd.query_hostapis(device["hostapi"])["name"] == "ASIO"
    inputs = dict(device=mic, channels=1 if asio else channel, dtype="float32")
    if asio:
        inputs["extra_settings"] = sd.AsioSettings([channel - 1])
    column = 0 if asio else channel - 1
    outputs = None
    rates = [device["default_samplerate"]]
    if speaker is not None:
        dest = sd.query_devices(speaker)
        outputs = dict(device=speaker, channels=min(2, dest["max_output_channels"]), dtype="float32")
        rates.insert(0, dest["default_samplerate"])
        if asio and mic != speaker and sd.query_hostapis(dest["hostapi"])["name"] == "ASIO":
            raise ValueError("For a separate FM1, select its Windows playback endpoint with the ASIO input.")
    last_error = None
    for rate in dict.fromkeys([*rates, 48000, 44100]):
        try:
            endpoint = "microphone"
            sd.check_input_settings(samplerate=rate, **inputs)
            if outputs:
                endpoint = "audio output"
                sd.check_output_settings(samplerate=rate, **outputs)
            break
        except sd.PortAudioError as exc:
            last_error = exc
    else:
        raise ValueError(f"Could not configure the {endpoint} at {rate:g} Hz: {last_error}") from last_error

    frames = round(rate * .04)
    voice_blocks = deque(maxlen=2)
    playback = deque(maxlen=3)
    ready = threading.Event()
    last_capture = time.monotonic()

    def capture(data, count, timing, status):
        nonlocal last_capture
        last_capture = time.monotonic()
        mono = data[:, column].copy()
        voice_blocks.append(mono)
        if outputs and mic != speaker:
            playback.append(mono)
        ready.set()

    def render(data, count, timing, status):
        try:
            data[:] = playback.popleft()[:, None]
        except IndexError:
            data.fill(0)

    def duplex(indata, outdata, count, timing, status):
        capture(indata, count, timing, status)
        outdata[:] = indata[:, column, None]

    with ExitStack() as stack:
        sender = None
        if port is not None:
            sender = midi.Output(port)
            stack.callback(sender.close)
            stack.callback(sender.write_short, 0xef, 0, 0)
        common = dict(samplerate=rate, blocksize=frames)
        if outputs and mic == speaker:
            stream = stack.enter_context(sd.Stream(
                **common, device=mic, channels=(inputs["channels"], outputs["channels"]),
                extra_settings=(inputs.get("extra_settings"), None), dtype="float32", callback=duplex))
            output_stream = stream
        else:
            stream = stack.enter_context(sd.InputStream(**common, **inputs, callback=capture))
            output_stream = stack.enter_context(sd.OutputStream(**common, **outputs, callback=render)) if outputs else None
        report(f"Streaming at {rate/1000:g} kHz")
        while not stop.is_set():
            ready.wait(.1)
            ready.clear()
            if not stream.active or (output_stream is not None and not output_stream.active):
                raise RuntimeError("An audio stream stopped. Check the connection and start again.")
            if time.monotonic() - last_capture > 3:
                raise RuntimeError("No microphone frames received. Check the selected input.")
            try:
                mono = voice_blocks.popleft()
            except IndexError:
                continue
            voice = pitch(mono, rate)
            if sender is not None:
                code = 0 if voice is None else 1 + round(voice * 100)
                sender.write_short(0xef, code & 127, code >> 7)
            level = 20 * np.log10(max(float(np.max(np.abs(mono))), 1e-6))
            cents = "" if voice is None else f"  {(voice-round(voice))*100:+.0f} ct"
            report(f"{name(voice)}{cents}     {level:.0f} dBFS")


def window(root, initial_status):
    root.title("FM1 microphone companion")
    panel = ttk.Frame(root, padding=18)
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(1, weight=1)
    devices = sd.query_devices()
    apis = sd.query_hostapis()

    def endpoints(field):
        ids = [i for i, d in enumerate(devices) if d[field]]
        return {f"{apis[devices[i]['hostapi']]['name']} · {devices[i]['name']} [{i}]": i for i in ids}

    microphones = endpoints("max_input_channels")
    speakers = {"Off": None, **endpoints("max_output_channels")}
    ports = {"Off": None}
    for i in range(midi.get_count()):
        _, label, _, output, _ = midi.get_device_info(i)
        if output:
            ports[f"{label.decode(errors='replace')} [{i}]"] = i

    def combo(row, title, values, preferred):
        ttk.Label(panel, text=title).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=6)
        box = ttk.Combobox(panel, values=list(values), width=56, state="readonly")
        box.grid(row=row, column=1, sticky="ew")
        if values:
            box.set(next((k for k in values if preferred(k)), next(iter(values))))
        return box

    def fm1(label):
        return "fm1" in label.lower().replace("-", "").replace(" ", "")

    mic = combo(0, "Microphone", microphones, lambda k: k.startswith("ASIO"))
    chan = combo(1, "Input channel", ["1"], lambda k: True)
    audio = combo(2, "FM1 audio output", speakers, lambda label: label == "Off")
    dest = combo(3, "FM1 MIDI output", ports, fm1)

    def channels(event=None):
        count = devices[microphones[mic.get()]]["max_input_channels"] if mic.get() else 1
        chan.configure(values=list(range(1, count + 1)))
        chan.set("1")
    mic.bind("<<ComboboxSelected>>", channels)
    channels()
    status = tk.StringVar(value=initial_status)
    ttk.Label(panel, textvariable=status, wraplength=490).grid(row=4, columnspan=2, sticky="w", pady=12)
    messages = queue.SimpleQueue()
    stop = threading.Event()
    worker = None
    closing = False

    def toggle():
        nonlocal worker
        if worker:
            stop.set()
            button.configure(state="disabled")
            return
        speaker, port = speakers[audio.get()], ports[dest.get()]
        if not mic.get() or (speaker is None and port is None):
            status.set("Choose a microphone and at least one FM1 output.")
            return
        args = microphones[mic.get()], int(chan.get()), speaker, port
        stop.clear()

        def work():
            try:
                route(*args, stop, messages.put)
            except Exception as exc:
                messages.put(f"Stopped · {exc}")
            else:
                messages.put("Stopped")
        for box in (mic, chan, audio, dest):
            box.configure(state="disabled")
        status.set("Opening devices…")
        button.configure(text="Stop")
        worker = threading.Thread(target=work, daemon=True)
        worker.start()

    def poll():
        nonlocal worker
        while not messages.empty():
            status.set(messages.get())
        if worker and not worker.is_alive():
            worker = None
            for box in (mic, chan, audio, dest):
                box.configure(state="readonly")
            button.configure(text="Start", state="normal")
        if closing and not worker:
            root.destroy()
        else:
            root.after(80, poll)

    def close():
        nonlocal closing
        closing = True
        stop.set()
        button.configure(state="disabled")

    button = ttk.Button(panel, text="Start", command=toggle)
    button.grid(row=5, column=1, sticky="e")
    root.protocol("WM_DELETE_WINDOW", close)
    poll()


if __name__ == "__main__":
    midi.init()
    try:
        root = tk.Tk()
        window(root, driver_status)
        root.mainloop()
    finally:
        midi.quit()
