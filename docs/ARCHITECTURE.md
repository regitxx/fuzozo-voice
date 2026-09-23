# How the bridge works

## Investigation method

The original investigation physically correlated a BLE device through power
cycles, reconstructed authenticated Bluetooth exchanges, and investigated Wi-Fi
setup. That did not yield a dependable Wi-Fi speech route. A working USB data
cable exposed a CH340 serial console. Command discovery, offline firmware
analysis, and live reads located the existing prompt player, filesystem calls,
recorder callback and volume setters.

A newer vendor firmware image was examined offline, but it was **not installed**.
Live function signatures were checked against the actual 1.0.42 target; addresses
were not assumed compatible merely because a different image had a similar
function. No firmware image or vendor account material is distributed here.

## Device-side changes

This is not a firmware replacement. Small ARM Thumb helpers are built from the
included `.S` sources and temporarily placed in verified unused SRAM. The bridge
borrows a CLI command entry, allocates bounded PSRAM, and restores/verifies the
entry and borrowed memory afterward. Files containing generated speech are
written to `/labvoice/`; normal volume setters can persist volume settings.
Therefore "no firmware flashing" does not mean "no persistent device writes."

`ram_wav_transfer.py` checks vectors/function bytes and command registry state,
allocates a WAV buffer, transfers acknowledged blocks, invokes bounded file
writes, restores RAM and checks the on-device MD5 before requesting playback.
`cpu1 prompt_wav` is the confirmed playback route. A different command,
`cpu1 wav_play`, faulted during investigation and is not used.

The stream helper forwards the original microphone callback while taking one
channel, averaging sample pairs and encoding 8 kHz mu-law into a 65536-byte
ring. The host drains that ring over the debug channel and reconstructs PCM
for recognition. Ring overwrite, unknown offsets and missing acknowledgements
stop the session. Only fully identified malformed read replies can be retried;
writes are not blindly replayed. The original callback is restored on cleanup.

## Main source files

| File | Purpose |
| --- | --- |
| `setup_device.py`, `fuzozo_console.py` | Enroll identity; verified console sessions and logs |
| `bkreg_probe.py` | Bounded binary debug reads |
| `ram_bulk_io.py`, `ram_wav_transfer.py` | Block transport and checksum-gated WAV upload |
| `mic_stream.py`, `ram_mic_ring.S` | Continuous microphone tap and buffered transport |
| `live_listen.py`, `fuzozo_voice.py` | Utterance detection, Whisper, wake-word gating |
| `volume_control.py`, `ram_volume.S` | Native volume and mute settings |
| `ai_backend.py`, `speech_clip.py` | Configurable chat and speech providers |
| `panel_server.py`, `panel/` | Local UI, serialized worker and cancellation |

## Known limitations and useful next research

- The firmware's factory behavior still runs, including loud sounds. Whether
  some bridge operations trigger additional factory chatter is unresolved.
- The master volume value is readable/settable, but custom/factory loudness is
  poorly balanced. Separate player gain/mixing needs investigation.
- Wake-word recognition has confused "Robot" with other words. A recorded
  "Thank you" was rejected as unaddressed. No reliable autonomous conversational
  cycle is claimed despite successful individual microphone/AI/playback tests.
- Speaker output uses uploaded files, not streaming PCM. Faster AI alone cannot
  remove that transport delay. Listening pauses during responses.
- Deep sleep, USB interruptions and reboots invalidate the session. Helpers are
  temporary; the robot does not boot independently into this companion.
- The GUI settings and generated files live on the host; there is no remote
  deployment of a complete agent to the robot.
- There is no AI-controlled movement, emotion selection or expression API.
- Newly generated panel reply files are deleted only after playback STOP;
  deletion can fail. Retained paths are bounded to 20 in one process, but the
  count is not persistent across restarts. Do not run unattended indefinitely.

Bench results from the original unit are observations, not proof that another
unit or this standalone refactor performs identically. Automated tests emulate
helper behavior and provider contracts; acoustic testing remains necessary.
