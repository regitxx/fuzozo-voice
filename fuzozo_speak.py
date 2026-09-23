#!/usr/bin/env python3
"""Generate a short phrase locally and send it through the verified USB route.

Use the project Python 3.11 environment. This is a bench
tool for the signature-checked FZ1012 1.0.42 unit. Keep it awake during transfer.
The temporary RAM helper is restored before playback; factory assets stay intact.
"""
import argparse
import audioop
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import wave

from fuzozo_console import Console, ROOT
from ram_wav_transfer import elf_text, transfer
from speech_clip import render


def prepare_wav(data, peak_target=8000):
    if not 1000 <= peak_target <= 24000:
        raise ValueError('Speech peak must be between 1000 and 24000')
    with wave.open(io.BytesIO(data), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getcomptype()) != (1, 2, 'NONE'):
            raise ValueError('Expected mono PCM16 WAV')
        frames, rate = source.getnframes(), source.getframerate()
        if not 8000 <= rate <= 48000 or not 0 < frames <= rate * 4:
            raise ValueError('Use a phrase of at most four seconds; audio is never truncated')
        pcm = source.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError('Truncated source WAV')
    pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 16000, None)
    peak = audioop.max(pcm, 2)
    if peak == 0:
        raise ValueError('Speech file is silent')
    # The default preserves the verified hello level. Voice mode can request
    # the user's moderately louder level without changing factory volume.
    pcm = audioop.mul(pcm, 2, peak_target / peak)
    output = io.BytesIO()
    with wave.open(output, 'wb') as target:
        target.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        target.writeframes(pcm)
    return output.getvalue()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--text', help='Short phrase, synthesized by the configured speech provider')
    source.add_argument('--wav', type=Path, help='Existing mono PCM16 WAV, at most four seconds')
    p.add_argument('--port', help='Explicit CH340 port; required unless --prepare-only')
    p.add_argument('--prepare-only', action='store_true', help='Save the WAV without touching the robot')
    args = p.parse_args()
    if not args.prepare_only and not args.port:
        p.error('--port is required for robot playback')
    os.umask(0o077)
    data = args.wav.read_bytes() if args.wav else render(args.text)[0]
    wav = prepare_wav(data)
    folder = ROOT / 'outputs'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('speech-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.wav')
    with path.open('xb') as output:
        output.write(wav)
    print(json.dumps({'host_wav': str(path), 'bytes': len(wav)}), flush=True)
    if args.prepare_only:
        return
    code = elf_text(ROOT / 'run/ram-wav-helper.o')
    with Console(args.port) as console:
        print(json.dumps({'captures': str(console.folder)}), flush=True)
        print(json.dumps(transfer(console, wav, code)), flush=True)


if __name__ == '__main__':
    main()
