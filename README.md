# FM1 vocal trainer

The FM1 runs the practice session. Its panel selects the exercise, plays reference notes through the internal synth and scores incoming sung pitch. The Windows companion listens to one microphone and sends pitch over USB MIDI.

## Practice from the FM1

The Windows bridge raises recognized microphone notes by one octave for the FM1 display and scoring. For example, a 220 Hz mic tone is reported as MIDI note 69 (A4), with its original cents deviation.

1. Start the microphone companion once. Select the Focusrite and input channel, leave **FM1 audio output** at **Off**, select the FM1 MIDI output (often **USB-Midi**), and click **Start**. Leave it running between exercises. Use headphones for the FM1 reference sound.
2. Open **HOME**. Turn **K1** to select FREESTYLE, SCALE (major), MINOR, ARPEGGIO, MELODIC (successive fifth), HARMONIC (sing the upper note), or MELODY (the embedded seven-note song). Freestyle displays the keyboard and microphone immediately.
3. While stopped, use **K2** to set the root (default C4) and **K3** to set tempo (default 90 BPM). For MELODY, C4 is original pitch and 120 BPM is the MIDI file's original timing.
4. Press **PLAY** to hear the selected root and its perfect fifth together for one beat. Take a breath during the next beat. The first target and scoring begin with the exercise. Follow **TARGET** and watch **VOICE**. Press **PLAY** again to cancel. Completing the exercise shows **SCORE**, the percentage of target-note time within 50 cents. Silence counts as missed time, rests are excluded, and pitches expire if the bridge stops sending. Play again to repeat.

### Put another MIDI melody in the panel slot

The MVP stores one melody in the application image. From the project directory, run the generator with a monophonic MIDI track (zero-based) and channel (one-based), then rebuild and deploy the firmware. The generated bank is checked in, so the normal firmware build needs no Python environment. The SDK checks whether a replacement song fits this device's application partition.

~~~powershell
.\.venv\Scripts\python make_routines.py "my-song.mid" --track 1 --channel 1
.\build.ps1 -Toolchain C:\JL\pi32
~~~

## Boot area and first hardware test

