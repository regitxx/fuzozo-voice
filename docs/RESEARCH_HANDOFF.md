# Research handoff: reproduce the investigation and continue the systems work

This guide is for the next engineer, not just someone using the panel.
It separates repeatable analysis from the inputs and physical evidence that
must be collected again. Start with the [investigation narrative](REVERSE_ENGINEERING.md).

## Scope and required inputs

| Investigation | Public tools now provided | Input/evidence you must supply |
| --- | --- | --- |
| USB discovery and console | Port listing, passive serial capture, enrollment, console inspection | Your physical robot and a data cable; confirmed identity |
| Binary debug and firmware profile | Read-only bounded reads and profile snapshot | Enrolled FZ1012 1.0.42 responding to USB |
| SDK reference analysis | Exact-hash C source downloader and source index | Public upstream network access; SDK license terms still apply |
| ARM firmware analysis | Hash check, bounded XZ unpacking, strings and annotated Thumb disassembly | Your legitimately obtained firmware image; acquisition provenance |
| Companion-app analysis | Mach-O, Swift metadata, Objective-C selector and caller tools | Your installed app executable in a supported readable format |
| BLE reply verification | Offline AES/CRC verifier and synthetic test | Your own captured notifications and matching local key |
| RAM helpers, speaker and microphone | Helper sources, emulator tests, transfer/capture code | Physical testing on your unit; audible confirmation |
| Original cloud-authentication discovery | Narrative and source references only | Not an automated/reproduced workflow in this release |

The public package does **not** include private keys, vendor binaries, original
recordings, or complete cloud-login/BLE acquisition clients. Your robot's real
captures and your firmware/app copy are required to reproduce the physical
findings. Synthetic tests prove parser/helper behavior, not vendor compatibility.

## 1. Establish an independent research workspace

```sh
git clone https://github.com/regitxx/fuzozo-voice.git
cd fuzozo-voice
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-research.txt
python build_helpers.py
python -m unittest discover -p 'test_*.py'
mkdir -p run/research
python -m research_tools.fetch_references
```

The downloader reconstructs the 29 individually indexed Beken C/header files
under ignored `run/references/`, preserving their paths. Each file must match
its recorded Git blob hash. Existing files are verified rather than silently
replaced. GitHub's anonymous API rate limit may require waiting and rerunning;
the tool resumes by checking already-downloaded files.

The other SDK checkout links and pinned revisions are in
[RESEARCH_SOURCES.md](RESEARCH_SOURCES.md). The reference libraries are not the
exact complete Fuzozo source tree. Read their code to form hypotheses, then
compare with the installed image and observed behavior.

## 2. Repeat app-analysis techniques on an original fixture first

On macOS with Xcode Command Line Tools:

```sh
swiftc -target arm64-apple-macosx13.0 -emit-library -module-name Fixture \
  examples/MetadataFixture.swift -o run/research/fixture.dylib
python -m research_tools.swift_metadata run/research/fixture.dylib \
  --output run/research/fixture-types.json
```

Expected: a type ending in `.RobotSettings` with `volume` and `muted` fields.
The automated test compiles this original fixture and checks those fields.
Nothing in the fixture is copied from the vendor application.

For a locally obtained app executable, use the same command with its path.
The parser expects a thin little-endian 64-bit Mach-O; the disassembly/caller
analyzer specifically assumes ARM64. If your executable is universal, select
its ARM64 slice using your normal Mach-O tooling first. No decryption is
implemented. Inspect the reported encryption regions; ciphertext is not code.
Unsupported chained fixups, stripped metadata and different app versions can
require parser changes. The original metadata reader handled pointer format 6.

```sh
python -m research_tools.swift_metadata /path/to/your/app-executable \
  --output run/research/app-types.json
python -m research_tools.macho_inspect /path/to/your/app-executable \
  --objc-method publishDps
# Replace addresses below with functions/ranges found in YOUR binary:
python -m research_tools.macho_inspect /path/to/your/app-executable \
  --callers YOUR_FUNCTION_ADDRESS
python -m research_tools.macho_inspect /path/to/your/app-executable \
  --start YOUR_START_ADDRESS --end YOUR_END_ADDRESS \
  --output run/research/app-disassembly.txt
```

These tools parse metadata, find direct branch references, and annotate a
bounded disassembly using `xcrun llvm-objdump`. They are heuristic aids, not a
complete decompiler or proof of runtime values. Inspect suspicious instructions
and call sites yourself. Outputs can expose embedded application data; keep
`run/` private rather than posting complete dumps.

## 3. Repeat the offline firmware analysis

Obtain firmware through a source you are entitled to access, record the URL or
acquisition method privately, and hash the original bytes. The original newer
1.0.44 package had SHA256
`0294910933b643506f00fabff1aea962a9d69b1d90fdd6dac86dc260bc8269da`
and an XZ stream at byte offset 64; it unpacked to 3,081,136 bytes. That package
was studied offline and was **not flashed** onto the 1.0.42 robot. A differently
packaged image may need a different unpacker.

