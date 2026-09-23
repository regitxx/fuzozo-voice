import struct
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP
from ram_wav_transfer import SCRATCH, CONTEXT, elf_text, make_scratch


class WavHelperTests(unittest.TestCase):
    def trial(self, fail_open=False, fail_write=False, short_write=False):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.mem_map(0x02000000, 0x400000)
        uc.mem_map(0x28000000, 0x60000)
        uc.mem_map(0x60000000, 0x20000)
        size = 110124
        payload = b'\x55'*size
        uc.mem_write(0x60000000, payload)
        uc.mem_write(SCRATCH, make_scratch(elf_text('run/ram-wav-helper.o'), 0x60000000, size, '/labvoice/test.wav'))
        uc.reg_write(UC_ARM_REG_SP, 0x2805e000)
        uc.reg_write(UC_ARM_REG_LR, 0x0213f001)
        written = bytearray()
        closes = []
        completed = []
        def hook(machine, address, count, unused):
            if address == 0x0213f000:
                completed.append(True)
                machine.emu_stop()
                return
            if address not in (0x0212c8e8, 0x0212cc40, 0x0212ca10):
                return
            self.assertEqual(machine.reg_read(UC_ARM_REG_SP)%8, 0)
            if address == 0x0212c8e8:
                self.assertEqual(machine.reg_read(UC_ARM_REG_R1), 0x20a)
                result = 0xffffffff if fail_open else 2
            elif address == 0x0212cc40:
                self.assertEqual(machine.reg_read(UC_ARM_REG_R0), 2)
                count = machine.reg_read(UC_ARM_REG_R2)
                self.assertTrue(0 < count <= 2048)
                count = min(count, 997) if short_write else count
                result = 0xffffffff if fail_write else count
                if not fail_write:
                    written.extend(machine.mem_read(machine.reg_read(UC_ARM_REG_R1), count))
            else:
                closes.append(machine.reg_read(UC_ARM_REG_R0))
                result = 0
            machine.reg_write(UC_ARM_REG_R0, result)
            machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))
        uc.hook_add(UC_HOOK_CODE, hook)
        uc.emu_start(SCRATCH|1, 0x0213f002, count=100000)
        self.assertEqual(completed, [True])
        self.assertEqual(uc.reg_read(UC_ARM_REG_SP), 0x2805e000)
        values = struct.unpack('<7I', uc.mem_read(CONTEXT, 28))
        self.assertEqual(values[5], 3)  # Terminal even when open fails.
        self.assertEqual(closes, [] if fail_open else [2])
        if not fail_open and not fail_write:
            self.assertEqual(bytes(written), payload)
            self.assertEqual(values[3], size)

    def test_full_write(self): self.trial()
    def test_short_writes(self): self.trial(short_write=True)
    def test_failed_open_is_terminal(self): self.trial(fail_open=True)
    def test_failed_write_closes(self): self.trial(fail_write=True)


if __name__ == '__main__':
    unittest.main()
