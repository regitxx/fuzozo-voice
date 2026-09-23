#!/usr/bin/env python3
"""Robot-microphone conversation over USB; speech recognition stays on the Mac.

This bench loop streams the robot microphone continuously, detects utterances,
and pauses listening for replies. Factory-sound suppression remains unverified.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import wave

import httpx
import numpy as np

from fuzozo_agent import (bridge_lock, companion_module, selected_port,
                         system_message, turn)
from fuzozo_console import Console, ROOT
from mic_capture import capture


def recognizer():
    from faster_whisper import WhisperModel
    from configuration import settings
    cfg = settings()
    return WhisperModel(cfg['stt_model'], device='cpu', compute_type='int8', cpu_threads=4,
                        download_root=str(ROOT / 'models/whisper'))


def recognize(model, path, wake_word='robot', addressed=False):
    with wave.open(str(path), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('Unexpected microphone WAV format')
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32)
    rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    result = {'rms': round(rms, 2), 'transcript': '', 'accepted': False,
              'reason': 'below speech level', 'segments': []}
    # Do not normalize background noise into speech; the muted-microphone
    # bench capture was RMS 37–65, versus RMS 4249 for actual nearby speech.
    if rms < 180:
        return result
    segments, _ = model.transcribe(samples / 32768.0, language='en', beam_size=5,
                                   vad_filter=True, condition_on_previous_text=False,
                                   temperature=0, initial_prompt=wake_word.capitalize()+'.')
    rows = [{'text': s.text.strip(), 'avg_logprob': s.avg_logprob,
             'no_speech_prob': s.no_speech_prob, 'compression_ratio': s.compression_ratio}
            for s in segments]
    result['segments'] = rows
    text = ' '.join(s['text'] for s in rows).strip()
    result['transcript'] = text
    if not rows or any(s['avg_logprob'] < -1.0 or s['no_speech_prob'] > .5 or
                       s['compression_ratio'] > 2.4 for s in rows):
        result['reason'] = 'uncertain speech'
        return result
    # Deliberate addressing is required; background conversation never grants
    # permission to answer. No fuzzy guesses such as "rub it" -> "robot".
    if re.fullmatch(r'\s*(?:(?:hey|hi|okay|ok)\W+)?'+re.escape(wake_word)+r'[\s,.!?:;-]*', text, re.I):
        result.update(reason='wake word; awaiting question', wake_only=True)
        return result
    if addressed and len(re.findall(r'\w+', text)) >= 2:
        result.update(accepted=True, reason='question after wake word', prompt=text)
        return result
    match = re.search(r'(?:^|[.!?]\s*)\s*(?:(?:hey|hi|okay|ok)\W+)?' + re.escape(wake_word) +
                      r'\b[\s,.!?:;-]*(.+)$', text, re.I)
    if not match or len(re.findall(r'\w+', match[1])) < 2:
        result['reason'] = 'no addressed request'
        return result
    result.update(accepted=True, reason='addressed request', prompt=match[1].strip())
    return result


def run(args):
    os.umask(0o077)
    model = recognizer()
    companion = companion_module()
    config = companion.settings()
    history = [system_message(companion, microphone=True)]
    stop = False
    def request_stop(*_):
        nonlocal stop
        stop = True
        print('Stopping after the current bounded hardware operation restores RAM.', flush=True)
    previous = {s: signal.signal(s, request_stop) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with bridge_lock(), httpx.Client(timeout=httpx.Timeout(180, connect=10), trust_env=False) as client:
            if config['model'] not in companion.model_ids(client, config):
                raise RuntimeError('The configured AI model is unavailable')
            with Console(selected_port(args.port)) as console:
                root = console.folder
                print('Robot microphone enabled for this session. No Mac microphone is used.', flush=True)
                print('Say "Robot, ..." during LISTENING. Listening pauses for AI replies. '
                      'Ctrl-C stops cleanly.', flush=True)
                print('Factory chatter is not yet suppressed by this prototype.', flush=True)
                count = replies = 0
                state = {'window': 0, 'status': 'ready', 'robot_microphone': True}
                state_path = ROOT / 'run/voice-status.json'
                def save():
                    state['updated_at'] = datetime.now(timezone.utc).isoformat()
                    state_path.write_text(json.dumps(state, indent=2) + '\n')
                save()
                while not stop and (not args.windows or count < args.windows):
                    count += 1
                    folder = root / f'window-{count:04d}'
                    folder.mkdir(mode=0o700)
                    console.folder = folder
                    state = {'window': count, 'status': 'preparing', 'robot_microphone': True}
                    def changed(status):
                        state['status'] = status
                        save()
                    save()
                    from live_listen import listen
                    heard = listen(console, model, recognize, args.wake_word,
                                   args.stream_seconds, lambda: stop, changed)
                    if stop:
                        break
                    if heard is not None and heard['accepted']:
                        print('Heard: ' + heard['transcript'], flush=True)
                        state.update(status='answering', transcript=heard['transcript'])
                        save()
                        report = turn(companion, client, config, history, heard['prompt'],
                                      console=console, microphone=True)
                        state['answer'] = report['answer']
                        replies += 1
                    else:
                        print('Listen interval complete; refreshing the temporary stream.', flush=True)
                    state.update(status='between windows', replies=replies)
                    save()
                    # Each new reply is a dedicated file on the robot. Bound a
                    # session until safe, target-specific file cleanup is added.
                    if replies >= 20:
                        print('Session limit: 20 saved replies. Stopping before more device files accumulate.', flush=True)
                        break
                state.update(status='stopped', replies=replies)
                save()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port')
    p.add_argument('--windows', type=int, default=0, help='Stop after N listen intervals; 0 repeats')
    p.add_argument('--stream-seconds', type=int, default=120, help='Refresh the stream after 1–120 seconds')
    p.add_argument('--wake-word', default='robot')
    args = p.parse_args()
    if args.windows < 0 or not 1 <= args.stream_seconds <= 120 or not re.fullmatch('[a-zA-Z]{2,16}', args.wake_word):
        p.error('Use nonnegative windows and a single alphabetic wake word')
    try:
        run(args)
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print('Voice loop stopped: ' + str(error), flush=True)
        (ROOT / 'run/voice-status.json').write_text(json.dumps({'status': 'error', 'error': str(error)}) + '\n')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