The application is a small patch against [M-VAVE FM1 Open V14 at 4c7496d](https://github.com/m-vave/fm1_open/tree/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41). The vendor SDK builds a full .fwsc container with boot bytes inside it. The Windows build checks all 16 KiB of those bytes against an independently built, unmodified copy of that revision. A matching package prefix alone cannot establish which physical sectors an updater erases. This project uses a specific PC install action whose allowed range starts at flash address 0x04000.

1. Use [M-Flasher 0.12.1 for Windows](https://github.com/jvitkauskas/m-flasher/releases/tag/v0.12.1). Close the trainer and other MIDI clients. Connect one powered FM-1 with a USB data cable. Use DOWNLOAD MODE if needed. Decline its optional bootloader installation prompt.
2. Confirm the model and **Back up the whole flash**. Keep the 1 MiB .bin and its metadata. This build has passed static SDK checks only. First boot, LCD, sound, subsequent update and recovery still require a physical unit.
3. Choose **Install firmware (.fwsc)** and select **firmware/vocal-trainer.fwsc**. Inspect the proposed write map before confirming. Its entire write range must start at or above 0x04000 and, for this build, end before 0x73000. Cancel if the boot area is selected, the model is uncertain, or the layout differs. Keep power connected through verification.
4. For a first-unit acceptance test, take another full backup before leaving download mode. Compare the first 0x4000 bytes of both raw dumps with the command below. Then restart, open HOME and run freestyle. Confirm a held key and sung note appear independently. Confirm a second firmware-only update is reachable before relying on field updates.
5. For rollback in download mode choose your own earlier backup and **Keep this unit's bootloader**. Access to download mode after an application failure depends on the existing bootloader and hardware. Preserving the boot region does not guarantee recovery from every failed update.

The reviewed firmware operation bounds its write plan to the app region. The block erase implementation chooses a larger erase only when the address is aligned and the whole block fits. The SDK also retains the vendor USB-MIDI update handler. This project's boot-preservation claim applies to the reviewed M-Flasher firmware action. [Firmware write plan](https://github.com/jvitkauskas/m-flasher/blob/8fbece7348d758ac284325eed455781675ac95ff/src/ops.rs#L361-L403) · [Erase implementation](https://github.com/jvitkauskas/m-flasher/blob/8fbece7348d758ac284325eed455781675ac95ff/src/jl.rs#L565-L576)

~~~powershell
py -c "from pathlib import Path; a,b=[Path(p).read_bytes() for p in ('before.bin','after.bin')]; assert len(a)==len(b)==1048576 and a[:16384]==b[:16384], 'Boot verification failed'; print('Boot area matches')"
~~~

## Run on Windows

Install Python 3.13 x64 and use PowerShell in this directory.

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python trainer.py devices
~~~

Use the FM1 MIDI **output** ID printed by devices for --out. Substitute your IDs for 5 and 1 below. Omit --mic for the Windows default input. Use a pitched timbre on FM1 track 1 with MIDI input channel 1.

### Desktop microphone companion

After the Python setup above, connect the FM1 by USB and double-click **Start Companion.cmd**. Select the microphone or ASIO interface and its physical input channel. For the microphone waveform, choose the FM1's Windows playback endpoint under **FM1 audio output**. For the trainer's VOICE display, choose its USB MIDI port under **FM1 MIDI output**. Both routes can run together, or you can set either to **Off**. Press **Start** and sing. The window shows the detected note, cents and peak input level. **Stop** releases the ports before you start a CLI practice session.

The app probes the installed ASIO drivers at startup and lists the host API beside each endpoint. It also supports ordinary Windows microphones. If an ASIO driver fails to initialize, select a WASAPI input. To skip ASIO discovery entirely, run `.\.venv\Scripts\python companion.py --no-asio`. For an ASIO microphone on a separate interface, use the FM1's WASAPI playback endpoint. Both ends need a common sample rate. If Windows exposes only FM1 MIDI, leave audio output Off and use live pitch. Use headphones when routing microphone audio and restart the companion after plugging in a new device. [sounddevice ASIO support](https://python-sounddevice.readthedocs.io/en/0.5.6/installation.html#asio-support)

### Optional PC-controlled CLI sessions

~~~powershell
.\.venv\Scripts\python trainer.py freestyle --out 5 --mic 1
.\.venv\Scripts\python trainer.py scale --root 55 --bpm 80 --out 5
.\.venv\Scripts\python trainer.py harmonic --root 60 --out 5
.\.venv\Scripts\python trainer.py song example.mid --track 0 --channel 1 --out 5
~~~

Warm-ups include scale (major), minor (natural minor), arpeggio (major triad), melodic (successive root and fifth) and harmonic (root and fifth together, sing the fifth). Root is a MIDI note, with 60 = middle C. Freestyle runs until Ctrl+C. The KEY row follows a physical held key and clears on release. The VOICE row clears on silence or loss of pitch messages.

Song mode reads standard format 0/1 MIDI with beat-based timing. Select a monophonic track and channel. Track numbers start at 0, channels at 1. Tempo changes on other tracks and rests are respected. A one-second lead-in precedes playback. The detector uses 40 ms frames and a 65–1100 Hz search range. For a measured fixed guide-output delay, pass --delay-ms to align captured frames with the reference.

**Score** is the percentage of target-note time sung within 50 cents. Silence during notes counts as missed time. Rests are excluded. In CLI mode the console also reports voiced coverage and duration-weighted mean absolute pitch error for voiced time. Scores assess pitch against this guide, including octave errors.

## Build and development

Install the [JieLi Windows 2.5.3 toolchain listed by M-VAVE](https://github.com/m-vave/fm1_open/tree/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41#build), then run:

~~~powershell
.\build.ps1 -Toolchain C:\JL\pi32
.\.venv\Scripts\python -m unittest -v
~~~

The script fetches the pinned vendor source into .build, applies firmware/trainer.patch, installs trainer.inc and invokes the official SDK verifier and packager. It outputs firmware/vocal-trainer.fwsc after checking the boot digest. It has no device-write step. The boot reference SHA-256 is 2981ccf8d12a132c82d8b5e959c2d27d62f13bc51419225cacc87a6e82d58171. The pinned SDK's own license, linking exception and binary SDK terms apply to the firmware. [License](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/LICENSE.md) · [Third-party notices](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/THIRD_PARTY.md)

## Compact controller interface

A replacement controller needs a microphone input, monophonic pitch tracking and a USB host port for the FM1 USB-MIDI device. A digital USB microphone also requires USB host support on the controller for microphone capture. An integrated microphone or audio ADC is another option. Direct USB microphone hosting by the FM1 has not been demonstrated here.

| USB MIDI to FM1 | Meaning |
| --- | --- |
| Channel 1 Note On / Off | Play / release reference notes |
| Channel 16 Pitch Bend, raw unsigned 14-bit value | 0 = unvoiced. Otherwise 1 + round(100 × fractional MIDI note). A4 = 6901. Send low seven bits first, refresh every 40 ms. Voice expires after 400 ms. |
| Channel 16 CC20 | 0 clears target. Values 1–127 select target notes 0–126 and reset the previous score. |
| Channel 16 CC21 | 0 clears score. Values 1–101 display 0–100 percent. |
