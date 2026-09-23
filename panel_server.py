#!/usr/bin/env python3
"""Loopback-only Fuzozo control panel, serialized hardware worker and local AI."""
import argparse
from collections import deque
from datetime import datetime, timezone
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import threading
import time
from urllib.parse import urlsplit
import uuid

import httpx
from serial.tools import list_ports

from fuzozo_agent import companion_module, selected_port, bridge_lock
from fuzozo_console import Console, ROOT
from panel_audio import prepare
from ram_wav_transfer import transfer, elf_text
from volume_control import volume

STATIC = ROOT/'panel'
SETTINGS_PATH = ROOT/'run/panel-settings.json'
DEFAULTS = {'speech_level': 67, 'agent_name': 'Lab companion', 'instructions': '',
            'reply_style': 'short', 'wake_word': 'robot'}


def now():
    return datetime.now(timezone.utc).isoformat()


def friendly_error(error):
    text = str(error)
    if 'matching serial MAC' in text:
        return 'Fuzozo isn’t responding. Wake it, then check the connection.'
    if 'CH340' in text or 'Connect Fuzozo' in text:
        return 'Connect Fuzozo’s USB cable, then check the connection.'
    if 'already running' in text or 'USB is in use' in text:
        return 'Another lab tool is using Fuzozo. Stop it before using the panel.'
    if 'Recovery stopped' in text or 'scratch' in text or 'callback' in text:
        return 'A previous robot session needs attention. Check connection; if that fails, restart Fuzozo normally.'
    if 'acknowledgement missing' in text or 'debug response' in text:
        return 'The audio connection was interrupted. Check connection before trying again.'
    if isinstance(error, httpx.HTTPError):
        return 'The AI service is unavailable. Check the configured AI endpoint and network.'
    return text


