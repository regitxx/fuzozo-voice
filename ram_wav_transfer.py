#!/usr/bin/env python3
"""Version-specific, reversible RAM helper for a normal WAV lab-file transfer.

For the verified 1.0.42 unit only. Guard every address against live signatures.
Borrow 224 verified-zero bytes in unused CLI registry slots, allocate only the
audio buffer in PSRAM, temporarily replace the xq registry entry, and restore
the entry and borrowed bytes immediately after writing a uniquely named WAV.
No firmware/flash/register-peripheral write is implemented. Playback requires
a device-side file MD5 match after restoration. Run the emulator test first.
"""
import argparse
import hashlib
import io
import json
import re
import struct
import time
import uuid
import wave
from pathlib import Path

from bkreg_probe import DebugReader
from fuzozo_console import Console

SCRATCH = 0x2802f534
SCRATCH_SIZE = 224
SLOT = 0x2802f3b0
ORIGINAL_SLOT = 0x0204817c
CONTEXT = SCRATCH + 96
DESCRIPTOR = SCRATCH + 128
SIGNATURES = {
    0x02010000: bytes.fromhex('00f80528718f0b0201020008218e0b02'),
    0x0212c8e8: bytes.fromhex('70b58cb004460e46fff7b0ff20b14ff0'),
    0x0212cc40: bytes.fromhex('f0b58bb007460d461646fff703fe0446'),
    0x0212ca10: bytes.fromhex('f0b58bb00746fff71dff00284dd1fff7'),
}


def elf_text(path):
    data = Path(path).read_bytes()
    if data[:6] != b'\x7fELF\x01\x01':
        raise ValueError('Expected a little-endian ELF32 ARM object')
    if struct.unpack_from('<H', data, 18)[0] != 40:
        raise ValueError('Object is not ARM')
    table = struct.unpack_from('<I', data, 32)[0]
    size, count, strings = struct.unpack_from('<HHH', data, 46)
    sections = [struct.unpack_from('<10I', data, table+i*size) for i in range(count)]
    names = data[sections[strings][4]:sections[strings][4]+sections[strings][5]]
    for sec in sections:
        name = names[sec[0]:].split(b'\0')[0]
        if name in (b'.rel.text', b'.rela.text') and sec[5]:
            raise ValueError('Helper contains unresolved relocations')
    text = next(s for s in sections if names[s[0]:].split(b'\0')[0] == b'.text')
    return data[text[4]:text[4]+text[5]]


def make_scratch(code, buffer, length, path):
    encoded = path.encode('ascii') + b'\0'
    if len(code) > 96 or len(encoded) > 64:
        raise ValueError('Helper or dedicated lab path exceeds reserved space')
    data = bytearray(SCRATCH_SIZE)
    data[:len(code)] = code
    struct.pack_into('<7I', data, 96, SCRATCH+160, buffer, length,
                     0xffffffff, 0xffffffff, 0, 0xffffffff)
    struct.pack_into('<3I', data, 128, SCRATCH+144, SCRATCH+144, SCRATCH|1)
    data[144:151] = b'labwav\0'
    data[160:160+len(encoded)] = encoded
    return bytes(data)


class ScopedWriter:
    def __init__(self, reader, buffer, size):
        if buffer % 4 or not 0x60000000 <= buffer < buffer+size <= 0x60800000:
            raise ValueError('Allocator returned an unexpected PSRAM range')
        self.reader = reader
        self.ranges = [(buffer, buffer+size), (SCRATCH, SCRATCH+SCRATCH_SIZE), (SLOT, SLOT+4)]

    def word(self, address, value):
        if address % 4 or not any(a <= address and address+4 <= b for a,b in self.ranges):
            raise ValueError('Write outside allocated/borrowed scratch scope')
        encoded = struct.pack('<II', address, value)
        event = self.reader.exchange(bytes.fromhex('01e0fc0901') + encoded,
                                     bytes.fromhex('01e0fc01') + encoded, 12,
                                     f'ram-write-{address:08x}')
        if event[-8:] != encoded:
            raise IOError('RAM write acknowledgment mismatch')

    def block(self, address, data):
        if len(data) % 4:
            raise ValueError('RAM data must be word-aligned')
        for offset in range(0, len(data), 4):
            self.word(address+offset, struct.unpack_from('<I', data, offset)[0])
            if len(data) > 4096 and offset % 8192 == 0:
                print(json.dumps({'ram_bytes_sent': offset+4, 'total': len(data)}), flush=True)


