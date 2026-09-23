#!/usr/bin/env python3
"""Offline ARM64 Mach-O references and annotated bounded disassembly."""
import argparse
import bisect
import re
import struct
import subprocess
from pathlib import Path
from research_tools.swift_metadata import MachO


class Inspector(MachO):
    def __init__(self, path):
        super().__init__(path)
        self.path = str(path)
        self.starts, self.symbols = [], {}
        pos, stub_sections = 32, []
        symtab = dysymtab = None
        for _ in range(self.u32(16)):
            cmd, size = self.unpack('II', pos)
            if cmd == 2:
                symtab = self.unpack('IIII', pos+8)
            elif cmd == 11:
                dysymtab = self.unpack('II', pos+56)
            elif cmd == 0x26:
                off, length = self.unpack('II', pos+8)
                addr = self.segments[1][0] if self.segments[0][2] == 0 else self.segments[0][0]
                value = shift = 0
                for b in self.data[off:off+length]:
                    value |= (b & 127) << shift
                    if b & 128:
                        shift += 7
                    elif value:
                        addr += value
                        self.starts.append(addr)
                        value = shift = 0
                    else:
                        break
            elif cmd == 0x19:
                for n in range(self.u32(pos+64)):
                    s = pos+72+n*80
                    if self.u32(s+64) & 255 == 8:
                        addr, length = self.unpack('QQ', s+32)
                        first, stride = self.unpack('II', s+68)
                        stub_sections.append((addr,length,first,stride))
            pos += size
        if symtab and dysymtab:
            symoff, count, stroff, _ = symtab
            indirect, _ = dysymtab
            for addr,length,first,stride in stub_sections:
                for n in range(length//stride):
                    idx = self.u32(indirect+(first+n)*4)
                    if idx < count:
                        nameoff = self.u32(symoff+16*idx)
                        self.symbols[addr+n*stride] = self.cstr(stroff+nameoff)
        if '__objc_stubs' in self.sections:
            addr, off, size = self.sections['__objc_stubs']
            for n in range(0,size,32):
                adrp, ldr = self.unpack('II',off+n)
                if adrp & 0x9f00001f != 0x90000001 or ldr & 0xffc003ff != 0xf9400021:
                    continue
                imm = ((adrp>>29)&3) | (((adrp>>5)&0x7ffff)<<2)
                if imm & (1<<20): imm -= 1<<21
                selector_ref = ((addr+n)&~4095)+(imm<<12)+(((ldr>>10)&4095)*8)
                try:
                    selector = self.cstr(self.offset(self.pointer(self.offset(selector_ref))))
                    self.symbols[addr+n] = 'objc_msgSend '+selector
                except ValueError:
                    pass

    def function(self, addr):
        idx = bisect.bisect_right(self.starts, addr)-1
        return self.starts[idx] if idx >= 0 else None

    def objc_methods(self):
        """Index on-disk Objective-C method lists, including relative entries."""
        if '__objc_classlist' not in self.sections:
            return []
        _, start, size = self.sections['__objc_classlist']
        result = []
        for slot in range(start, start+size, 8):
            try:
                cls = self.offset(self.pointer(slot))
                for meta in (False, True):
                    obj = self.offset(self.pointer(cls)) if meta else cls
                    ro = self.offset(self.pointer(obj+32) & ~7)
                    name = self.cstr(self.offset(self.pointer(ro+24)))
                    if self.unpack('Q', ro+32)[0] == 0:
                        continue
                    methods = self.offset(self.pointer(ro+32))
                    flags, count = self.unpack('II', methods)
                    stride = flags & 0xffff
                    if stride not in (12, 24) or count > 20000:
                        continue
                    for n in range(count):
                        item = methods+8+n*stride
                        if flags & 0x80000000:
                            sel = self.rel(item)
                            if not flags & 0x40000000:
                                sel = self.offset(self.pointer(sel))
                            imp = self.address(self.rel(item+8))
                        else:
                            sel = self.offset(self.pointer(item))
                            imp = self.pointer(item+16)
                        result.append((name, '+' if meta else '-', self.cstr(sel), imp))
            except (ValueError, struct.error, TypeError):
                continue
        if '__objc_catlist' in self.sections:
            _, start, size = self.sections['__objc_catlist']
            for slot in range(start,start+size,8):
                try:
                    cat=self.offset(self.pointer(slot))
                    name='category:'+self.cstr(self.offset(self.pointer(cat)))
                    for delta,kind in ((16,'-'),(24,'+')):
                        if self.unpack('Q',cat+delta)[0]==0:
                            continue
                        methods=self.offset(self.pointer(cat+delta))
                        flags,count=self.unpack('II',methods)
                        stride=flags&0xffff
                        if stride not in (12,24) or count>20000:
                            continue
                        for n in range(count):
                            item=methods+8+n*stride
                            if flags&0x80000000:
                                sel=self.rel(item)
                                if not flags&0x40000000:
                                    sel=self.offset(self.pointer(sel))
                                imp=self.address(self.rel(item+8))
                            else:
                                sel=self.offset(self.pointer(item))
                                imp=self.pointer(item+16)
                            result.append((name,kind,self.cstr(sel),imp))
                except (ValueError,struct.error,TypeError):
                    continue
        return result

    def callers(self, target):
        addr, off, size = self.sections['__text']
        found = []
        for n,(word,) in enumerate(struct.iter_unpack('<I',self.data[off:off+size])):
            if word & 0xfc000000 not in (0x94000000,0x14000000):
                continue
            delta = word & 0x3ffffff
            if delta & (1<<25):
                delta -= 1<<26
            here = addr+4*n
            if here+4*delta == target:
                found.append((hex(here),hex(self.function(here) or 0)))
        return found

    def text_at(self, addr):
        # Only annotate a string when its address falls in a string section.
        if '__cfstring' in self.sections:
            base, off, size = self.sections['__cfstring']
            if base <= addr < base+size and (addr-base) % 32 == 0:
                item = off+addr-base
                try:
                    data = self.offset(self.pointer(item+16))
                    length = self.unpack('Q', item+24)[0]
                    if length <= 4096:
                        utf16 = bool(self.u32(item+8) & 0x10)
                        raw = self.data[data:data+length*(2 if utf16 else 1)]
                        return repr(raw.decode('utf-16le' if utf16 else 'utf-8'))
                except (ValueError, UnicodeError):
                    pass
        for name in ('__cstring','__objc_methname','__swift5_reflstr'):
            if name not in self.sections:
                continue
            base, off, size = self.sections[name]
            if base <= addr < base+size:
                return repr(self.cstr(off+addr-base))
        return None

    def disassemble(self, start, end):
        output = subprocess.check_output(['xcrun','llvm-objdump','--disassemble',
                    f'--start-address={start}',f'--stop-address={end}',self.path],text=True)
        regs, rows = {}, []
        for line in output.splitlines():
            m = re.match(r'([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)\s*(.*)', line.strip())
            if not m:
                continue
            addr, op, args = int(m[1],16),m[2],m[3].split(' <')[0].split(' ;')[0].strip()
            if addr in self.starts:
                rows.append(f'\nfunction {addr:#x}')
                regs.clear()
            note = ''
            parts = [p.strip() for p in args.split(',')]
            reg = lambda r: 'x'+r[1:] if r.startswith('w') else r
            if op in ('adrp','adr'):
                regs[parts[0]] = int(parts[1],16)
            elif op in ('mov','movz') and len(parts) >= 2 and parts[1].startswith('#'):
                regs[reg(parts[0])] = int(parts[1][1:],0) & ((1<<64)-1)
            elif op == 'movk' and reg(parts[0]) in regs:
                shift = int(parts[2].split('#')[1],0) if len(parts)>2 else 0
                old = regs[reg(parts[0])]
                regs[reg(parts[0])] = (old & ~(65535<<shift)) | (int(parts[1][1:],0)<<shift)
            elif op == 'mov' and len(parts)==2:
                if reg(parts[1]) in regs:
                    regs[reg(parts[0])] = regs[reg(parts[1])]
                else:
                    regs.pop(reg(parts[0]),None)
            elif op in ('add','sub') and len(parts)==3 and parts[2].startswith('#') and reg(parts[1]) in regs:
                regs[reg(parts[0])] = regs[reg(parts[1])] + (1 if op=='add' else -1)*int(parts[2][1:],0)
            elif op in ('bl','b') and args.startswith('0x'):
                target = int(args,16)
                note = self.symbols.get(target,'')
                # Annotate plausible Swift small-string pairs, never a live value.
                for r in range(0,8):
                    a,b = regs.get(f'x{r}'),regs.get(f'x{r+1}')
                    if a is not None and b is not None and b>>60 == 14:
                        n = (b>>56)&15
                        raw = struct.pack('<QQ',a,b)[:n]
                        if n>=3 and all(32<=c<127 for c in raw):
                            note += f' small_string(x{r})={raw.decode()!r}'
                if op == 'bl':
                    for r in range(19):
                        regs.pop(f'x{r}',None)
            elif parts and op not in ('str','stur','stp','cmp','tst','cbz','cbnz','tbz','tbnz','ret','nop'):
                regs.pop(reg(parts[0]),None)
            if parts and reg(parts[0]) in regs:
                note += ' '+(self.text_at(regs[reg(parts[0])]) or '')
            rows.append(f'{addr:#x}: {op:8} {args}'+(f' // {note.strip()}' if note.strip() else ''))
        return '\n'.join(rows)+'\n'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary')
    p.add_argument('--callers', type=lambda x:int(x,0))
    p.add_argument('--objc-method', help='Substring of Objective-C class or selector')
    p.add_argument('--start', type=lambda x:int(x,0))
    p.add_argument('--end', type=lambda x:int(x,0))
    p.add_argument('--output')
    a=p.parse_args(); m=Inspector(a.binary)
    if a.objc_method:
        for cls, kind, selector, imp in m.objc_methods():
            if a.objc_method.lower() in (cls+' '+selector).lower():
                print(hex(imp), f'{kind}[{cls} {selector}]')
    elif a.callers is not None:
        for row in m.callers(a.callers): print(*row)
    elif a.start is not None and a.end is not None and a.output:
        if a.end-a.start>0x200000: p.error('Select a bounded code range <=2 MiB')
        out=Path(a.output)
        with out.open('x') as f: f.write(m.disassemble(a.start,a.end))
        out.chmod(0o600)
        print(f'Saved annotated disassembly to {out}')
    else:
        p.error('Use --callers ADDRESS or --start ADDRESS --end ADDRESS --output FILE')
