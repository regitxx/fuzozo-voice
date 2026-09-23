"""Restore only the exact known RAM stream helpers after a lost host reply.

Uses a newly identity-checked, exclusively owned console and current recorder
metadata. Any mismatch stops recovery; never use cached PSRAM addresses.
"""
import json
import struct

from bkreg_probe import DebugReader
from fuzozo_agent import selected_port
from fuzozo_console import Console
from mic_stream import CODE, SIZE, CONTEXT, CAPACITY
from mic_capture import RECORDER_GLOBAL, read_psram, CALLBACK, CALLBACK_SIGNATURE
from ram_wav_transfer import SCRATCH, SCRATCH_SIZE, SLOT, ORIGINAL_SLOT, ScopedWriter, elf_text


def recover(console):
    r = DebugReader(console)
    def require(condition, message):
        if not condition:
            raise ValueError('Recovery stopped: '+message)
    require(r.read_image(CALLBACK&~1, 4) == CALLBACK_SIGNATURE, 'callback firmware changed')
    require(r.read_image(0x2186dec, 4).hex() == 'f8b51d465b682c4e93f90030312b47d1', 'mic command changed')
    require(r.read_ram(CODE, 32) == elf_text('run/ram-mic-ring.o'), 'ring code is not ours')
    require(r.read_ram(SCRATCH, 23) == elf_text('run/ram-bulk-get.o'), 'bulk code is not ours')
    require(r.read_ram(SLOT) == struct.pack('<I', SCRATCH+160), 'bulk descriptor changed')
    require(r.read_ram(0x2802f630) == struct.pack('<I', 137), 'registry count changed')
    ctx = struct.unpack('<8I', r.read_ram(CONTEXT, 8))
    require(ctx[1] == CAPACITY and ctx[3] == CALLBACK and ctx[4] == 1, 'ring context changed')
    buffer = ctx[0]
    bulk = struct.unpack('<3I', r.read_ram(SCRATCH+128, 3))
    require(bulk[0] == buffer and 0 < bulk[1] <= CAPACITY and bulk[2] <= bulk[1], 'bulk bounds changed')
    recorder = int.from_bytes(r.read_ram(RECORDER_GLOBAL), 'little')
    slot = recorder+0x50
    require(read_psram(r, slot, 1) == struct.pack('<I', CODE|1), 'current recorder does not own our hook')
    w = ScopedWriter(r, buffer, CAPACITY)
    w.ranges += [(CODE, CODE+SIZE), (slot, slot+4)]
    console.exchange('mic_set 0', .7, 'stop-owned-stream-for-recovery')
    w.word(CONTEXT+16, 0)
    w.word(slot, CALLBACK)
    require(read_psram(r, slot, 1) == struct.pack('<I', CALLBACK), 'callback restoration failed')
    require(r.read_ram(CONTEXT+24) == bytes(4), 'callback still in flight')
    w.word(SLOT, ORIGINAL_SLOT)
    require(r.read_ram(SLOT) == struct.pack('<I', ORIGINAL_SLOT), 'registry restoration failed')
    w.block(CODE, bytes(SIZE))
    w.block(SCRATCH, bytes(SCRATCH_SIZE))
    require(r.read_ram(CODE, SIZE//4) == bytes(SIZE), 'ring scratch restoration failed')
    require(r.read_ram(SCRATCH, SCRATCH_SIZE//4) == bytes(SCRATCH_SIZE), 'bulk scratch restoration failed')
    console.exchange(f'psram_free {buffer:#x}', .5, 'free-recovered-ring')
    result = {'owned_helpers_verified': True, 'current_callback_restored': True,
              'registry_and_scratch_restored': True, 'buffer_freed': True}
    (console.folder/'stream-recovery.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    with Console(selected_port(None)) as c:
        print(json.dumps(recover(c)), flush=True)
        print('captures', c.folder, flush=True)