```sh
python -m research_tools.firmware_inspect /path/to/firmware-package \
  --sha256 YOUR_EXPECTED_SHA256 --unpack-xz --xz-offset 64 \
  --output run/research/firmware.bin
python -m research_tools.firmware_inspect run/research/firmware.bin \
  --base 0x02010000 --strings --output run/research/firmware-strings.json
python -m research_tools.firmware_inspect run/research/firmware.bin \
  --base 0x02010000 --start YOUR_START_ADDRESS --end YOUR_END_ADDRESS \
  --output run/research/firmware-disassembly.txt
```

The base is an analysis assumption to verify against vectors, literal pointers
and string references. Start with strings such as `prompt_wav`, filesystem
commands and audio-event names, then follow code references in your preferred
reverse-engineering tool. The included disassembler annotates PC-relative
literal loads; it does not automatically recover every string reference or
identify every function. It rejects out-of-image ranges and oversized output.

Do not copy a newer image's function addresses into the live 1.0.42 profile.
The supplied image hash documents a research input; it is not permission to
upload that image or proof that it matches the robot.

## 4. Repeat discovery and verify the live USB profile without RAM writes

Stop all other bridge processes. Physically identify the adapter by disconnect/
reconnect, then optionally observe it without transmitting commands:

```sh
python -m serial.tools.list_ports -v
python -m research_tools.serial_listen --port /dev/cu.YOUR_PORT --seconds 4
```

Opening serial can still affect hardware line states through its driver;
RTS/DTR are deasserted, and this tool sends no bytes. Captures are private
because factory logs may contain credentials.

Follow [SETUP.md](SETUP.md) to enroll the MAC/version. Then:

```sh
python fuzozo_console.py --port /dev/cu.YOUR_PORT inspect
python -m research_tools.snapshot_profile --port /dev/cu.YOUR_PORT
python bkreg_probe.py --port /dev/cu.YOUR_PORT --address 0x02010000 --words 4
```

The snapshot reads published code signatures and CLI/scratch state. It saves
actual versus expected bytes without writing RAM. A mismatch is valuable new
evidence: stop, record the build and investigate it offline. These tools retain
the supported-profile guard; they do not provide an automatic port to unknown
firmware or a full image-dump workflow.

## 5. Trace a single command through every layer

For a short custom WAV, follow these source files in order:

1. `fuzozo_console.py`: identity, firmware, bounded replies and invalidation.
2. `bkreg_probe.py`: binary request framing and exact reply matching.
3. `ram_wav_transfer.py`: live signatures, allocation, restoration and checksum.
4. `ram_bulk_io.py` / `ram_bulk_put.S`: text-safe blocks reconstructed in RAM.
5. `ram_wav_helper.S`: actual firmware open/write/close calls and completion.
6. `Console.play`: matching the exact filename and ordered playback events.

Emulator tests deliberately cover short writes, failure returns, register/
stack behavior and completion state. On hardware, record the checksum,
restoration result and what was audibly heard. A player log cannot substitute
for an acoustic result.

For microphone work, follow `mic_capture.py`, `ram_mic_ring.S`, `mic_stream.py`,
then `live_listen.py`. Record samples received, duration, maximum backlog,
overflow state and restoration. Recognition output is a separate observation.

## 6. Independently verify BLE captures when you have them

```sh
python -m research_tools.verify_ble_capture \
  /path/to/your-capture.json /path/to/your-private-records.json
```

The capture schema is `{"events":[{"type":"notification","hex":"..."}]}`;
non-notification events are ignored. Records are a one-element list containing
`localKey` for your correlated device. Capture notification fragments from the
initial information reply onward so the session-key challenge is present.
The verifier checks framing, AES-CBC replies, CRC, and reply padding, reporting
only command IDs/counts. It does not acquire keys, log into a vendor account or
connect to Bluetooth. `test_research.py` generates entirely synthetic encrypted
replies and verifies both valid and corrupted cases.

## 7. Continue the unfinished systems work

Prioritize narrow experiments over broad changes:

- **Audio balance:** compare one known custom clip with one stock sound at the
  same master volume. Trace their player/mixer calls and gain parameters. Do not
  assume digital peak normalization gives equal perceived loudness.
- **Factory behavior:** identify the producer of unwanted sounds and whether
  a command triggers it. Find a reversible way to suspend that producer without
  disabling the microphone or the custom player.
- **Latency:** timestamp recognition, model generation, synthesis, transfer and
  playback separately. Research a streamed speaker input instead of claiming
  that a faster model fixes file-upload delay.
- **Recognition:** inspect locally recorded utterances and acceptance reasons.
  Separate microphone signal quality, factory-audio interference, transcription
  errors and wake-word rejection before changing thresholds.
- **New firmware profiles:** first establish addresses and behavior offline;
  add dedicated signatures and emulator tests rather than bypassing old guards.

For each change record the commit, robot model/version, input hashes, hypothesis,
exact commands, observed bytes/timing, audible result, and restoration checks.
Keep secrets and full captures in your private lab archive. Share a redacted
summary plus the smallest synthetic regression test you can make.

**Acceptance criterion for the unfinished companion:** a person addresses the
robot, the intended request is recognized, the chosen AI generates a response,
and that response is audibly intelligible without disruptive factory sounds,
across repeated turns and reconnects. That result is still outstanding.
