"""Emulate the exact temporary ARM recorder hook before running it on Fuzozo."""
import audioop
import random
import struct
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import *
from ram_wav_transfer import elf_text

CODE = 0x2802f474
CTX = CODE + 160
BUFFER = 0x60000000
FRAME = 0x60011000
SAMPLES = 0x60012000
ORIGINAL = 0x021895e4


class RingTapTests(unittest.TestCase):
    def invoke(self, samples, counter=0, enabled=True):
        code = elf_text('run/ram-mic-ring.o')
        self.assertLessEqual(len(code), 160)
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.mem_map(0x28000000, 0x60000)
        uc.mem_map(0x60000000, 0x20000)
        uc.mem_map(0x02189000, 0x1000)
        uc.mem_write(CODE, code)
        uc.mem_write(CTX, struct.pack('<8I', BUFFER, 65536, counter, ORIGINAL|1,
                                      int(enabled), 0, 0, 0))
        stereo = b''.join(struct.pack('<hh', sample, 12345) for sample in samples)
        uc.mem_write(SAMPLES, stereo)
        uc.mem_write(FRAME, struct.pack('<IIH', 0, SAMPLES, len(stereo)))
        registers = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                     UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                     UC_ARM_REG_LR, UC_ARM_REG_SP]
        expected = [FRAME, 11, 22, 33, 44, 55, 66, 77, 0x02189001, 0x2805e000]
        for register, value in zip(registers, expected):
            uc.reg_write(register, value)
        reached = []
        def hook(machine, address, size, unused):
            if address == ORIGINAL:
                reached.append(True)
                machine.emu_stop()
        uc.hook_add(UC_HOOK_CODE, hook)
        uc.emu_start(CODE|1, ORIGINAL+2, count=200000)
        self.assertEqual(reached, [True])
        self.assertEqual([uc.reg_read(r) for r in registers], expected)
        context = struct.unpack('<8I', uc.mem_read(CTX, 32))
        self.assertEqual(context[5:7], (1, 0))
        if enabled:
            mono = b''.join(struct.pack('<h', (samples[i] + samples[i+1]) >> 1)
                            for i in range(0, len(samples)-1, 2))
            encoded = audioop.lin2ulaw(mono, 2)
            actual = bytes(uc.mem_read(BUFFER + ((counter+i)&65535), 1)[0]
                           for i in range(len(encoded)))
            self.assertEqual(actual, encoded)
            self.assertEqual(context[2], (counter+len(encoded)) & 0xffffffff)
        else:
            self.assertEqual(context[2], counter)
            self.assertEqual(bytes(uc.mem_read(BUFFER, 65536)), bytes(65536))

    def test_extremes_random_and_ring_wrap(self):
        rng = random.Random(42)
        samples = [-32768, -32768, 32767, 32767, -1, -1, 0, 0]
        samples += [rng.randrange(-32768, 32768) for _ in range(632)]
        for count in (0, 65480, 0xfffffff0):
            self.invoke(samples, count)

    def test_disabled_and_short_frame(self):
        self.invoke([20000]*640, enabled=False)
        self.invoke([42])


if __name__ == '__main__':
    unittest.main()
