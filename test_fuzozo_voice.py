import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import wave

import numpy as np

from fuzozo_agent import system_message
from fuzozo_voice import recognize


class VoiceBoundaryTests(unittest.TestCase):
    def clip(self, folder, level=2000):
        path = Path(folder) / 'test.wav'
        with wave.open(str(path), 'wb') as w:
            w.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            samples = (np.sin(np.arange(16000) * .1) * level).astype('<i2')
            w.writeframes(samples.tobytes())
        return path

    def model(self, text, **changes):
        fields = dict(text=text, avg_logprob=-.3, no_speech_prob=.01, compression_ratio=1.1)
        fields.update(changes)
        return SimpleNamespace(transcribe=Mock(return_value=([SimpleNamespace(**fields)], None)))

    def test_quiet_input_never_reaches_recognizer(self):
        with tempfile.TemporaryDirectory() as d:
            model = self.model('Robot, say something.')
            result = recognize(model, self.clip(d, 65))
            self.assertFalse(result['accepted'])
            model.transcribe.assert_not_called()

    def test_only_addressed_confident_speech_is_answered(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.clip(d)
            good = recognize(self.model('Hey robot, what is two plus two?'), path)
            self.assertTrue(good['accepted'])
            self.assertEqual(good['prompt'], 'what is two plus two?')
            for text in ('What is two plus two?', 'I saw a robot at work.', 'Rub it, what is two plus two?', 'Robot.'):
                self.assertFalse(recognize(self.model(text), path)['accepted'])
            self.assertFalse(recognize(self.model('Robot, what is two plus two?', no_speech_prob=.8), path)['accepted'])

    def test_wake_word_can_precede_a_separate_question(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.clip(d)
            self.assertTrue(recognize(self.model('Robot.'), path)['wake_only'])
            self.assertTrue(recognize(self.model('What is two plus two?'), path, addressed=True)['accepted'])
            self.assertFalse(recognize(self.model('What is two plus two?'), path)['accepted'])

    def test_voice_persona_describes_actual_input(self):
        msg = system_message(SimpleNamespace(SYSTEM='Persona.'), microphone=True)
        self.assertIn('robot microphone', msg['content'])
        self.assertNotIn('typed text', msg['content'])


if __name__ == '__main__':
    unittest.main()
