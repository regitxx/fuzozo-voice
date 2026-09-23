# Connect your own AI and speech server

## What "real time" means here

The robot microphone can stream continuously to the USB host. Recognition,
model generation, speech synthesis, file upload and playback still happen in
sequence. The bridge stops listening to answer; it does not support interrupting
speech, echo cancellation, duplex audio or a realtime WebSocket voice API.
Changing the AI provider does not remove USB upload delay or factory chatter.
A reliable complete autonomous exchange has not yet been demonstrated.

## Chat endpoint contract

Copy `config.example.json` to ignored `config.json`. Set:

- `ai_base_url`: API prefix, including `/v1`, without `/chat/completions`.
- `ai_model`: exact model identifier served by that system.
- `ai_api_key_env`: environment-variable name containing the bearer token.
- `system_prompt`: your companion's personality.

The adapter sends `POST <base>/chat/completions` with `model`, `messages`, and
`stream:false`. It reads `choices[0].message.content`. The model must return
text, not just tool calls. The connection check/CLI doctor also needs
`GET <base>/models` returning `data[].id`. The panel can still attempt chat if
a provider rejects model listing, but the CLI doctor and CLI conversation
currently require it. APIs with different schemas need an adapter; this is not
universal support for every hosted agent product.

Authentication keys never enter the web settings or committed JSON. Export
keys in the Terminal that starts the panel; a Finder-launched process does not
inherit exports from another Terminal. For example in zsh:

```sh
read -s 'FUZOZO_AI_API_KEY?AI API key: '
printf '\n'
export FUZOZO_AI_API_KEY
.venv/bin/python start_panel.py
```

Stop an existing panel before changing config or keys; the launcher otherwise
reuses it. Keys are sent only to their respective configured endpoints, with
redirect following disabled. Do not embed a password/token in the URL.

## LM Studio

Enable the server and load a chat model, then configure:

```json
{
  "ai_base_url": "http://127.0.0.1:1234/v1",
  "ai_model": "EXACT_LOADED_MODEL_ID",
  "tts_provider": "macos"
}
```

Use the model ID from its `/v1/models` response. The original lab used a Mac
Studio-hosted model; no particular model or Mac Studio hardware is required.
See [LM Studio's developer documentation](https://lmstudio.ai/docs/developer).

## Ollama

Use an installed chat-capable model and the compatible endpoint:

```json
{
  "ai_base_url": "http://127.0.0.1:11434/v1",
  "ai_model": "YOUR_INSTALLED_MODEL_TAG",
  "tts_provider": "macos"
}
```

Use the exact tag shown by `ollama list`. Compatibility depends on the selected
model/server version. See [Ollama's official compatibility documentation](https://docs.ollama.com/api/openai-compatibility).

## A separate machine, Tailscale, or hosted service

Keep the USB bridge/panel on the computer physically attached to Fuzozo. Run the
model server elsewhere and set `ai_base_url` to its reachable API prefix, e.g.
`http://YOUR_TAILSCALE_HOST:1234/v1`. The server must listen on an interface that
host can reach, and its firewall/tailnet policy must allow the connection.
Never paste the original developer's IP or credentials into your configuration.

For an internet-hosted compatible provider, use its documented **HTTPS** base
URL, model ID and API-key environment variable. For a private tailnet/LAN, use
its approved network address. Model-provider quotas and response times apply.
The control panel remains loopback-only; remote AI configuration does not
publish robot controls to the network.

```sh
.venv/bin/python fuzozo_agent.py --doctor
.venv/bin/python fuzozo_agent.py --prompt 'Say hello to the lab.' --prepare-only
```

The second command generates an AI answer and WAV without opening the robot.
Short CLI replies must fit seven words and four seconds; the panel handles
longer speech in sections, with pauses for uploads.

## Speech providers are configured separately

A working chat API does not imply that the same server supports speech.

**Built-in macOS speech (default):** `"tts_provider":"macos"`. No external
service/key is needed. `say -v '?'` lists installed voices; set `tts_voice` to
an exact installed voice or leave it empty for the system default.

**A custom WAV server:** use `"tts_provider":"http-wav"` and set `tts_url` to
the full synthesis URL. The bridge posts `{"text":"Hello"}` and expects binary
PCM16 WAV in the HTTP response. This can wrap your own Piper, Qwen or other
speech service; those servers are not bundled or auto-started.

**A compatible audio/speech API:** use `"tts_provider":"compatible"`,
`tts_url` as the full `/v1/audio/speech` URL, and provider-supported `tts_model`
and `tts_voice`. The body is:

```json
{"model":"YOUR_TTS_MODEL","voice":"YOUR_VOICE","input":"Hello","response_format":"wav"}
```

`tts_api_key_env` defaults to `FUZOZO_TTS_API_KEY`, separate from the AI key.
The server must honor WAV output; MP3, raw PCM and float WAV are not supported.
Mono/stereo PCM16 WAV at 8–48 kHz is converted to mono 24 kHz internally, then
16 kHz for the robot. Responses are limited to 30 seconds and 6 MB each.
Long panel text is split before synthesis; extreme speaking rates may still
exceed the per-request duration limit.

## Recognition and privacy

Whisper runs on the USB host's CPU. The initial model download needs internet;
after caching, recognition uses local files. The default `base.en` model and
recognition language are English; multilingual conversation is not implemented.

Only accepted transcripts and chat history are sent to the AI server. Text to
synthesize is sent to the selected TTS server (or local `say`). Audio captures,
transcripts, previews and raw device logs remain in ignored `run/`, `outputs/`
and `models/`. Their retention is local and manual; they can include sensitive
speech or factory credentials. Do not upload these directories with bug reports.
