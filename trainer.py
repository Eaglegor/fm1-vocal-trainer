"""Windows microphone bridge and practice-session runner."""
import argparse
import math
import queue
import sys
from bisect import bisect_right
from dataclasses import dataclass

import mido
import numpy as np
import pygame.midi as midi
import sounddevice as sd


@dataclass(frozen=True)
class Step:
    start: float
    end: float
    notes: tuple

    @property
    def target(self):
        return self.notes[-1]


PATTERNS = {
    "scale": [0, 2, 4, 5, 7, 9, 11, 12, 11, 9, 7, 5, 4, 2, 0],
    "minor": [0, 2, 3, 5, 7, 8, 10, 12, 10, 8, 7, 5, 3, 2, 0],
    "arpeggio": [0, 4, 7, 12, 7, 4, 0],
    "melodic": [0, 7, 0],
    "harmonic": [0, 0, 0],
}


def warmup(name, root, bpm):
    beat = 60 / bpm
    return [Step(i * beat, (i + 0.92) * beat,
                 (root, root + 7) if name == "harmonic" else (root + offset,))
            for i, offset in enumerate(PATTERNS[name])]


def song(path, track_index, channel):
    song_file = mido.MidiFile(path)
    if song_file.type == 2 or song_file.ticks_per_beat <= 0:
        raise ValueError("Choose a format 0/1 MIDI file with beat-based timing.")
    if not 0 <= track_index < len(song_file.tracks):
        raise ValueError(f"Track must be between 0 and {len(song_file.tracks)-1}.")
    events = []
    for index, track in enumerate(song_file.tracks):
        tick = 0
        for event in track:
            tick += event.time
            if event.type == "set_tempo" or (index == track_index and
                    event.type in ("note_on", "note_off") and event.channel == channel - 1):
                events.append((tick, event))

    steps = []
    previous = 0
    seconds = 0.0
    tempo = 500000
    active = None
    for tick, event in sorted(events, key=lambda pair: pair[0]):
        seconds += mido.tick2second(tick - previous, song_file.ticks_per_beat, tempo)
        previous = tick
        if event.type == "set_tempo":
            tempo = event.tempo
        elif event.type == "note_on" and event.velocity:
            if active is not None:
                raise ValueError("Overlapping notes. Choose a monophonic melody track/channel.")
            active = (seconds, event.note)
        elif active is not None and event.note == active[1]:
            if seconds > active[0]:
                steps.append(Step(active[0], seconds, (event.note,)))
            active = None
    if active is not None or not steps:
        raise ValueError("No complete melody on this track/channel. Check the MIDI selection.")
    return steps


MIC_TRANSPOSE_SEMITONES = 12


