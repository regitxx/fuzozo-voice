# How Fuzozo was reverse-engineered

This is the investigation behind this repository, conducted on one owned
**Fuzozo FZ1012 running firmware 1.0.42** in September 2026. The enclosure
remained closed. No replacement firmware was flashed.

The outcome is access to the robot's microphone, custom speaker playback and
native sound settings through USB. It is **not** a complete replacement of its
factory application or a finished realtime conversational system.

## 1. Establish which device is actually the robot

The box and device information supplied the model. Nearby Bluetooth devices
were scanned during the robot's Wi-Fi setup mode. A Tuya advertisement was a
candidate, but its name alone was insufficient: other products use similar
names. A controlled power-off/on experiment showed that the candidate vanished
with this robot and returned when it was powered on in setup mode.

That physical correlation established which device to investigate. Later USB
sessions checked the robot's MAC against the correlated identity. The public
version replaces the private lab identity record with explicit local enrollment
in `setup_device.py`; each user must enroll their own robot.

**Lesson:** interface discovery, device identity and permission to modify the
device are separate questions. Seeing a USB adapter does not prove that the
robot is awake, and seeing a BLE name does not establish identity.

## 2. Inspect the companion application and Bluetooth protocol

Static analysis of the companion application's executable provided strings,
Objective-C selectors and Swift metadata. Most of that particular executable
was readable; an early assumption that encryption blocked all static analysis
was incorrect. Following references from recognizable device-property names
revealed the bridge to the bundled Tuya SDK.

The investigation recovered mappings for properties such as battery, volume,
mute and brightness. These were initially **static findings**, not proof that
sending the corresponding values would work. No arbitrary speech-upload
property was established.

Following the SDK's device-specific account flow led to the authenticated
record for the physically identified robot and its local encryption material.
Request-signing reconstruction was checked against an existing signed request.
The lab client then reproduced encrypted BLE exchanges; replies were decrypted
and their CRCs checked independently. Information, network status and Wi-Fi
scans worked. The production account credentials, device keys, app binaries
and raw captures are not included in this repository.

This investigation did not produce a dependable Wi-Fi voice route. A network
setup request being acknowledged was not equivalent to joining Wi-Fi. The
vendor voice service also returned an entitlement error instead of a usable
voice session. Those results prompted the move to the local USB interface.

**Lesson:** distinguish transport success, authentication, command acceptance
and the desired physical effect. They are different milestones.

## 3. Find the USB console

A working data cable exposed a CH340 USB-to-serial adapter. The investigated
interface used **460800 baud, 8 data bits, no parity, one stop bit**, with RTS
and DTR deasserted.

Read-only commands including `macaddr get`, `devget version`, `help` and
`cpu1 help` established identity, firmware version and available CLI functions.
The robot could enumerate on USB while failing to answer, particularly around
sleep or power interruptions. Serial access therefore needed timeouts, explicit
identity checks and exclusive access rather than assuming an open port worked.

Command discovery exposed audio and filesystem-related functions. Existing
player functions were more promising than implementing an entire audio driver.
See [`fuzozo_console.py`](../fuzozo_console.py) for the bounded console wrapper.

## 4. Use firmware analysis to explain the commands

An official newer **1.0.44** firmware package was obtained for offline study.
Its package checksum was checked; the compressed image was unpacked and
examined as ARM Thumb code. Strings, references to those strings, literal
addresses and call sites helped identify command handlers and their callees.

The robot still ran **1.0.42**. A function found in the newer image was only a
lead. Before using an address on the robot, the investigation compared live
instruction bytes and relevant memory structures. The public code keeps these
signature checks rather than trusting a version label alone.

For example, finding a WAV command name was followed by examining its handler,
tracing how it passed the filename, and comparing the resulting runtime logs.
This connected static code analysis with observed behavior.

**Lesson:** a useful disassembly gives hypotheses to test. It does not prove
that another firmware build uses the same addresses or behavior.

## 5. Discover why a text console cannot upload an ordinary WAV

Initial filesystem writes accepted text arguments. Small controlled byte tests
showed that high-bit bytes survived, some control bytes disappeared, and the
write command appended a terminating NUL. The resulting file lengths and
checksums matched those transformations.

A normal WAV header contains binary values, including bytes that this input
path could not preserve. Changing the speech content could not repair a
transport that modified the header. A raw/headerless-audio experiment also did
not establish reliable custom speech.

The next question was whether the serial interface had a separate binary debug
protocol. A bounded link probe returned the expected reply. Subsequent aligned
memory reads established access to the firmware image and SRAM. The host
implementation is in [`bkreg_probe.py`](../bkreg_probe.py).

**Lesson:** test the transport with small known byte sequences before sending
large files. A checksum mismatch is evidence to explain, not to ignore.

## 6. Execute small temporary helpers without replacing firmware

Readback located the CLI's command registry. The transfer code verifies its
expected pointer, entry count, an existing command entry and an unused zeroed
SRAM region before borrowing anything. It also verifies function signatures.

The mechanism is:

1. Allocate a bounded buffer using the firmware's existing PSRAM allocator.
2. Write and read back test data in that allocated buffer.
3. Place a small Thumb helper and its context in checked unused SRAM.
4. Temporarily redirect a CLI entry to the helper's command descriptor.
5. Invoke the helper, wait for an explicit completion state and inspect results.
6. Restore the original entry and borrowed SRAM, verify restoration, then free
   memory when ownership and execution state remain known.

