import re
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import mic_stream as stream


class FakeBulk:
    def __init__(self, reader, buffer, length, mode, **kwargs):
        self.length = length
        self.offset = 0
        self.writer = SimpleNamespace(word=self.word)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def word(self, address, value):
        if address == stream.BULK_CONTEXT+4:
            self.length = value
        elif address == stream.BULK_CONTEXT+8:
            self.offset = value
        else:
            raise AssertionError('Unexpected write')

    def command(self, command, pattern):
        count = min(80, self.length-self.offset)
        assert count > 0
        self.offset += count
        data = b'LABHEX:' + b'ff'*count + b'\r\n'
        match = re.search(pattern, data)
        assert match, 'Host expected a different partial-block length'
        return match[1]

    def read_chunk(self, offset, count, **kwargs):
        assert self.offset == offset
        pattern = rb'LABHEX:([0-9a-f]{'+str(count*2).encode()+rb'})\r?\n'
        return bytes.fromhex(self.command('labio', pattern).decode())


class RingConsumerTests(unittest.TestCase):
    def test_partial_blocks_across_ring_boundaries(self):
        for seconds in (1, 8, 12, 20):
            produced = 0
            def read(address):
                nonlocal produced
                self.assertEqual(address, stream.CONTEXT+8)
                produced += 5120
                return struct.pack('<I', produced)
            ring = stream.MicRing.__new__(stream.MicRing)
            ring.r = SimpleNamespace(read_ram=read)
            ring.buffer = 0x60000000
            with patch.object(stream, 'BulkSession', FakeBulk):
                data = b''.join(ring.chunks(seconds))
            self.assertEqual(data, b'\xff'*(8000*seconds))

    def test_overrun_is_rejected_before_stale_audio(self):
        ring = stream.MicRing.__new__(stream.MicRing)
        ring.r = SimpleNamespace(read_ram=lambda _: struct.pack('<I', 70000))
        ring.buffer = 0x60000000
        with patch.object(stream, 'BulkSession', FakeBulk), self.assertRaisesRegex(OSError, 'overflow'):
            list(ring.chunks(12))


if __name__ == '__main__':
    unittest.main()
