import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ram_bulk_io import BulkSession, MalformedBulkRead, CONTEXT


class ReadRecoveryTests(unittest.TestCase):
    def bulk(self, returned_offset):
        b = BulkSession.__new__(BulkSession)
        b.mode, b.length = 'get', 65536
        b.r = SimpleNamespace(read_ram=Mock(return_value=struct.pack('<I', returned_offset)))
        b.writer = SimpleNamespace(word=Mock())
        b.command = Mock(side_effect=[MalformedBulkRead('truncated'), b'ff'*80])
        return b

    def test_partial_read_retries_only_after_expected_offset(self):
        b = self.bulk(160)
        retained = Mock()
        self.assertEqual(b.read_chunk(80, 80, retained), b'\xff'*80)
        retained.assert_called_once()
        b.writer.word.assert_called_once_with(CONTEXT+8, 80)

    def test_unknown_offset_never_rewinds(self):
        b = self.bulk(200)
        with self.assertRaisesRegex(ValueError, 'unexpected helper offset'):
            b.read_chunk(80, 80)
        b.writer.word.assert_not_called()

    def test_expired_ring_never_rewinds(self):
        b = self.bulk(160)
        with self.assertRaisesRegex(ValueError, 'expired'):
            b.read_chunk(80, 80, Mock(side_effect=ValueError('expired')))
        b.writer.word.assert_not_called()


if __name__ == '__main__':
    unittest.main()
