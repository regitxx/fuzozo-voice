"""Temporary guarded CLI helpers for bounded allocated-PSRAM hex transfers."""
import re
import struct
import time

from fuzozo_console import ROOT
from ram_wav_transfer import SCRATCH, SCRATCH_SIZE, SLOT, ORIGINAL_SLOT, ScopedWriter, elf_text

CONTEXT = SCRATCH + 128
DESCRIPTOR = SCRATCH + 160


class MalformedBulkRead(ValueError):
    """A complete read-only reply arrived with a damaged/truncated body."""


class BulkSession:
    def __init__(self, reader, buffer, length, mode, record_packets=True):
        if mode not in ('put', 'get') or not 0 < length <= 512000 or length % 4:
            raise ValueError('Invalid bounded bulk transfer')
        self.r, self.c, self.buffer, self.length, self.mode = reader, reader.console, buffer, length, mode
        self.writer = ScopedWriter(reader, buffer, length)
        self.borrowed = self.installed = False
        self.offset = 0
        self.record_packets = record_packets

    def __enter__(self):
        r = self.r
        if r.read_image(0x20b9bf4,4).hex() != '0fb41fb500f032f978b10a4b1b7863b1':
            raise ValueError('Bulk helper print function signature changed')
        if r.read_ram(SLOT) != struct.pack('<I',ORIGINAL_SLOT) or r.read_ram(0x2802f630)!=struct.pack('<I',137):
            raise ValueError('Command registry changed')
        self.original = r.read_ram(SCRATCH,SCRATCH_SIZE//4)
        if self.original != bytes(SCRATCH_SIZE):
            raise ValueError('Bulk helper scratch is occupied')
        code = elf_text(ROOT / ('run/ram-bulk-'+self.mode+'.o'))
        if len(code)>128:
            raise ValueError('Bulk helper exceeds reserved code space')
        scratch = bytearray(SCRATCH_SIZE)
        scratch[:len(code)] = code
        struct.pack_into('<3I',scratch,128,self.buffer,self.length,0)
        struct.pack_into('<3I',scratch,160,SCRATCH+172,SCRATCH+172,SCRATCH|1)
        scratch[172:178]=b'labio\0'
        fmt = b'LABPUT:%08x\r\n\0' if self.mode=='put' else b'LABHEX:%s\r\n\0'
        scratch[184:184+len(fmt)] = fmt
        scratch[200:216] = b'0123456789abcdef'
        try:
            self.borrowed=True
            self.writer.block(SCRATCH,bytes(scratch))
            if r.read_ram(SCRATCH,SCRATCH_SIZE//4)!=scratch:
                raise IOError('Bulk helper readback mismatch')
            self.installed=True
            self.writer.word(SLOT,DESCRIPTOR)
            if r.read_ram(SLOT)!=struct.pack('<I',DESCRIPTOR):
                raise IOError('Bulk helper registration mismatch')
        except BaseException:
            self.__exit__(None,None,None)
            raise
        return self

    def __exit__(self,*_):
        if self.r.session_invalidated or self.c.session_invalidated:
            return
        if self.installed:
            self.writer.word(SLOT,ORIGINAL_SLOT)
            if self.r.read_ram(SLOT)!=struct.pack('<I',ORIGINAL_SLOT):
                raise IOError('Bulk helper registry restoration failed')
        if self.borrowed:
            self.writer.block(SCRATCH,self.original)
            if self.r.read_ram(SCRATCH,SCRATCH_SIZE//4)!=self.original:
                raise IOError('Bulk helper scratch restoration failed')

    def command(self, text, pattern):
        if self.r.session_invalidated or self.c.session_invalidated:
            raise IOError('Bulk session invalidated')
        data=bytearray()
        matched = False
        try:
            self.c.serial.reset_input_buffer()
            self.c.serial.write(text.encode('ascii')+b'\r\n')
            deadline=time.monotonic()+3
            match=None
            while time.monotonic()<deadline:
                data.extend(self.c.serial.read(max(1,min(self.c.serial.in_waiting,4096))))
                if len(data)>100000:
                    raise IOError('Bulk reply exceeded capture limit')
                if any(x in data.lower() for x in (b'prepare to deepsleep',b'reason -',b'start user app thread',b'memfault',b'hardfault')):
                    raise IOError('Device sleep or fault during bulk transfer')
                match=re.search(pattern,data)
                if match:
                    matched = True
                    return match[1]
                if self.mode == 'get' and re.search(rb'LABHEX:[^\r\n]*\r?\n', data):
                    raise MalformedBulkRead('Complete microphone read reply has an invalid length')
            raise TimeoutError('Bulk helper acknowledgement missing')
        except (OSError,TimeoutError):
            self.r.session_invalidated=True
            raise
        finally:
            self.c.sequence+=1
            if self.record_packets or not matched:
                (self.c.folder/f'{self.c.sequence:02}-bulk-{self.mode}.bin').write_bytes(data)

    def put(self,data):
        if self.mode!='put' or len(data)!=self.length:
            raise ValueError('Bulk upload length mismatch')
        for offset in range(0,len(data),80):
            chunk=data[offset:offset+80]
            ack=self.command('labio '+chunk.hex(),rb'LABPUT:([0-9a-f]{8})\r?\n')
            if int(ack,16)!=offset+len(chunk):
                self.r.session_invalidated=True
                raise IOError('Bulk upload offset mismatch')
        if int.from_bytes(self.r.read_ram(CONTEXT+8),'little')!=len(data):
            raise IOError('Bulk upload final offset mismatch')

    def get(self):
        if self.mode!='get':raise ValueError('Not a bulk download session')
        result=bytearray()
        for offset in range(0,self.length,80):
            count=min(80,self.length-offset)
            result.extend(self.read_chunk(offset, count))
        if int.from_bytes(self.r.read_ram(CONTEXT+8),'little')!=self.length:
            raise IOError('Bulk download final offset mismatch')
        return bytes(result)

    def read_chunk(self, offset, count, before_retry=None):
        if self.mode != 'get' or not 0 < count <= 80 or not 0 <= offset < offset+count <= self.length:
            raise ValueError('Invalid bounded bulk read chunk')
        for attempt in range(3):
            try:
                chunk = self.command('labio', rb'LABHEX:([0-9a-f]{'+str(count*2).encode()+rb'})\r?\n')
                return bytes.fromhex(chunk.decode('ascii'))
            except MalformedBulkRead:
                # The helper advances before printing. Prove the read finished
                # at its expected offset before replaying that read-only block.
                actual = int.from_bytes(self.r.read_ram(CONTEXT+8), 'little')
                if actual != offset+count:
                    raise ValueError('Damaged read reply also has an unexpected helper offset')
                if before_retry is not None:
                    before_retry()
                if attempt == 2:
                    raise
                self.writer.word(CONTEXT+8, offset)
