#!/usr/bin/env python3
"""Read Swift field/type metadata from a thin little-endian 64-bit Mach-O.

Offline only. Does not load/execute the inspected binary or read process memory.
Output contains schema names and code addresses, not live account values.
"""
import argparse
import json
import struct
from pathlib import Path


class MachO:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if self.u32(0) != 0xFEEDFACF:
            raise ValueError('Expected a thin little-endian 64-bit Mach-O')
        self.segments, self.sections, self.encryption = [], {}, []
        self.chained_formats = set()
        pos = 32
        for _ in range(self.u32(16)):
            cmd, size = self.unpack('II', pos)
            if size < 8 or pos + size > len(self.data):
                raise ValueError('Invalid load command')
            if cmd == 0x19:
                vm, vmsize, off, filesize = self.unpack('QQQQ', pos + 24)
                self.segments.append((vm, off, filesize))
                for n in range(self.u32(pos + 64)):
                    s = pos + 72 + n * 80
                    name = self.data[s:s+16].split(b'\0')[0].decode()
                    addr, length, offset = self.unpack('QQI', s+32)
                    self.sections[name] = (addr, offset, length)
            elif cmd == 0x2c:
                off, length, enabled = self.unpack('III', pos + 8)
                self.encryption.append(dict(offset=off, size=length, cryptid=enabled))
            elif cmd == 0x80000034:
                fixups = self.u32(pos+8)
                starts = fixups + self.u32(fixups+4)
                for n in range(self.u32(starts)):
                    delta = self.u32(starts+4+4*n)
                    if delta:
                        self.chained_formats.add(self.unpack('H', starts+delta+6)[0])
            pos += size

    def unpack(self, fmt, pos):
        return struct.unpack_from('<'+fmt, self.data, pos)

    def u32(self, pos):
        return self.unpack('I', pos)[0]

    def offset(self, addr):
        for vm, off, size in self.segments:
            if vm <= addr < vm + size:
                return off + addr - vm
        raise ValueError(f'Unmapped address {addr:x}')

    def address(self, off):
        for vm, start, size in self.segments:
            if start <= off < start + size:
                return vm + off - start
        raise ValueError('Unmapped offset')

    def rel(self, off, indirect=False):
        delta = self.unpack('i', off)[0]
        if delta == 0:
            return None
        target = self.address(off) + (delta & ~1 if indirect else delta)
        if indirect and delta & 1:
            target = self.pointer(self.offset(target))
        return self.offset(target)

    def pointer(self, off):
        value = self.unpack('Q', off)[0]
        if self.chained_formats == {6}:
            if value >> 63:
                raise ValueError('Imported dyld binding requires symbol resolution')
            base = min(vm for vm, _, size in self.segments if size)
            return base + (value & ((1<<36)-1))
        return value

    def cstr(self, off):
        if off is None:
            return None
        end = self.data.find(b'\0', off, min(off+4096, len(self.data)))
        if end < 0:
            raise ValueError('Unterminated string')
        return self.data[off:end].decode('utf-8', errors='replace')

    def context(self, off, seen=None):
        if off is None:
            return ''
        seen = set() if seen is None else set(seen)
        if off in seen or len(seen) > 12:
            return '<recursive>'
        seen.add(off)
        kind = self.u32(off) & 31
        name = self.cstr(self.rel(off+8)) if kind in (0,3,16,17,18) else f'<context:{kind}>'
        try:
            parent = self.context(self.rel(off+4, True), seen)
        except (ValueError, struct.error):
            # Imported contexts can use dyld chained fixups. Do not interpret
            # an unresolved on-disk pointer as a normal virtual address.
            parent = '<external-context>'
        return '.'.join(x for x in (parent, name) if x)

    def typeref(self, off):
        if off is None:
            return None
        result = []
        for _ in range(1024):
            b = self.data[off]
            if b == 0:
                return ''.join(result)
            if b in (1,2):
                try:
                    target = self.rel(off+1)
                    if b == 2:
                        target = self.offset(self.pointer(target))
                    result.append('{'+self.context(target)+'}')
                except (ValueError, struct.error):
                    result.append('<unresolved-symbolic-reference>')
                off += 5
            elif 1 <= b <= 0x17:
                result.append(f'<symbolic:{b:x}>')
                off += 5
            else:
                result.append(chr(b) if 32 <= b < 127 else f'\\x{b:02x}')
                off += 1
        raise ValueError('Oversized typeref')

    def types(self):
        _, start, size = self.sections['__swift5_types']
        records = []
        for pos in range(start, start+size, 4):
            off = self.rel(pos)
            if off is None:
                continue
            kind = self.u32(off) & 31
            if kind not in (16,17,18):
                continue
            name = self.context(off)
            fields = []
            f = self.rel(off+16)
            if f is not None:
                _, stride, count = self.unpack('HHI', f+8)
                if stride < 12 or count > 10000:
                    raise ValueError(f'Bad field descriptor for {name}')
                for n in range(count):
                    row = f+16+n*stride
                    fields.append(dict(name=self.cstr(self.rel(row+8)),
                                       type=self.typeref(self.rel(row+4)),
                                       flags=self.u32(row)))
            access = self.rel(off+12)
            records.append(dict(name=name,kind=kind,
                                descriptor=hex(self.address(off)),
                                accessor=hex(self.address(access)) if access else None,
                                fields=fields))
        return records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    binary = MachO(args.binary)
    records = binary.types()
    report = dict(binary=args.binary,encryption=binary.encryption,types=records)
    path = Path(args.output)
    with path.open('x') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    path.chmod(0o600)
    print(f'Recovered {len(records)} type descriptors; saved {path}')


if __name__ == '__main__':
    main()