class Controller:
    def __init__(self, settings_path=SETTINGS_PATH):
        self.lock = threading.RLock()
        self.settings_path = settings_path
        self.settings = dict(DEFAULTS)
        if settings_path.exists():
            self.settings.update(self.validate_settings(json.loads(settings_path.read_text())))
        self.jobs = {}
        self.order = deque(maxlen=80)
        self.work = queue.Queue(maxsize=20)
        self.events = deque(maxlen=60)
        self.messages = deque(maxlen=40)
        self.history = []
        self.device = {'verified': False, 'port': None, 'volume': None, 'muted': None, 'last_seen': None}
        self.services = {'studio': 'unchecked', 'voice': 'unchecked', 'model': None}
        self.voice_enabled = False
        self.voice_state = 'off'
        self.active = None
        self.phase = 'idle'
        self.notice = 'Connect Fuzozo by USB and check the connection.'
        self.interrupt = threading.Event()
        self.cancel = threading.Event()
        self.shutdown = threading.Event()
        self.csrf = secrets.token_urlsafe(32)
        self.thread = None
        self.companion = companion_module()
        self.config = self.companion.settings()
        self.services['model'] = self.config['model']
        self.stt = None
        self.uploaded = []
        self.stop_epoch = 0

    @staticmethod
    def validate_settings(values):
        if not isinstance(values, dict) or set(values)-set(DEFAULTS):
            raise ValueError('Unknown panel setting')
        result = dict(values)
        if 'speech_level' in result and (type(result['speech_level']) is not int or not 0 <= result['speech_level'] <= 100):
            raise ValueError('Speech level must be 0–100')
        for key, limit in [('agent_name', 50), ('instructions', 1200)]:
            if key in result and (not isinstance(result[key], str) or len(result[key]) > limit):
                raise ValueError('Invalid '+key)
        if 'wake_word' in result and (not isinstance(result['wake_word'], str) or not re.fullmatch('[a-zA-Z]{2,16}', result['wake_word'])):
            raise ValueError('Use a single alphabetic wake word')
        if 'reply_style' in result and result['reply_style'] not in ('short', 'standard'):
            raise ValueError('Unknown reply style')
        return result

    def start(self):
        self.thread = threading.Thread(target=self.worker, name='fuzozo-hardware', daemon=True)
        self.thread.start()

    def event(self, text, kind='info'):
        with self.lock:
            self.events.append({'at': now(), 'text': text, 'kind': kind})

    def progress(self, phase, message):
        with self.lock:
            self.phase, self.notice = phase, message
            if self.active:
                self.jobs[self.active].update(phase=phase, message=message)

    def snapshot(self):
        candidates = [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x1a86, 0x7523)]
        with self.lock:
            return json.loads(json.dumps({'csrf': self.csrf, 'settings': self.settings,
                'device': dict(self.device, adapter_present=self.device['port'] in candidates,
                               candidates=candidates), 'services': self.services,
                'voice': {'enabled': self.voice_enabled, 'state': self.voice_state},
                'phase': self.phase, 'notice': self.notice, 'active': self.active,
                'jobs': [{k:v for k,v in self.jobs[j].items() if k not in ('audio_path', 'epoch')}
                         for j in self.order if j in self.jobs][-30:],
                'events': list(self.events), 'messages': list(self.messages), 'time': now()}))

    def update_settings(self, values):
        values = self.validate_settings(values)
        with self.lock:
            self.settings.update(values)
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.settings_path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.settings, indent=2)+'\n')
            temp.replace(self.settings_path)
        self.event('Companion settings saved.')

    def enqueue(self, kind, payload):
        allowed = {'connect', 'speak', 'preview', 'ask', 'volume', 'replay', 'clear_chat'}
        if kind not in allowed or not isinstance(payload, dict):
            raise ValueError('Unknown action')
        if kind in ('speak', 'preview', 'ask'):
            text = payload.get('text')
            limit = 1000 if kind == 'ask' else 600
            if not isinstance(text, str) or not 0 < len(text.strip()) <= limit:
                raise ValueError(f'Enter between 1 and {limit} characters')
        if kind == 'ask' and type(payload.get('speak', True)) is not bool:
            raise ValueError('Speak replies must be true or false')
        if kind == 'volume':
            if set(payload)-{'level', 'muted'} or not payload:
                raise ValueError('Choose volume or mute')
            if 'level' in payload and (type(payload['level']) is not int or not 0 <= payload['level'] <= 100):
                raise ValueError('Volume must be 0–100')
            if 'muted' in payload and type(payload['muted']) is not bool:
                raise ValueError('Muted must be true or false')
        if kind == 'replay':
            original = self.jobs.get(payload.get('job_id'))
            if not original or not original.get('audio_path'):
                raise ValueError('That speech preview is unavailable')
        with self.lock:
            if self.work.full():
                raise ValueError('The command queue is full; wait or press Stop all')
            identity = uuid.uuid4().hex
            self.jobs[identity] = {'id': identity, 'kind': kind, 'status': 'queued',
                                   'phase': 'queued', 'message': 'Queued', 'created': now(), 'epoch': self.stop_epoch}
            self.order.append(identity)
            self.work.put_nowait((identity, kind, dict(payload)))
            self.interrupt.set()
        return identity

    def set_voice(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Voice mode must be true or false')
        with self.lock:
            self.voice_enabled = enabled
            if not enabled:
                self.interrupt.set()
            self.voice_state = 'starting' if enabled else ('stopping' if self.phase == 'listening' else 'off')
        self.event('Voice mode requested.' if enabled else 'Voice mode stopping.')

    def stop(self):
        with self.lock:
            self.stop_epoch += 1
            self.voice_enabled = False
            self.voice_state = 'stopping' if self.phase != 'idle' else 'off'
            self.interrupt.set()
            self.cancel.set()
            while True:
                try:
                    identity, _, _ = self.work.get_nowait()
                    self.jobs[identity].update(status='cancelled', message='Cancelled before starting')
                    self.work.task_done()
                except queue.Empty:
                    break
        self.event('Stop requested. Any active hardware operation will finish cleanup first.')

    def remember_device(self, console, sound=None):
        with self.lock:
            self.device.update(verified=True, port=console.serial.port, last_seen=now())
            if sound:
                self.device.update(volume=sound['volume'], muted=sound['muted'])

    def check_services(self):
        with httpx.Client(timeout=httpx.Timeout(12, connect=3), trust_env=False) as client:
            try:
                ids = self.companion.model_ids(client, self.config)
                self.services['studio'] = 'ready' if self.config['model'] in ids else 'model missing'
            except (OSError, ValueError, httpx.HTTPError):
                self.services['studio'] = 'unreachable'
        from speech_clip import available
        self.services['voice'] = 'configured' if available() else 'unconfigured'

    def ensure_voice(self):
        from speech_clip import available
        if not available():
            raise ValueError('Configure TTS in config.json; see docs/HOSTED_AI.md')

    def check_cancel(self):
        if self.cancel.is_set() or self.shutdown.is_set():
            raise InterruptedError('Stopped before the next operation')

    def play_audio(self, identity, audio):
        import audioop
        import io
        import wave
        from panel_audio import wav_bytes
        self.check_cancel()
        if self.settings['speech_level'] == 0:
            return {'spoken': False, 'note': 'Speech level is zero. Raise it to speak.'}
        pcm_parts = []
        for part in audio['parts']:
            with wave.open(io.BytesIO(part), 'rb') as w:
                pcm_parts.append(w.readframes(w.getnframes()))
        peak = max((audioop.max(part, 2) for part in pcm_parts), default=0)
        if not peak:
            return {'spoken': False, 'note': 'This preview is silent. Generate it again with speech level above zero.'}
        gain = round(24000*self.settings['speech_level']/100)/peak
        parts = [wav_bytes(audioop.mul(part, 2, gain)) for part in pcm_parts]
        if len(self.uploaded) >= 20:
            raise ValueError('Temporary-file cleanup needs attention before more speech is uploaded')
        with Console(selected_port(None)) as c:
            sound = volume(c)
            self.remember_device(c, sound)
            if sound['muted'] or sound['volume'] == 0:
                return {'spoken': False, 'note': 'Robot is muted. Unmute it, then use Replay.'}
            code = elf_text(ROOT/'run/ram-wav-helper.o')
            transfers = []
            for index, part in enumerate(parts):
                self.check_cancel()
                if len(self.uploaded) >= 20:
                    raise ValueError('Temporary-file cleanup needs attention before more speech is uploaded')
                self.progress('speaking', f'Sending speech · section {index+1}/{len(parts)}')
                result = transfer(c, part, code)
                transfers.append({'verified': result['file_verified'], 'playback': result['playback_log']})
                self.uploaded.append(result['robot_path'])
                # Delete only the exact, newly created /labvoice file after its
                # verified playback stops. Factory assets are never candidates.
                path = result['robot_path']
                if not re.fullmatch(r'/labvoice/voice_[0-9a-f]{16}\.wav', path):
                    raise ValueError('Unexpected generated speech path')
                response = c.exchange_matching('cpu1 del '+path, 3, 'delete-panel-speech',
                                               re.escape(('del '+path+', ret ').encode())+rb'-?\d+\r?\n')
                match = re.search(re.escape(('del '+path+', ret ').encode())+rb'(-?\d+)', response)
                if match and int(match[1]) == 0:
                    self.uploaded.remove(path)
                else:
                    self.event('A temporary reply file was retained on the robot.', 'warning')
            self.remember_device(c)
        return {'spoken': True, 'sections': len(transfers), 'checks': transfers}

    def generate_audio(self, identity, text):
        self.check_cancel()
        self.progress('synthesizing', 'Preparing speech')
        self.ensure_voice()
        folder = ROOT/'outputs/panel'/identity
        audio = prepare(text, self.settings['speech_level'], folder, self.progress, self.cancel.is_set)
        with self.lock:
            self.jobs[identity].update(audio_path=audio['preview'], audio_url='/api/audio/'+identity,
                                       seconds=round(audio['seconds'], 2), text=text)
        return audio

    def answer(self, identity, text, speak, microphone=False):
        self.check_cancel()
        with self.lock:
            self.messages.append({'id': uuid.uuid4().hex, 'role': 'user', 'text': text,
                                  'source': 'voice' if microphone else 'typed', 'at': now()})
        self.progress('thinking', 'Your AI companion is thinking')
        word_limit = 7 if self.settings['reply_style'] == 'short' else 24
        system = self.companion.SYSTEM + (
            ' You are speaking through Fuzozo. Factory animations run independently.'
            ' Input is '+('transcribed from its real microphone.' if microphone else 'typed in its web panel.')+
            f' Answer in plain spoken English, at most {word_limit} words.'+
            ' Do not claim control over motors or animations. '+self.settings['instructions'])
        candidate = [{'role': 'system', 'content': system}]+self.history[-12:]+[{'role': 'user', 'content': text}]
        with httpx.Client(timeout=httpx.Timeout(180, connect=10), trust_env=False) as client:
            answer = self.companion.reply(client, self.config, candidate)
        if len(answer) > 600:
            raise ValueError('The AI answer exceeded the speech limit; choose Short replies and retry')
        self.check_cancel()
        with self.lock:
            self.services['studio'] = 'ready'
            self.messages.append({'id': uuid.uuid4().hex, 'role': 'assistant', 'text': answer,
                                  'job_id': identity, 'at': now()})
            self.jobs[identity]['answer'] = answer
            self.history = (self.history+[{'role': 'user', 'content': text}, {'role': 'assistant', 'content': answer}])[-12:]
        if speak:
            return dict(self.play_audio(identity, self.generate_audio(identity, answer)), answer=answer)
        return {'answer': answer, 'spoken': False, 'note': 'Text-only reply'}

    def execute(self, identity, kind, payload):
        if kind == 'connect':
            self.progress('connecting', 'Checking Fuzozo and its audio controls')
            self.check_services()
            with Console(selected_port(None)) as c:
                from bkreg_probe import DebugReader
                from mic_stream import CODE, SIZE
                from ram_wav_transfer import SCRATCH, SCRATCH_SIZE
                r = DebugReader(c)
                if r.read_ram(CODE, SIZE//4) != bytes(SIZE) or r.read_ram(SCRATCH, SCRATCH_SIZE//4) != bytes(SCRATCH_SIZE):
                    from recover_mic_stream import recover
                    self.progress('connecting', 'Restoring the interrupted microphone stream')
                    recover(c)
                sound = volume(c)
                self.remember_device(c, sound)
            return {'connected': True, **sound}
        if kind == 'volume':
            self.progress('volume', 'Applying the robot’s sound setting')
            with Console(selected_port(None)) as c:
                sound = volume(c, payload.get('level'), payload.get('muted'))
                self.remember_device(c, sound)
            return sound
        if kind == 'clear_chat':
            with self.lock:
                self.history.clear(); self.messages.clear()
            return {'cleared': True}
        if kind == 'ask':
            return self.answer(identity, payload['text'].strip(), payload.get('speak', True))
        if kind == 'replay':
            import wave
            from panel_audio import segment_pcm, wav_bytes
            original = self.jobs[payload['job_id']]
            with wave.open(original['audio_path'], 'rb') as w:
                pcm = w.readframes(w.getnframes())
            return self.play_audio(identity, {'parts': [wav_bytes(p) for p in segment_pcm(pcm)]})
        audio = self.generate_audio(identity, payload['text'].strip())
        return self.play_audio(identity, audio) if kind == 'speak' else {'prepared': True, 'spoken': False}

    def listen_once(self):
        from fuzozo_voice import recognizer, recognize
        from live_listen import listen
        self.progress('preparing', 'Starting Fuzozo’s microphone stream')
        if self.stt is None:
            self.stt = recognizer()
        with Console(selected_port(None)) as c:
            self.remember_device(c)
            def changed(phase):
                with self.lock:
                    self.voice_state = phase
                self.progress(phase, 'Listening — say “'+self.settings['wake_word'].capitalize()+'”, then your question.'
                              if phase == 'listening' else 'Recognizing your question')
            result = listen(c, self.stt, recognize, self.settings['wake_word'], 120,
                            lambda: self.interrupt.is_set() or self.shutdown.is_set(), changed)
        if result and not self.interrupt.is_set():
            identity = uuid.uuid4().hex
            with self.lock:
                self.jobs[identity] = {'id': identity, 'kind': 'voice', 'status': 'running', 'created': now()}
                self.order.append(identity); self.active = identity; self.voice_state = 'replying'
            try:
                output = self.answer(identity, result['prompt'], True, microphone=True)
                self.jobs[identity].update(status='done', result=output, message=output.get('note', 'Reply complete'))
            except Exception as error:
                self.jobs[identity].update(status='error', message=str(error))
                raise
            finally:
                self.active = None

    def worker(self):
        while not self.shutdown.is_set():
            try:
                identity, kind, payload = self.work.get(timeout=.2)
            except queue.Empty:
                with self.lock:
                    if not self.voice_enabled or not self.work.empty():
                        continue
                    self.interrupt.clear(); self.cancel.clear()
                try:
                    with bridge_lock():
                        self.listen_once()
                except Exception as error:
                    with self.lock:
                        self.voice_enabled = False; self.voice_state = 'error'
                        self.device['verified'] = False
                    self.event('Voice mode stopped: '+friendly_error(error), 'error')
                    self.progress('error', friendly_error(error))
                finally:
                    if self.voice_state != 'error':
                        with self.lock:
                            self.voice_state = 'starting' if self.voice_enabled else 'off'
                        self.progress('idle', 'Ready for your next request')
                continue
            started = time.monotonic()
            with self.lock:
                if self.jobs[identity]['epoch'] != self.stop_epoch:
                    self.jobs[identity].update(status='cancelled', message='Cancelled before starting')
                    self.work.task_done()
                    continue
                self.active = identity
                self.jobs[identity]['status'] = 'running'
                self.cancel.clear(); self.interrupt.clear()
            try:
                with bridge_lock():
                    result = self.execute(identity, kind, payload)
                with self.lock:
                    self.jobs[identity].update(status='done', result=result, message=result.get('note', 'Complete'),
                                               elapsed=round(time.monotonic()-started, 1))
                self.event({'connect': 'Connection checked.', 'volume': 'Robot sound setting verified.',
                            'ask': 'AI reply ready.', 'speak': 'Speech request complete.', 'preview': 'Preview ready.',
                            'replay': 'Replay complete.', 'clear_chat': 'Conversation cleared.'}[kind])
            except InterruptedError as error:
                self.jobs[identity].update(status='cancelled', message=str(error))
            except Exception as error:
                self.jobs[identity].update(status='error', message=friendly_error(error))
                if kind in ('connect', 'volume', 'speak', 'replay') or kind == 'ask' and payload.get('speak', True):
                    with self.lock:
                        self.device['verified'] = False
                self.event(friendly_error(error), 'error')
            finally:
                with self.lock:
                    self.active = None
                    self.phase = 'error' if self.jobs[identity]['status'] == 'error' else 'idle'
                    self.notice = self.jobs[identity]['message']
                    if not self.voice_enabled:
                        self.voice_state = 'off'
                self.work.task_done()


def handler_for(controller, port):
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Private text requests never go into HTTP access logs.

        def send(self, status, data, content_type='application/json; charset=utf-8'):
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(data)

        def valid_host(self):
            return self.headers.get('Host') in allowed_hosts

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {'error': 'Local panel host required'})
            path = urlsplit(self.path).path
            if path == '/api/status':
                return self.send(200, controller.snapshot())
            if path == '/api/health':
                return self.send(200, {'service': 'fuzozo-panel-v1'})
            if re.fullmatch(r'/api/audio/[0-9a-f]{32}', path):
                job = controller.jobs.get(path.rsplit('/', 1)[1], {})
                if job.get('audio_path'):
                    return self.send(200, Path(job['audio_path']).read_bytes(), 'audio/wav')
                return self.send(404, {'error': 'Audio not found'})
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/favicon.svg': ('favicon.svg', 'image/svg+xml'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path not in assets:
                return self.send(404, {'error': 'Not found'})
            name, mime = assets[path]
            self.send(200, (STATIC/name).read_bytes(), mime)

        def do_POST(self):
            origin = self.headers.get('Origin')
            if not self.valid_host() or origin and origin not in {'http://'+h for h in allowed_hosts}:
                return self.send(403, {'error': 'Local same-origin request required'})
            if not secrets.compare_digest(self.headers.get('X-Fuzozo-Token', ''), controller.csrf):
                return self.send(403, {'error': 'Reload the panel before sending commands'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8192 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Expected a small JSON request')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected an object')
                path = urlsplit(self.path).path
                if path == '/api/settings':
                    controller.update_settings(payload); return self.send(200, {'ok': True})
                if path == '/api/voice':
                    controller.set_voice(payload.get('enabled')); return self.send(200, {'ok': True})
                if path == '/api/stop':
                    controller.stop(); return self.send(200, {'ok': True})
                if path == '/api/action':
                    identity = controller.enqueue(payload.get('kind'), payload.get('payload', {}))
                    return self.send(202, {'job_id': identity})
                return self.send(404, {'error': 'Unknown endpoint'})
            except (ValueError, TypeError, KeyError) as error:
                self.send(400, {'error': str(error)})
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8787)
    args = p.parse_args()
    if not 1024 <= args.port <= 65535:
        p.error('Choose an unprivileged local port')
    os.umask(0o077)
    (ROOT/'run').mkdir(exist_ok=True)
    lock = (ROOT/'run/panel-server.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    controller = Controller()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(controller, args.port))
    controller.start()
    controller.enqueue('connect', {})
    def stop(*_):
        controller.stop(); controller.shutdown.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    print(f'Fuzozo panel ready at http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        controller.stop(); controller.shutdown.set()
        controller.thread.join(timeout=200)
        server.server_close(); lock.close()


if __name__ == '__main__':
    main()