def transfer(console, wav, code):
    with wave.open(io.BytesIO(wav), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1,2,16000,'NONE'):
            raise ValueError('Expected PCM16 mono 16 kHz WAV')
        if not 0 < audio.getnframes() <= 64000:
            raise ValueError('WAV must be at most four seconds')
    if len(wav) > 128100:
        raise ValueError('WAV exceeds bench transfer size')
    r = DebugReader(console)
    r.link()
    for address, expected in SIGNATURES.items():
        if r.read_image(address, len(expected)//4) != expected:
            raise ValueError('Live firmware signature mismatch; no RAM writes')
    if r.read_ram(0x280086e4) != struct.pack('<I', 0x2802f230):
        raise ValueError('CLI registry moved; no RAM writes')
    if r.read_ram(0x2802f630) != struct.pack('<I', 137):
        raise ValueError('CLI registry size changed; no RAM writes')
    if r.read_ram(SLOT) != struct.pack('<I', ORIGINAL_SLOT):
        raise ValueError('Expected xq registry slot not found; no RAM writes')
    original = r.read_ram(SCRATCH, SCRATCH_SIZE//4)
    if original != bytes(SCRATCH_SIZE):
        raise ValueError('Reserved CLI slots are not unused; no RAM writes')
    padded = wav + bytes((-len(wav)) % 4)
    allocation = len(padded)
    reply = console.exchange_matching(f'psram_malloc {allocation}', 2, 'allocate-wav',
                                      rb'psram_malloc ret\((?:0x)?[0-9a-fA-F]+\)')
    match = re.search(rb'psram_malloc ret\((?:0x)?([0-9a-fA-F]+)\)', reply)
    if match is None:
        raise ValueError('No unambiguous PSRAM allocation result')
    buffer = int(match[1], 16)
    writer = ScopedWriter(r, buffer, allocation)
    path = '/labvoice/voice_' + uuid.uuid4().hex[:16] + '.wav'
    digest = hashlib.md5(wav).hexdigest()
    report = {'robot_path':path, 'bytes':len(wav), 'expected_md5':digest,
              'buffer':hex(buffer), 'scratch_restored':False, 'registry_restored':False,
              'file_verified':False, 'custom_speech_heard':False}
    report_path = console.folder/'ram-wav-result.json'
    def save(): report_path.write_text(json.dumps(report,indent=2)+'\n')
    save()
    borrowed = False
    slot_touched = False
    helper_finished = False
    try:
        # Validate real RAM writes in allocated memory before borrowing SRAM.
        writer.word(buffer, struct.unpack_from('<I', padded)[0])
        if r._read_words(buffer, 1) != padded[:4]:
            raise IOError('Allocated RAM write/readback failed')
        from ram_bulk_io import BulkSession
        transfer_start = time.monotonic()
        with BulkSession(r, buffer, allocation, 'put') as bulk:
            bulk.put(padded)
        report['upload_seconds'] = round(time.monotonic() - transfer_start, 2)
        report['transport'] = 'bounded hex block helper'
        scratch = make_scratch(code, buffer, len(wav), path)
        borrowed = True
        writer.block(SCRATCH, scratch)
        if r.read_ram(SCRATCH, SCRATCH_SIZE//4) != scratch:
            raise IOError('RAM helper readback mismatch')
        slot_touched = True
        writer.word(SLOT, DESCRIPTOR)
        if r.read_ram(SLOT) != struct.pack('<I', DESCRIPTOR):
            raise IOError('Temporary command registration mismatch')
        console.exchange('labwav', .1, 'write-wav-helper')
        deadline = time.monotonic()+5
        while True:
            result = struct.unpack('<7I', r.read_ram(CONTEXT, 7))
            if result[5] == 3:
                break
            if time.monotonic() > deadline:
                r.session_invalidated = True
                raise TimeoutError('WAV helper remains active; retain its memory until recovery')
            time.sleep(.02)
        report.update({'write_return':result[3], 'open_return':result[4],
                       'helper_stage':result[5], 'close_return':result[6]})
        helper_finished = result[5] == 3
        if not helper_finished or result[3] != len(wav) or result[6] != 0:
            raise IOError('Helper did not complete an exact WAV write and close')
    finally:
        if r.session_invalidated or console.session_invalidated:
            report['session_invalidated'] = True
            report['cleanup_skipped'] = 'RAM ownership cannot be trusted after sleep, reboot, or lost debug link'
            report['registry_touched'] = slot_touched
            report['scratch_touched'] = borrowed
            save()
        else:
            # Restore the callable entry first; never free data referenced by a
            # still-running helper. A failed restoration is surfaced, not hidden.
            if slot_touched:
                writer.word(SLOT, ORIGINAL_SLOT)
                report['registry_restored'] = r.read_ram(SLOT) == struct.pack('<I', ORIGINAL_SLOT)
                save()
                if not report['registry_restored']:
                    raise IOError('CLI registry restoration not verified')
            else:
                report['registry_restored'] = True
            if borrowed:
                writer.block(SCRATCH, original)
                report['scratch_restored'] = r.read_ram(SCRATCH, SCRATCH_SIZE//4) == original
                save()
                if not report['scratch_restored']:
                    raise IOError('Borrowed SRAM restoration not verified')
            else:
                report['scratch_restored'] = True
            if helper_finished or not slot_touched:
                console.exchange(f'psram_free {buffer:#x}', .1, 'free-wav-buffer')
            save()
    response = console.exchange_matching('cpu1 md5sum '+path, 3, 'md5-normal-wav', digest.encode())
    report['file_verified'] = bool(re.search(rb'(?<![0-9a-f])'+digest.encode()+rb'(?![0-9a-f])',response.lower()))
    save()
    if not report['file_verified']:
        raise IOError('Normal WAV file checksum mismatch; playback not attempted')
    print(json.dumps(report),flush=True)
    report['playback_log'] = console.play(path)
    save()
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('wav',type=Path)
    p.add_argument('--port',required=True)
    p.add_argument('--helper',type=Path,default=Path('run/ram-wav-helper.o'))
    args=p.parse_args()
    with Console(args.port) as c:
        print(json.dumps({'target_verified':True,'captures':str(c.folder)}),flush=True)
        print(json.dumps(transfer(c,args.wav.read_bytes(),elf_text(args.helper))),flush=True)
