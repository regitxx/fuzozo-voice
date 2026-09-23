#!/usr/bin/env python3
"""Read-only Beken debug probe for the already identified Fuzozo console.

Only link-check (0) and aligned reads (3) within the mapped application image
are implemented. This is not a file uploader. Never infer installed firmware
addresses from the downloaded, different firmware version without comparison.
"""
import argparse
import json
import struct
import time
from pathlib import Path

from fuzozo_console import Console

IMAGE_BASE = 0x02010000
IMAGE_END = IMAGE_BASE + 3081136


def find_event(data, prefix, length):
    """Find the complete, exact-length expected event among asynchronous logs."""
    marker = b'\x04\x0e' + bytes([length]) + prefix
    start = data.find(marker)
    while start >= 0:
        end = start + 3 + length
        if len(data) >= end:
            return bytes(data[start:end])
        start = data.find(marker, start + 1)
    return None


class DebugReader:
    def __init__(self, console):
        self.console = console
        self.session_invalidated = False

    def exchange(self, packet, prefix, length, label):
        try:
            return self._exchange(packet, prefix, length, label)
        except (OSError, TimeoutError):
            self.session_invalidated = True
            raise

    def _exchange(self, packet, prefix, length, label):
        if self.session_invalidated or getattr(self.console, 'session_invalidated', False):
            raise IOError('Debug session invalidated; reopen and verify the device')
        c = self.console
        c.serial.reset_input_buffer()
        if c.serial.write(packet) != len(packet):
            raise IOError('Short debug packet write')
        captured = bytearray()
        deadline = time.monotonic() + 2
        event = None
        while time.monotonic() < deadline:
            captured.extend(c.serial.read(max(1, min(c.serial.in_waiting, 8192))))
            if len(captured) > 100_000:
                raise IOError('Debug response exceeded capture limit')
            event = find_event(captured, prefix, length)
            if event is not None:
                break
        c.sequence += 1
        (c.folder / f'{c.sequence:02}-{label}.bin').write_bytes(captured)
        if any(marker in captured.lower() for marker in (
                b'prepare to deepsleep', b'save config && reboot',
                b'reason - software reboot', b'start user app thread',
                b'memfault', b'hardfault', b'memory management fault')):
            self.session_invalidated = True
            raise IOError('Device sleep/reboot detected; all RAM addresses invalidated')
        if event is None:
            self.session_invalidated = True
            raise TimeoutError('No matching debug response; no further packets sent')
        return event

    def link(self):
        return self.exchange(bytes.fromhex('01e0fc0100'), b'\x00', 1, 'bkreg-link')

    def read_image(self, address, words=1):
        if (type(address) is not int or type(words) is not int or address % 4
                or not 1 <= words <= 64 or address < IMAGE_BASE
                or address + words * 4 > IMAGE_END):
            raise ValueError('Use 1–64 aligned words inside the application image')
        return self._read_words(address, words)

    def read_ram(self, address, words=1):
        # Main SRAM only, ending below the observed initial stack pointer.
        # No peripheral register, OTP, or write operation is exposed.
        if (type(address) is not int or type(words) is not int or address % 4
                or not 1 <= words <= 64 or address < 0x28000000
                or address + words * 4 > 0x2805f800):
            raise ValueError('Use 1–64 aligned words inside main SRAM')
        return self._read_words(address, words)

    def _read_words(self, address, words):
        output = bytearray()
        for offset in range(0, words * 4, 4):
            encoded = struct.pack('<I', address + offset)
            event = self.exchange(bytes.fromhex('01e0fc0503') + encoded,
                                  bytes.fromhex('01e0fc03') + encoded, 12,
                                  f'bkreg-read-{address + offset:08x}')
            output.extend(event[-4:])
        return bytes(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/cu.usbserial-210')
    parser.add_argument('--address', type=lambda x: int(x, 0), default=IMAGE_BASE)
    parser.add_argument('--words', type=int, default=4)
    args = parser.parse_args()
    with Console(args.port) as c:
        reader = DebugReader(c)
        reply = reader.link()
        print(json.dumps({'link_verified': True, 'reply': reply.hex(),
                          'captures': str(c.folder)}), flush=True)
        data = reader.read_image(args.address, args.words)
        path = c.folder / f'image-{args.address:08x}.bin'
        path.write_bytes(data)
        print(json.dumps({'image_read_verified': True, 'address': hex(args.address),
                          'bytes': len(data), 'output': str(path)}))


if __name__ == '__main__':
    main()
