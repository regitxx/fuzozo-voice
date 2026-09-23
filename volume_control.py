"""Guarded native volume/mute settings for the identified firmware 1.0.42.

Invokes the same firmware setters as its volume buttons, then verifies the
saved-setting RAM values. Temporary code/command registry are restored.
"""
import struct
import time

from bkreg_probe import DebugReader
from fuzozo_console import ROOT
from scratch_writer import ScratchWriter
from ram_wav_transfer import SCRATCH, SCRATCH_SIZE, SLOT, ORIGINAL_SLOT, elf_text


def volume(console, level=None, muted=None):
    if level is not None and (type(level) is not int or not 0 <= level <= 100):
        raise ValueError('Volume must be an integer from 0 to 100')
    if muted is not None and type(muted) is not bool:
        raise ValueError('Muted must be true or false')
    r = DebugReader(console)
    if r.read_image(0x218a344, 8).hex() != '08b5074b5870fff797ff002203461146012096f78bfcbde80840fff7dbba00bf':
        raise ValueError('Volume setter firmware signature mismatch')
    if r.read_image(0x218a368, 4).hex() != '38b50d46011e14bf012300230c4c6371':
        raise ValueError('Mute setter firmware signature mismatch')
    cfg = r.read_ram(0x280180d0, 2)
    if cfg[1] > 100 or cfg[5] not in (0, 1):
        raise ValueError('Unexpected device volume configuration')
    if level is None and muted is None:
        return {'volume': cfg[1], 'muted': bool(cfg[5]), 'verified': True}
    if r.read_ram(SLOT) != struct.pack('<I', ORIGINAL_SLOT) or r.read_ram(0x2802f630) != struct.pack('<I', 137):
        raise ValueError('Command registry changed')
    original = r.read_ram(SCRATCH, SCRATCH_SIZE//4)
    if original != bytes(SCRATCH_SIZE):
        raise ValueError('Volume helper scratch occupied')
    code = elf_text(ROOT/'run/ram-volume.o')
    if len(code) > 96:
        raise ValueError('Volume helper exceeds reserved space')
    scratch = bytearray(SCRATCH_SIZE)
    scratch[:len(code)] = code
    struct.pack_into('<5I', scratch, 96, 0xffffffff if level is None else level,
                     0xffffffff if muted is None else int(muted), 0xffffffff, 0xffffffff, 0)
    struct.pack_into('<3I', scratch, 128, SCRATCH+144, SCRATCH+144, SCRATCH|1)
    scratch[144:154] = b'labvolume\0'
    w = ScratchWriter(r)
    borrowed = installed = False
    try:
        borrowed = True
        w.block(SCRATCH, bytes(scratch))
        if r.read_ram(SCRATCH, SCRATCH_SIZE//4) != scratch:
            raise IOError('Volume helper readback mismatch')
        installed = True
        w.word(SLOT, SCRATCH+128)
        console.exchange('labvolume', .15, 'native-volume')
        deadline = time.monotonic()+5
        while True:
            result = struct.unpack('<5I', r.read_ram(SCRATCH+96, 5))
            if result[4] == 1:
                break
            if time.monotonic() > deadline:
                r.session_invalidated = True
                raise TimeoutError('Volume helper remains active; normal restart required')
            time.sleep(.02)
        if result[2] > 100 or result[3] not in (0, 1):
            raise IOError('Native volume returned invalid state')
        if level is not None and result[2] != level or muted is not None and result[3] != int(muted):
            raise IOError('Native volume setting did not match its readback')
        return {'volume': result[2], 'muted': bool(result[3]), 'verified': True}
    finally:
        if not r.session_invalidated and not console.session_invalidated:
            if installed:
                w.word(SLOT, ORIGINAL_SLOT)
                if r.read_ram(SLOT) != struct.pack('<I', ORIGINAL_SLOT):
                    raise IOError('Volume command restoration failed')
            if borrowed:
                w.block(SCRATCH, original)
                if r.read_ram(SCRATCH, SCRATCH_SIZE//4) != original:
                    raise IOError('Volume scratch restoration failed')
