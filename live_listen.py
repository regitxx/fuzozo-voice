"""Continuous robot audio, bounded utterance detection, and local recognition."""
import audioop
from collections import deque
from contextlib import closing
import json
import time
import wave

from mic_stream import MicRing


class Utterances:
    def __init__(self, threshold=350):
        self.threshold = threshold
        self.preroll = deque(maxlen=20)
        self.active = bytearray()
        self.loud_bytes = self.quiet_bytes = 0

    def feed(self, chunk):
        loud = audioop.rms(audioop.ulaw2lin(chunk, 2), 2) >= self.threshold
        if not self.active:
            self.preroll.append(chunk)
            self.loud_bytes = self.loud_bytes+len(chunk) if loud else 0
            if self.loud_bytes >= 240:
                self.active.extend(b''.join(self.preroll))
                self.preroll.clear()
                self.quiet_bytes = 0
            return None
        self.active.extend(chunk)
        if loud:
            self.loud_bytes += len(chunk)
            self.quiet_bytes = 0
        else:
            self.quiet_bytes += len(chunk)
        if self.quiet_bytes >= 5200 or len(self.active) >= 64000:
            completed = bytes(self.active) if self.loud_bytes >= 1600 else None
            self.active.clear()
            self.quiet_bytes = self.loud_bytes = 0
            return completed
        return None


def listen(console, model, recognize, wake_word, seconds, stopping, state_changed=None):
    detector = Utterances()
    utterance = 0
    addressed_until = 0
    ring = MicRing(console)
    try:
        with ring, closing(ring.chunks(seconds)) as chunks:
            print('LISTENING continuously: say "Robot, ...". Keep microphone enabled.', flush=True)
            if state_changed:
                state_changed('listening')
            for chunk in chunks:
                if stopping():
                    return None
                speech = detector.feed(chunk)
                if speech is None:
                    continue
                utterance += 1
                path = console.folder/f'utterance-{utterance:03d}.wav'
                pcm, _ = audioop.ratecv(audioop.ulaw2lin(speech, 2), 2, 1, 8000, 16000, None)
                with wave.open(str(path), 'wb') as out:
                    out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                    out.writeframes(pcm)
                if state_changed:
                    state_changed('recognizing')
                result = recognize(model, path, wake_word, addressed=time.monotonic() < addressed_until)
                ring.refresh_counter = True
                result['wav'] = str(path)
                path.with_suffix('.json').write_text(json.dumps(result, indent=2)+'\n')
                if result['accepted']:
                    return result
                if result.get('wake_only'):
                    addressed_until = time.monotonic()+10
                    print('Robot heard. Say your question now.', flush=True)
                print('No reply: '+result['reason']+
                      (': '+result['transcript'] if result['transcript'] else ''), flush=True)
                if state_changed:
                    state_changed('listening')
    finally:
        (console.folder/'stream-cleanup.json').write_text(json.dumps({
            'callback_and_scratch_restored': ring.restored,
            'utterances': utterance,
            'transport': 'continuous 8 kHz mu-law from robot microphone'})+'\n')
    return None
