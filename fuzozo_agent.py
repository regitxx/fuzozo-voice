#!/usr/bin/env python3
"""Typed chat through a configured compatible AI server and Fuzozo speaker.
For experimental robot microphone input use fuzozo_voice.py.
AI-controlled movement is not implemented.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sys
import time

import httpx
from serial.tools import list_ports

from fuzozo_console import Console, ROOT
from fuzozo_speak import prepare_wav
from ram_wav_transfer import elf_text, transfer
from speech_clip import render

def companion_module():
    import ai_backend
    return ai_backend


def system_message(companion, microphone=False):
    return {'role': 'system', 'content': companion.SYSTEM +
            ' You are now speaking through Fuzozo in the same robotics lab.' +
            (' Input is transcribed from the robot microphone; it may contain recognition errors.'
             if microphone else ' Input comes from typed text, not the robot microphone.') +
            ' Factory animations run independently; you cannot control them.'
            ' For this slow USB prototype, answer in one sentence of at most'
            ' seven words. Use plain spoken English and no markup.'}


def short_reply(companion, client, config, messages):
    answer = companion.reply(client, config, messages)
    if len(answer.split()) > 7 or len(answer) > 100:
        answer = companion.reply(client, config, messages + [
            {'role': 'assistant', 'content': answer},
            {'role': 'user', 'content': 'Restate that answer in at most seven short words.'}])
    if not answer.strip() or len(answer.split()) > 7 or len(answer) > 100:
        raise ValueError('Model reply exceeds the short spoken-answer limit; nothing was sent to the robot')
    return answer


def selected_port(explicit):
    if explicit:
        return explicit
    ports = [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x1a86, 0x7523)]
    if len(ports) != 1:
        raise ValueError('Connect Fuzozo or pass its exact --port; expected one CH340 candidate')
    return ports[0]  # Console still verifies the physical robot MAC.


@contextmanager
def bridge_lock():
    (ROOT / 'run').mkdir(exist_ok=True)
    with (ROOT / 'run/ai-bridge.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A Fuzozo AI bridge is already running') from None
        yield


def turn(companion, client, config, history, prompt, port=None, prepare_only=False,
         console=None, microphone=False):
    if not 0 < len(prompt.strip()) <= 2000:
        raise ValueError('Use a question of 1–2000 characters')
    start = time.monotonic()
    candidate = history + [{'role': 'user', 'content': prompt.strip()}]
    answer = short_reply(companion, client, config, candidate)
    model_seconds = time.monotonic() - start
    print('Companion: ' + answer, flush=True)
    wav = prepare_wav(render(answer)[0], peak_target=16000)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = ROOT / 'outputs' / ('ai-' + stamp)
    folder.mkdir(parents=True, mode=0o700)
    path = folder / 'reply.wav'
    path.write_bytes(wav)
    report = {'prompt': prompt.strip(), 'answer': answer, 'model': config['model'],
              'model_seconds': round(model_seconds, 2), 'host_wav': str(path),
              'robot_microphone_used': microphone, 'prepare_only': prepare_only}
    report_path = folder / 'turn.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    if not prepare_only:
        code = elf_text(ROOT / 'run/ram-wav-helper.o')
        from contextlib import nullcontext
        with (nullcontext(console) if console is not None else Console(selected_port(port))) as active_console:
            report['captures'] = str(active_console.folder)
            report['transfer'] = transfer(active_console, wav, code)
            playback = report['transfer']['playback_log']
            if not all(playback.get(k) for k in ('requested_path_logged', 'play_start_logged', 'play_stop_logged')):
                report_path.write_text(json.dumps(report, indent=2) + '\n')
                raise RuntimeError('Upload completed but expected playback evidence is incomplete')
    report['total_seconds'] = round(time.monotonic() - start, 2)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(report_path), 'total_seconds': report['total_seconds'],
                      'playback_completed': not prepare_only}), flush=True)
    # Keep six complete conversational turns, and commit only after success.
    history[:] = history[:1] + (candidate[1:] + [{'role': 'assistant', 'content': answer}])[-12:]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt', help='One typed question; omit for interactive chat')
    parser.add_argument('--port', help='Exact CH340 port, otherwise identify the only candidate')
    parser.add_argument('--prepare-only', action='store_true', help='Generate reply/audio without touching Fuzozo')
    parser.add_argument('--doctor', action='store_true', help='Check the configured AI model without robot commands')
    args = parser.parse_args()
    os.umask(0o077)
    companion = companion_module()
    config = companion.settings()
    try:
        with bridge_lock(), httpx.Client(timeout=httpx.Timeout(180, connect=10), trust_env=False) as client:
            if config['model'] not in companion.model_ids(client, config):
                raise RuntimeError('The configured AI model is unavailable')
            if args.doctor:
                print(json.dumps({'studio_reachable': True, 'model': config['model'],
                                  'input': 'typed text', 'robot_microphone': 'available in fuzozo_voice.py'}))
                return 0
            history = [system_message(companion)]
            if args.prompt is not None:
                turn(companion, client, config, history, args.prompt, args.port, args.prepare_only)
                return 0
            print('Fuzozo AI: keep sound on and the robot awake. Type /quit to stop.', flush=True)
            while True:
                prompt = input('You: ').strip()
                if prompt.lower() in ('/quit', 'quit', 'exit'):
                    return 0
                if prompt:
                    turn(companion, client, config, history, prompt, args.port, args.prepare_only)
    except (EOFError, KeyboardInterrupt):
        print('\nStopped.')
        return 0
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print('Fuzozo AI stopped: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