def pitch(samples, rate):
    """Estimate the microphone's fractional MIDI note on the FM1's corrected scale."""
    x = np.asarray(samples, dtype=np.float64)
    x = x - x.mean()
    if np.mean(x * x) < 0.000025:
        return None
    # Average small groups before decimation to reduce high-frequency content.
    stride = max(1, int(rate // 12000))
    x = x[:len(x) // stride * stride].reshape(-1, stride).mean(axis=1)
    rate /= stride
    longest = min(math.ceil(rate / 65), len(x) // 2)
    width = len(x) - longest
    ref = x[:width]
    energy = np.r_[0.0, np.cumsum(x * x)]
    diff = np.maximum(0, energy[width:] - energy[:-width] + energy[width]
                      - 2 * np.correlate(x, ref, "valid"))
    norm = np.ones_like(diff)
    norm[1:] = diff[1:] * np.arange(1, longest + 1) / np.maximum(np.cumsum(diff[1:]), 1e-18)
    for lag in range(max(2, int(rate / 1100)), longest):
        if norm[lag] >= 0.15:
            continue
        while lag < longest - 1 and norm[lag + 1] < norm[lag]:
            lag += 1
        left, center, right = norm[lag-1:lag+2]
        curvature = left + right - 2 * center
        offset = np.clip((left-right) / (2*curvature), -0.5, 0.5) if curvature > 0 else 0
        hz = rate / (lag + offset)
        if 65 <= hz <= 1100:
            return 69 + 12 * math.log2(hz / 440) + MIC_TRANSPOSE_SEMITONES
        return None
    return None


class Score:
    def __init__(self, steps):
        self.steps = steps
        self.ends = [s.end for s in steps]
        self.duration = sum(s.end - s.start for s in steps)
        self.voiced = self.hit = self.error = 0.0

    def observe(self, start, end, voice):
        if voice is None:
            return
        index = bisect_right(self.ends, start)
        while index < len(self.steps) and self.steps[index].start < end:
            step = self.steps[index]
            overlap = min(end, step.end) - max(start, step.start)
            cents = abs(voice - step.target) * 100
            self.voiced += overlap
            self.error += cents * overlap
            if cents <= 50:
                self.hit += overlap
            index += 1


def name(note):
    if note is None:
        return "--"
    n = round(note)
    return f"{'C C# D D# E F F# G G# A A# B'.split()[n % 12]}{n // 12 - 1}"


def run(args, steps, out):
    rate = float(sd.query_devices(args.mic, "input")["default_samplerate"])
    frames = round(rate * 0.04)
    packets = queue.Queue(maxsize=12)
    score = Score(steps)
    starts = [s.start for s in steps]
    active = None
    completed = False

    def capture(data, count, timing, status):
        stamp = timing.inputBufferAdcTime
        if not stamp:
            stamp = timing.currentTime - count / rate
        try:
            packets.put_nowait((stamp, None if status.input_overflow else data[:, 0].copy()))
        except queue.Full:
            pass  # Lost time remains in the denominator.

    def play(step):
        nonlocal active
        if active is not None:
            for n in active.notes:
                out.note_off(n)
        active = step
        if step is not None:
            for n in step.notes:
                out.note_on(n, 80)
        out.write_short(0xbf, 20, step.target + 1 if step else 0)

    try:
        with sd.InputStream(device=args.mic, channels=1, samplerate=rate, blocksize=frames,
                            dtype="float32", callback=capture) as stream:
            origin = stream.time + (1 if steps else 0)
            play(None)
            print("Listening. Use headphones. Ctrl+C ends practice.")
            while True:
                now = stream.time - origin
                if steps and now > steps[-1].end + 1:
                    break
                index = bisect_right(starts, now) - 1
                current = steps[index] if index >= 0 and now < steps[index].end else None
                if current is not active:
                    play(current)
                try:
                    stamp, data = packets.get(timeout=0.005)
                except queue.Empty:
                    if not stream.active:
                        raise RuntimeError("Microphone stream stopped during the session.")
                    continue
                voice = pitch(data, rate) if data is not None else None
                code = 0 if voice is None else 1 + round(voice * 100)
                out.write_short(0xef, code & 127, code >> 7)
                start = stamp - origin - args.delay_ms / 1000
                score.observe(start, start + frames/rate, voice)
                cents = "" if voice is None else f" {100*(voice-round(voice)):+.0f} ct"
                print(f"\rTarget {name(current.target if current else None):4}   Voice {name(voice):4}{cents:9}", end="", flush=True)
                if steps and start >= steps[-1].end:
                    break
            completed = True
    finally:
        play(None)
        out.write_short(0xef, 0, 0)
        print()
    if completed and steps:
        percent = round(100 * score.hit / score.duration)
        out.write_short(0xbf, 21, percent + 1)
        mean = f"{score.error/score.voiced:.1f} cents" if score.voiced else "n/a"
        print(f"In tune {percent}%   Voiced {100*score.voiced/score.duration:.1f}%   Mean absolute error {mean}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["devices", "freestyle", "song", *PATTERNS])
    p.add_argument("file", nargs="?")
    p.add_argument("--mic", type=int, help="Windows audio input ID (default: system input)")
    p.add_argument("--out", type=int, help="FM1 MIDI output ID from devices")
    p.add_argument("--track", type=int, default=0, help="zero-based melody track")
    p.add_argument("--channel", type=int, choices=range(1,17), default=1)
    p.add_argument("--root", type=int, choices=range(0,115), default=60)
    p.add_argument("--bpm", type=int, choices=range(30,241), default=90)
    p.add_argument("--delay-ms", type=int, choices=range(0,501), default=0,
                   help="compensate measured monitoring/output delay")
    args = p.parse_args()
    if args.mode == "song" and not args.file:
        p.error("song requires a MIDI file")
    midi.init()
    try:
        if args.mode == "devices":
            print(sd.query_devices())
            for i in range(midi.get_count()):
                _, label, _, output, _ = midi.get_device_info(i)
                if output:
                    print(f"MIDI output {i}: {label.decode(errors='replace')}")
            return
        if args.out is None:
            p.error("select the FM1 port using devices and --out")
        steps = (song(args.file, args.track, args.channel) if args.mode == "song"
                 else warmup(args.mode, args.root, args.bpm) if args.mode in PATTERNS else [])
        if any(s.target == 127 for s in steps):
            p.error("supported melody range is MIDI notes 0 through 126")
        out = midi.Output(args.out)
        try:
            run(args, steps, out)
        finally:
            out.close()
    finally:
        midi.quit()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, EOFError, RuntimeError, sd.PortAudioError, midi.MidiException) as exc:
        sys.exit(str(exc))
