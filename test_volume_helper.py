import struct
import unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP
from ram_wav_transfer import elf_text, SCRATCH


class VolumeHelperTests(unittest.TestCase):
    def test_query_set_and_unchanged(self):
        for level, muted in ((0xffffffff, 0xffffffff), (20, 1), (100, 0), (0, 1)):
            uc=Uc(UC_ARCH_ARM, UC_MODE_THUMB)
            uc.mem_map(0x02000000,0x400000);uc.mem_map(0x28000000,0x60000)
            code=elf_text('run/ram-volume.o');self.assertLessEqual(len(code),96)
            uc.mem_write(SCRATCH,code)
            uc.mem_write(SCRATCH+96,struct.pack('<5I',level,muted,0xffffffff,0xffffffff,0))
            uc.mem_write(0x280180d0,bytes([0,100,0,0,0,0,0,0]))
            uc.reg_write(UC_ARM_REG_SP,0x2805e000);uc.reg_write(UC_ARM_REG_LR,0x213f001)
            called=[]
            def hook(m,a,s,u):
                if a==0x213f000:m.emu_stop();return
                if a not in (0x218a344,0x218a368):return
                self.assertEqual(m.reg_read(UC_ARM_REG_SP)%8,0)
                value=m.reg_read(UC_ARM_REG_R0);called.append((a,value))
                if a==0x218a368:self.assertEqual(m.reg_read(UC_ARM_REG_R1),1)
                m.mem_write(0x280180d0+(1 if a==0x218a344 else 5),bytes([value]))
                m.reg_write(UC_ARM_REG_PC,m.reg_read(UC_ARM_REG_LR))
            uc.hook_add(UC_HOOK_CODE,hook);uc.emu_start(SCRATCH|1,0x213f002,count=1000)
            result=struct.unpack('<5I',uc.mem_read(SCRATCH+96,20))
            self.assertEqual(result[2:],(100 if level==0xffffffff else level,0 if muted==0xffffffff else muted,1))
            self.assertEqual(uc.reg_read(UC_ARM_REG_SP),0x2805e000)
            if level in (100,0xffffffff) and muted in (0,0xffffffff):self.assertEqual(called,[])


if __name__=='__main__':unittest.main()
