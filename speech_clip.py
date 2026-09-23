#!/usr/bin/env python3
"""Render a bounded 24 kHz mono PCM16 WAV using the configured provider."""
import argparse
import audioop
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave
import httpx
from configuration import settings, auth_headers

def available():
    cfg = settings()
    return bool(shutil.which('say')) if cfg['tts_provider'] == 'macos' else bool(cfg['tts_url'])

def normalize(data):
    with wave.open(io.BytesIO(data), 'rb') as w:
        channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if channels not in (1, 2) or width != 2 or w.getcomptype() != 'NONE' or not 8000 <= rate <= 48000:
            raise ValueError('TTS must return mono/stereo PCM16 WAV at 8–48 kHz')
        if not 0 < frames <= rate*30:
            raise ValueError('TTS audio must be at most 30 seconds')
        pcm = w.readframes(frames)
        if len(pcm) != frames*channels*width:
            raise ValueError('Truncated TTS WAV')
    if channels == 2: pcm = audioop.tomono(pcm, 2, .5, .5)
    pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 24000, None)
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setparams((1,2,24000,0,'NONE','not compressed')); w.writeframes(pcm)
    return out.getvalue(), len(pcm)/48000

def render(text):
    if not isinstance(text,str) or not 0 < len(text.strip()) <= 600:
        raise ValueError('Use 1–600 characters')
    cfg = settings()
    if cfg['tts_provider'] == 'macos':
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'text.txt', Path(folder)/'speech.wav'
            source.write_text(text)
            args = ['say', '-f', str(source), '-o', str(target), '--file-format=WAVE', '--data-format=LEI16@24000']
            if cfg['tts_voice']: args += ['-v', cfg['tts_voice']]
            subprocess.run(args, check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return normalize(target.read_bytes())
    if not cfg['tts_url']: raise ValueError('Set tts_url in config.json')
    payload = {'text':text.strip()} if cfg['tts_provider']=='http-wav' else {
        'model':cfg['tts_model'], 'voice':cfg['tts_voice'], 'input':text.strip(), 'response_format':'wav'}
    with httpx.Client(timeout=120, trust_env=False, follow_redirects=False) as client:
        with client.stream('POST', cfg['tts_url'], headers=auth_headers(cfg['tts_api_key_env']), json=payload) as response:
            response.raise_for_status()
            data=bytearray()
            for part in response.iter_bytes():
                data.extend(part)
                if len(data)>6_000_000: raise ValueError('TTS response too large')
    return normalize(bytes(data))

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('text'); p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); os.umask(0o077)
    data,seconds=render(args.text); args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('xb') as f: f.write(data)
    print(f'Saved {seconds:.2f}s speech to {args.output}')
if __name__=='__main__': main()
