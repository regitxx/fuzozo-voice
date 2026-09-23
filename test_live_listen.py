import audioop
import unittest
from live_listen import Utterances


class UtteranceTests(unittest.TestCase):
    def test_silence_and_short_click_do_not_trigger(self):
        d = Utterances()
        quiet = b'\xff'*80
        loud = audioop.lin2ulaw(b'\x00\x20'*80, 2)
        for part in [quiet]*30 + [loud]*4 + [quiet]*80:
            self.assertIsNone(d.feed(part))

    def test_speech_finishes_after_pause_and_detector_resets(self):
        d = Utterances()
        quiet = b'\xff'*80
        loud = audioop.lin2ulaw(b'\x00\x20'*80, 2)
        results = []
        for part in ([quiet]*30 + [loud]*60 + [quiet]*80)*2:
            value = d.feed(part)
            if value is not None:
                results.append(value)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(len(r) < 16000 for r in results))

    def test_continuous_noise_is_bounded(self):
        d = Utterances()
        loud = audioop.lin2ulaw(b'\x00\x20'*80, 2)
        results = [r for _ in range(1000) if (r := d.feed(loud)) is not None]
        self.assertEqual(len(results), 1)
        self.assertLessEqual(len(results[0]), 64000)


if __name__ == '__main__':
    unittest.main()
