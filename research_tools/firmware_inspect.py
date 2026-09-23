"""Offline strings, hashing, XZ unpacking, and bounded ARM Thumb disassembly."""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import capstone
from capstone.arm import ARM_OP_MEM, ARM_REG_PC
LIMIT=32*1024*1024


def unpack_xz(data, offset=64, limit=LIMIT):
    if not 0 <= offset < len(data) or data[offset:offset+6] != b'\xfd7zXZ\0':
        raise ValueError('No XZ header at the specified offset; inspect the package format first')
    decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=128*1024*1024)
    result=decoder.decompress(data[offset:],max_length=limit+1)
    if len(result)>limit or not decoder.eof:
        raise ValueError('Unpacked image exceeds the limit or is truncated')
    if decoder.unused_data:
        raise ValueError('Unexpected trailing bytes after XZ stream; inspect separately')
    return result


def strings(data, base):
    return [{'offset':hex(m.start()),'address':hex(base+m.start()),'text':m[0].decode()}
            for m in re.finditer(rb'[\x20-\x7e]{5,}',data)]


def disassemble(data, base, start, end):
    if not base <= start < end <= base+len(data) or end-start>2*1024*1024:
        raise ValueError('Choose an in-image code range of at most 2 MiB')
    md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB)
    md.detail=True;md.skipdata=True
    rows=[]
    for ins in md.disasm(data[start-base:end-base],start):
        note=''
        if ins.id and ins.mnemonic.startswith('ldr'):
            for op in ins.operands:
                if op.type==ARM_OP_MEM and op.mem.base==ARM_REG_PC:
                    off=((ins.address+4)&~3)+op.mem.disp-base
                    if 0<=off<=len(data)-4:
                        ptr=struct.unpack_from('<I',data,off)[0]
                        note=' ; literal '+hex(ptr)
                        if 0<=ptr-base<len(data):
                            text=data[ptr-base:ptr-base+240].split(b'\0')[0]
                            if len(text)>2 and all(32<=b<127 or b in (10,13) for b in text):note+=' '+repr(text.decode())
        rows.append(f'{ins.address:#x}: {ins.mnemonic:9} {ins.op_str}{note}')
    return '\n'.join(rows)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image',type=Path)
    p.add_argument('--sha256',help='Expected hash from your trusted acquisition record')
    p.add_argument('--base',type=lambda x:int(x,0),default=0x02010000)
    p.add_argument('--unpack-xz',action='store_true');p.add_argument('--xz-offset',type=lambda x:int(x,0),default=64)
    p.add_argument('--strings',action='store_true');p.add_argument('--start',type=lambda x:int(x,0));p.add_argument('--end',type=lambda x:int(x,0))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.image.stat().st_size>LIMIT: p.error('Input exceeds 32 MiB')
    data=a.image.read_bytes();digest=hashlib.sha256(data).hexdigest()
    if a.sha256 and digest.lower()!=a.sha256.lower():p.error('Input SHA256 mismatch')
    if a.unpack_xz: output=unpack_xz(data,a.xz_offset)
    elif a.strings:output=(json.dumps(strings(data,a.base),indent=2)+'\n').encode()
    elif a.start is not None and a.end is not None:output=disassemble(data,a.base,a.start,a.end).encode()
    else:p.error('Choose --unpack-xz, --strings, or --start and --end')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    import os
    os.umask(0o077)
    with a.output.open('xb') as f:f.write(output)
    print(json.dumps({'input_sha256':digest,'output_sha256':hashlib.sha256(output).hexdigest(),'output_bytes':len(output)}))
if __name__=='__main__':main()
