#!/usr/bin/env python3
"""Temporary 8 kHz mu-law microphone ring; no flash writes or Mac microphone."""
import argparse
import audioop
import json
import re
import struct
import time
import wave

from bkreg_probe import DebugReader
from fuzozo_console import Console, ROOT
from mic_capture import CALLBACK, CALLBACK_SIGNATURE, RECORDER_GLOBAL, read_psram
from ram_bulk_io import BulkSession, CONTEXT as BULK_CONTEXT
from ram_wav_transfer import ScopedWriter, elf_text

CODE = 0x2802f474  # Unused CLI slots 144–191; bulk helpers use slots 192–247.
SIZE = 192
CONTEXT = CODE + 160
CAPACITY = 65536


class MicRing:
    def __init__(self, console):
        self.c = console
        self.r = DebugReader(console)
        self.buffer = None
        self.borrowed = self.installed = self.started = False
        self.restored = False

    def __enter__(self):
        r = self.r
        if r.read_image(CALLBACK & ~1, 4) != CALLBACK_SIGNATURE:
            raise ValueError('Microphone callback firmware signature changed')
        if r.read_image(0x2186dec, 4).hex() != 'f8b51d465b682c4e93f90030312b47d1':
            raise ValueError('Microphone command changed')
        if r.read_ram(0x28017ff8) != bytes(4) or r.read_ram(0x2802f630) != struct.pack('<I', 137):
            raise ValueError('UART dump or CLI configuration changed')
        self.original = r.read_ram(CODE, SIZE//4)
        if self.original != bytes(SIZE):
            raise ValueError('Microphone ring scratch is occupied')
        recorder = int.from_bytes(r.read_ram(RECORDER_GLOBAL), 'little')
        self.slot = recorder + 0x50
        if read_psram(r, self.slot, 1) != struct.pack('<I', CALLBACK):
            raise ValueError('Recorder callback changed')
        count = r.read_ram(0x28018004)
        time.sleep(.1)
        if r.read_ram(0x28018004) != count:
            raise ValueError('Factory microphone stream already active')
        code = elf_text(ROOT/'run/ram-mic-ring.o')
        if len(code) > 160:
            raise ValueError('Ring tap exceeds its separate scratch region')
        reply = self.c.exchange(f'psram_malloc {CAPACITY}', .5, 'allocate-mic-ring')
        match = re.search(rb'psram_malloc ret\((?:0x)?([0-9a-fA-F]+)\)', reply)
        if not match:
            raise ValueError('Microphone ring allocation failed')
        self.buffer = int(match[1], 16)
        self.writer = ScopedWriter(r, self.buffer, CAPACITY)
        self.writer.ranges = [(self.buffer, self.buffer+CAPACITY), (CODE, CODE+SIZE), (self.slot, self.slot+4)]
        scratch = bytearray(SIZE)
        scratch[:len(code)] = code
        struct.pack_into('<8I', scratch, 160, self.buffer, CAPACITY, 0, CALLBACK, 1, 0, 0, 0)
        try:
            self.borrowed = True
            self.writer.block(CODE, bytes(scratch))
            if r.read_ram(CODE, SIZE//4) != scratch:
                raise IOError('Ring helper readback mismatch')
            self.installed = True
            self.writer.word(self.slot, CODE|1)
            if read_psram(r, self.slot, 1) != struct.pack('<I', CODE|1):
                raise IOError('Ring callback registration mismatch')
            self.started = True
            self.c.exchange('mic_set 1 0 x', .2, 'start-mic-stream')
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.r.session_invalidated or self.c.session_invalidated:
            return
        if self.started:
            self.c.exchange('mic_set 0', .5, 'stop-mic-stream')
        if self.installed:
            self.writer.word(CONTEXT+16, 0)
            self.writer.word(self.slot, CALLBACK)
            if read_psram(self.r, self.slot, 1) != struct.pack('<I', CALLBACK):
                raise IOError('Microphone stream callback restoration failed')
            time.sleep(.05)
            if self.r.read_ram(CONTEXT+24) != bytes(4):
                raise IOError('Ring hook still in flight; retain its memory')
        if self.borrowed:
            self.writer.block(CODE, self.original)
            if self.r.read_ram(CODE, SIZE//4) != self.original:
                raise IOError('Ring scratch restoration failed')
        if self.buffer is not None:
            self.c.exchange(f'psram_free {self.buffer:#x}', .5, 'free-mic-ring')
        self.restored = True

    def chunks(self, seconds):
        """Yield live mu-law chunks while the callback continues recording."""
        if not 1 <= seconds <= 120:
            raise ValueError('Stream bench duration must be 1–120 seconds')
        consumed = 0
        produced = 0
        target = int(seconds * 8000)
        deadline = time.monotonic() + seconds + 15
        max_backlog = 0
        with BulkSession(self.r, self.buffer, CAPACITY, 'get', record_packets=False) as bulk:
            bulk.writer.word(BULK_CONTEXT+4, min(CAPACITY, target))
            while consumed < target:
                if time.monotonic() > deadline:
                    raise TimeoutError('Live microphone stream stalled')
                available = produced-consumed
                offset = consumed % CAPACITY
                count = min(80, CAPACITY-offset, target-consumed)
                if available < count or consumed % 5120 == 0 or getattr(self, 'refresh_counter', False):
                    self.refresh_counter = False
                    produced = int.from_bytes(self.r.read_ram(CONTEXT+8), 'little')
                    available = produced-consumed
                    max_backlog = max(max_backlog, available)
                    if available < 0 or available > CAPACITY-640:
                        raise IOError('Microphone ring overflow; no stale audio accepted')
                if available < count:
                    time.sleep(.01)
                    continue
                if offset == 0 and consumed:
                    bulk.writer.word(BULK_CONTEXT+8, 0)
                    bulk.writer.word(BULK_CONTEXT+4, min(CAPACITY, target-consumed))
                def ensure_retained():
                    current = int.from_bytes(self.r.read_ram(CONTEXT+8), 'little')
                    if not 0 <= current-consumed <= CAPACITY-640:
                        raise ValueError('Ring data expired before retry; refusing stale samples')
                chunk = bulk.read_chunk(offset, count, before_retry=ensure_retained)
                consumed += count
                yield chunk
        self.stats = {'bytes_streamed': consumed, 'max_backlog_bytes': max_backlog,
                      'sample_rate': 8000, 'encoding': 'mu-law', 'continuous_capture': True}


def bench(console, seconds=12):
    start = time.monotonic()
    data = bytearray()
    ring = MicRing(console)
    with ring:
        print('LIVE MICROPHONE STREAM NOW: '+str(seconds)+' seconds.', flush=True)
        stream_start = time.monotonic()
        for chunk in ring.chunks(seconds):
            data.extend(chunk)
        duration = time.monotonic()-stream_start
    pcm8 = audioop.ulaw2lin(bytes(data), 2)
    pcm16, _ = audioop.ratecv(pcm8, 2, 1, 8000, 16000, None)
    path = console.folder/'microphone-stream.wav'
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(pcm16)
    report = dict(ring.stats, stream_wall_seconds=round(duration, 2),
                  total_seconds=round(time.monotonic()-start, 2),
                  callback_and_scratch_restored=ring.restored, wav=str(path))
    (console.folder/'mic-stream-result.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', required=True)
    p.add_argument('--seconds', type=int, default=12)
    args = p.parse_args()
    with Console(args.port) as c:
        print(json.dumps(bench(c, args.seconds)), flush=True)
