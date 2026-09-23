#!/usr/bin/env python3
"""Bounded Fuzozo console access at the verified 460800 baud.

Captures are private because factory logs can include credentials. Every
connection checks the enrolled MAC and reported firmware before proceeding.
No factory reset, firmware update or arbitrary shell command is exposed.
"""
import argparse
import fcntl
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import termios
import time

import serial
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parent
RECORDS = ROOT / 'run/device.json'


class Console:
    def __init__(self, port, records=RECORDS):
        os.umask(0o077)
        target = json.loads(Path(records).read_text())
        if target.get('model') != 'FZ1012' or target.get('firmware') != '1.0.42':
            raise ValueError('Only the FZ1012 1.0.42 profile is supported; run setup_device.py')
        self.mac = re.sub('[^0-9a-f]', '', target['mac'].lower())
        if len(self.mac) != 12:
            raise ValueError('Invalid target MAC')
        matches = [p for p in list_ports.comports() if p.device == port
                   and (p.vid, p.pid) == (0x1a86, 0x7523)]
        if len(matches) != 1:
            raise ValueError('Expected CH340 bridge at the explicit port')
        self.folder = ROOT / 'run' / ('console-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        self.folder.mkdir(mode=0o700)
        self.sequence = 0
        self.session_invalidated = False
        self.lock_handle = None
        self.serial = serial.Serial(port=None, baudrate=460800, timeout=.1, write_timeout=2)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port

    def __enter__(self):
        try:
            self.lock_handle = (ROOT / 'run' / 'console.lock').open('a')
            try:
                fcntl.flock(self.lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Fuzozo USB is in use by another lab command; stop that command first') from None
            self.serial.open()
            self.capture(.5)
            for _ in range(2):
                self.serial.write(b'\r\n')
                response = self.exchange('macaddr get', 3, 'identity')
                normalized = re.sub('[^a-z0-9]', '', response.decode('ascii', 'ignore').lower())
                if self.mac in normalized:
                    version = self.exchange('devget version', 2, 'firmware-version')
                    match = re.search(rb'USER_SW_VER:([\d.]+)', version)
                    if not match or match[1] != b'1.0.42':
                        raise ValueError('Unsupported or unconfirmed firmware; expected 1.0.42')
                    return self
            raise ValueError('No matching serial MAC response; stopping')
        except BaseException:
            self.serial.close()
            if self.lock_handle:
                self.lock_handle.close()
                self.lock_handle = None
            raise

    def __exit__(self, *_):
        self.serial.close()
        if self.lock_handle:
            self.lock_handle.close()
            self.lock_handle = None

    def capture(self, seconds):
        if not 0 < seconds <= 45:
            raise ValueError('Capture duration must be 0–45 seconds')
        data = bytearray()
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            data.extend(self.serial.read(8192))
            if len(data) > 2_000_000:
                raise ValueError('Capture exceeded bounded size')
        return bytes(data)

    def exchange(self, command, seconds, label):
        if self.session_invalidated:
            raise IOError('Device session invalidated; reopen and verify identity')
        if '\r' in command or '\n' in command or len(command.encode()) >= 200:
            raise ValueError('Invalid command framing')
        # Idle factory logs can accumulate between commands; exclude them from
        # this response so old events cannot masquerade as new command results.
        self.serial.reset_input_buffer()
        self.serial.write(command.encode() + b'\r\n')
        data = self.capture(seconds)
        self.sequence += 1
        (self.folder / f'{self.sequence:02}-{label}.bin').write_bytes(data)
        if any(marker in data.lower() for marker in (
                b'prepare to deepsleep', b'save config && reboot',
                b'init:w(0):reason -', b'start user app thread',
                b'memfault', b'hardfault', b'memory management fault')):
            self.session_invalidated = True
            raise IOError('Device sleep, restart, or firmware fault detected; capture saved')
        return data

    def exchange_matching(self, command, seconds, label, pattern):
        """Read until an explicit reply marker, retaining the same fault checks."""
        if self.session_invalidated:
            raise IOError('Device session invalidated; reopen and verify identity')
        if '\r' in command or '\n' in command or len(command.encode()) >= 200:
            raise ValueError('Invalid command framing')
        self.serial.reset_input_buffer()
        self.serial.write(command.encode() + b'\r\n')
        deadline = time.monotonic() + seconds
        data = bytearray()
        try:
            while time.monotonic() < deadline:
                data.extend(self.serial.read(max(1, min(self.serial.in_waiting, 8192))))
                if len(data) > 2_000_000:
                    raise IOError('Reply exceeded capture limit')
                if any(marker in data.lower() for marker in (
                        b'prepare to deepsleep', b'save config && reboot',
                        b'init:w(0):reason -', b'start user app thread',
                        b'memfault', b'hardfault', b'memory management fault')):
                    self.session_invalidated = True
                    raise IOError('Device sleep, restart, or firmware fault detected')
                if re.search(pattern, data, re.S):
                    return bytes(data)
            raise TimeoutError('Expected console reply marker missing: ' + label)
        finally:
            self.sequence += 1
            (self.folder / f'{self.sequence:02}-{label}.bin').write_bytes(data)

    def inspect(self):
        results = {}
        for command, label in [('devget version', 'version'), ('help', 'help'),
                               ('cpu1 help', 'cpu1-help'), ('state', 'network-state')]:
            data = self.exchange(command, 2, label)
            results[label] = {'bytes': len(data)}
            if label == 'version':
                match = re.search(rb'USER_SW_VER:([\d.]+)', data)
                results[label]['version'] = match[1].decode() if match else None
            if label == 'cpu1-help':
                results[label]['app_play_wav_available'] = b'app_play_wav:' in data
        return results

    def play(self, path):
        if not re.fullmatch(r'/wav/\d+\.wav|/labvoice/[A-Za-z0-9_-]+\.wav', path):
            raise ValueError('Use an existing stock WAV or a dedicated /labvoice WAV')
        pattern = (re.escape(('aud tras prompt url ' + path).encode()) +
                   rb'.*PROMPT_TONE_PLAY_START.*PROMPT_TONE_PLAY_STOP')
        data = self.exchange_matching('cpu1 prompt_wav ' + path, 7, 'play', pattern)
        return {'play_start_logged': b'PROMPT_TONE_PLAY_START' in data,
                'play_stop_logged': b'PROMPT_TONE_PLAY_STOP' in data,
                'requested_path_logged': ('aud tras prompt url ' + path).encode() in data,
                'command': 'cpu1 prompt_wav',
                'note': 'Logs alone do not establish which sound was heard.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--records', type=Path, default=RECORDS)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('inspect')
    play = sub.add_parser('play')
    play.add_argument('path')
    args = parser.parse_args()
    try:
        with Console(args.port, args.records) as console:
            result = console.inspect() if args.action == 'inspect' else console.play(args.path)
            print(json.dumps({'target_mac_verified': True, 'result': result,
                              'private_capture_directory': str(console.folder)}, indent=2))
    except (serial.SerialException, OSError, termios.error, ValueError) as error:
        print(json.dumps({'success': False, 'error': str(error)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
