# Fuzozo Voice Lab

Experimental USB voice and AI control for the **Fuzozo FZ1012**, by [regitxx](https://github.com/regitxx).

Give a robot text to speak, connect it to your own AI server, adjust sound levels,
and experiment with its built-in microphone. Includes a local web panel and the
source for the small ARM RAM helpers used by the USB bridge.

**This is a research prototype, not a finished replacement firmware.** Custom
speech and microphone capture were demonstrated on one FZ1012 running **1.0.42**.
Other physical units have not been tested. Hands-free conversation remains
experimental, and replies are not low-latency, full-duplex audio.

## What works, and what does not

| Capability | Evidence / limitation |
| --- | --- |
| Custom speaker playback | Heard on the original unit; each upload is checksum checked |
| Continuous microphone transport | 60 seconds received in 60.35 seconds in a bench test |
| AI text chat and speech previews | Working prototype; standalone provider adapter has automated tests |
| Master volume | Native setting changes and readback verified; affects factory audio too |
| Mute | Native setter exposed; acoustic effectiveness still needs confirmation |
| Automatic conversation | Wake-word recognition unreliable; no confirmed uninterrupted conversational cycle |
| Factory chatter suppression | Not implemented; factory sounds can dominate custom speech |
| Reply latency | Observed roughly 11–32 seconds for recent short speech jobs; not a guarantee |
| Wi-Fi-only / standalone AI | Not implemented; USB host must stay connected |
| Expressions and movement | Factory behavior continues; no AI control implemented |

The speaker path uploads complete WAV sections before playback. Continuous
microphone capture does **not** mean continuous speaker streaming. Raising the
speech slider has not resolved all loudness differences between factory and
custom audio. See [architecture and limitations](docs/ARCHITECTURE.md).

## How it was reverse-engineered

For an engineer continuing the work, start with the [research handoff](docs/RESEARCH_HANDOFF.md).
It includes commands, analysis tools, synthetic fixtures, required input files,
and acceptance criteria for the unfinished systems.

Read the [step-by-step investigation](docs/REVERSE_ENGINEERING.md): device
identification, Bluetooth/app analysis, the USB console, firmware disassembly,
binary-transfer failures, temporary ARM helpers, verified speaker playback and
continuous microphone capture. It includes the unsuccessful routes and explains
what each test did—and did not—prove.

## Requirements

- macOS with Python **3.11**, Xcode Command Line Tools (`xcode-select --install`).
  Python 3.13+ is unsupported because this prototype uses `audioop`.
- A data-capable USB-C cable and FZ1012 with the **1.0.42** firmware profile.
- A reachable AI server with `/v1/chat/completions` and `/v1/models`.
- macOS `say` for basic local speech, or a configured HTTP WAV/TTS endpoint.
- Internet access for the initial Whisper model download when using voice mode.

Linux may be adaptable, but it is not validated; the launchers/default TTS are
macOS-specific. Windows is unsupported (`fcntl`/`termios` are used).

## Quick start

```sh
git clone https://github.com/regitxx/fuzozo-voice.git
cd fuzozo-voice
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python build_helpers.py
cp config.example.json config.json
```

Edit `config.json`: set `ai_base_url` and an exact `ai_model` served there.
The default endpoint is local LM Studio; the model is intentionally blank.
Configuration changes require a panel restart.

Enroll your own robot using [SETUP.md](docs/SETUP.md). Enrollment reads identity
and version only; it does not require a vendor account or identity documents.
Do not copy somebody else's `run/device.json`.

```sh
python -m serial.tools.list_ports -v
python setup_device.py --port /dev/cu.YOUR_PORT
# Physically confirm the FZ1012, then use the MAC printed by the probe:
python setup_device.py --port /dev/cu.YOUR_PORT --mac YOUR_ROBOT_MAC
python fuzozo_agent.py --doctor
python start_panel.py
```

Open **http://127.0.0.1:8787**. The panel is local to this Mac. Keep the robot
awake with microphone and sound enabled for conversation tests. Click **Connect
Fuzozo**. Start with **Prepare preview**, then a short **Speak through Fuzozo**
request. Warn nearby people before playback; factory audio may be loud.

The `Start Fuzozo Panel.command` launcher also starts/reuses the panel. Terminal
commands use the same config and enrolled identity. Stop the old lab panel before
running this standalone version; do not run two checkouts against the same robot.
Their local lock files do not coordinate across different directories.

## Bring your own AI

See [HOSTED_AI.md](docs/HOSTED_AI.md) for LM Studio, Ollama, remote servers over
Tailscale, compatible hosted APIs, API-key handling and custom speech services.
The model runs on that server; it is not installed on the robot.

```text
Robot microphone → USB → local Whisper → your AI server
                                       ↓ text reply
Robot speaker    ← USB WAV upload ← speech provider
```

For voice mode, click **Start listening**, wait for **LISTENING**, and say
“Robot,” followed by your question. You can pause after “Robot” and ask within
10 seconds. Quiet/uncertain/unaddressed recognition is rejected. Listening pauses
while generating and playing replies. The first start downloads the configured
Whisper model; use `python -c 'from fuzozo_voice import recognizer; recognizer()'`
to download it in advance. Model files follow their own upstream licenses.

## Development

```sh
python -m pip install -r requirements-dev.txt
python build_helpers.py
python -m unittest discover -p 'test_*.py'
```

Tests cover ARM helper behavior in emulation, bounded transfers, retry rules,
recognition gating, web access controls, cancellation and provider adapters.
They do not substitute for acoustic or second-device testing. Firmware blobs,
recordings, credentials and private research captures are not distributed.

- [Setup another robot and troubleshooting](docs/SETUP.md)
- [Hosted AI and speech configuration](docs/HOSTED_AI.md)
- [Step-by-step reverse-engineering investigation](docs/REVERSE_ENGINEERING.md)
- [Reproduce the analysis and continue development](docs/RESEARCH_HANDOFF.md)
- [C references and what can be reproduced](docs/RESEARCH_SOURCES.md)
- [Architecture and current limitations](docs/ARCHITECTURE.md)
- [Privacy and reporting issues](SECURITY.md)

MIT license for this repository's code. Independent project; not affiliated with
Fuzozo, Robopoet, Tuya, or Beken. Vendor firmware and third-party models are not
covered by this repository's license.