The helpers preserve the required registers and call existing firmware
functions. They do not implement new filesystem or speaker drivers. They are
built from source with `build_helpers.py` and tested with Unicorn emulation.
The files `ram_*.S` show the actual assembly, not pseudocode.

Losing the debug link is not permission to keep writing. Sleep/reboot/fault
markers invalidate the session; a helper whose execution status is uncertain
must not have its memory freed underneath it. The recovery routine recognizes
only an exact known interrupted microphone-helper state.

## 7. Transfer a file and prove that custom speech is audible

The first approach wrote RAM one word at a time and was slow. Bounded helpers
later moved **80-byte blocks** using hexadecimal command text and checked
acknowledgements. Hex text survives the console's character filtering while
the helper reconstructs the original bytes in memory.

The WAV helper calls the existing filesystem open/write/close functions. It
writes at most 2048 bytes per filesystem call, handles positive short writes,
and reports the final byte count, close result and completion stage. The host
checks the on-device file MD5 against the original WAV after restoration.
MD5 is used here to detect transfer corruption, not authenticate untrusted code.

Different playback commands produced different results:

| Experiment | What it established |
| --- | --- |
| File length and checksum matched | The intended bytes reached storage |
| `app_play_wav` logged playback but only factory sounds were reported | Logs alone did not establish audible custom speech |
| `wav_play` caused a firmware fault/restart | This route was unsuitable; it is not used by the bridge |
| `prompt_wav` logged the exact file and the user heard the English phrase with sound enabled | Custom audio reached the robot's own speaker |

The current player requires an ordered sequence containing the requested path,
playback START and playback STOP. Even this is firmware-reported evidence;
listening to the robot remains a separate check.

Read [`ram_wav_transfer.py`](../ram_wav_transfer.py) alongside
[`ram_wav_helper.S`](../ram_wav_helper.S). The original confirmed phrase was
“Hello, I am Fuzozo.” Later the user also heard an AI-generated arithmetic answer.

## 8. Tap the existing microphone callback

Firmware analysis and live reads identified the recorder object and its
callback. The first temporary tap copied a short recording while forwarding
to the original callback, preserving the factory call path. Captured audio
contained real speech, which local Whisper could transcribe imperfectly.

Downloading each recording after it finished introduced too much delay. The
next helper used a **65536-byte circular buffer**: it selected one channel,
averaged pairs of samples and encoded **8 kHz mu-law** while the host drained
the buffer concurrently. The forwarding call still went to the original
callback. Buffer counters exposed unread data and overflow conditions.

A 60-second bench test delivered 60 seconds of audio in **60.35 seconds**, with
maximum backlog **5120 bytes**, no overflow, and callback/scratch restoration
verified. This demonstrates continuous microphone transport, not a successful
end-to-end conversational turn.

See [`ram_mic_ring.S`](../ram_mic_ring.S), [`mic_stream.py`](../mic_stream.py)
and their emulator/transport tests. The recognition code rejects quiet,
uncertain or unaddressed speech. Wake-word mistakes remain a practical blocker.

## 9. Locate the native sound settings

The volume implementation follows the firmware's native volume and mute
setters instead of guessing peripheral register writes. Live configuration
readback confirmed a change from **100 to 20** on the original unit. An earlier
GPIO mute experiment did not provide reliable output-state evidence and is not
part of this public release.

Native setting readback is not an acoustic measurement. The robot can report
100% while custom speech remains much quieter than factory sounds. Independent
player gain, mixing and loudness processing are still hypotheses to investigate.
See [`volume_control.py`](../volume_control.py) and
[`ram_volume.S`](../ram_volume.S).

## 10. Assemble the host-side companion

Only after the individual paths worked were they connected:

```mermaid
flowchart LR
    M[Robot microphone] --> U[USB audio capture]
    U --> S[Local speech recognition]
    S --> A[Configured AI server]
    A --> T[Speech synthesis]
    T --> F[Checksum-checked WAV upload]
    F --> P[Existing robot prompt player]
```

The public release makes the AI and speech providers configurable and replaces
the private device record with per-user enrollment. The web panel serializes
hardware work, keeps credentials server-side and exposes connection, speech,
chat, sound and experimental listening controls.

This arrangement leaves the original firmware running. Factory chatter,
expressions and sleep behavior still exist. Listening pauses for replies;
file uploads remain slow. No low-latency, duplex conversation or persistent
on-device AI installation is claimed.

For the SDK C/header files consulted during this work and the scope of what
is reproducible, see [Research sources](RESEARCH_SOURCES.md). The public bridge
does not depend on those reference trees at build time.

## How to study or reproduce the reasoning

Start with [SETUP.md](SETUP.md), not raw memory writes. Then read the console,
transfer and microphone source in that order. For each experiment record:

- **Question:** one behavior you want to explain.
- **Action:** the smallest controlled test that distinguishes possibilities.
- **Observation:** bytes, timing, readback or what was physically heard.
- **Conclusion:** exactly what those observations establish, plus what remains
  uncertain.

The raw investigation captures are private because they contain device/account
material and recordings. This write-up summarizes them; it is not a public raw
capture dataset. Tests in this repository are reproducible without vendor
firmware blobs, but physical results on another unit remain unverified.
