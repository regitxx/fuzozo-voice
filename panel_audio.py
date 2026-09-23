"""Local speech rendering, complete audio segmentation, and panel previews."""
import audioop
import io
from pathlib import Path
import wave

from speech_clip import render


def wav_bytes(pcm, rate=16000):
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        w.writeframes(pcm)
    return out.getvalue()


def segment_pcm(pcm, max_frames=60800):
    """Preserve every sample; prefer a quiet boundary before the four-second cap."""
    remaining = pcm
    parts = []
    while len(remaining) > max_frames*2:
        start = max_frames-16000
        candidates = range(start, max_frames-320, 160)
        cut = min(candidates, key=lambda n: audioop.rms(remaining[n*2:(n+320)*2], 2))+160
        parts.append(remaining[:cut*2])
        remaining = remaining[cut*2:]
    if remaining:
        parts.append(remaining)
    return parts


def prepare(text, level, folder, progress=lambda *_: None, cancelled=lambda: False):
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 600:
        raise ValueError('Enter between 1 and 600 characters')
    if type(level) is not int or not 0 <= level <= 100:
        raise ValueError('Speech level must be 0–100')
    words = text.split()
    chunks = [' '.join(words[i:i+20]) for i in range(0, len(words), 20)]
    all_pcm = bytearray()
    for index, chunk in enumerate(chunks):
        if cancelled():
            raise InterruptedError('Stopped before speech generation')
        progress('synthesizing', f'Creating voice · section {index+1}/{len(chunks)}')
        source, _ = render(chunk)
        with wave.open(io.BytesIO(source), 'rb') as w:
            pcm, _ = audioop.ratecv(w.readframes(w.getnframes()), 2, 1, 24000, 16000, None)
        all_pcm.extend(pcm)
    peak = audioop.max(bytes(all_pcm), 2)
    if not peak:
        raise ValueError('The voice service returned silent audio')
    target = round(24000*level/100)
    pcm = audioop.mul(bytes(all_pcm), 2, target/peak)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    preview = folder/'preview.wav'
    preview.write_bytes(wav_bytes(pcm))
    parts = [wav_bytes(part) for part in segment_pcm(pcm)]
    return {'preview': str(preview), 'parts': parts, 'seconds': len(pcm)/32000,
            'peak': audioop.max(pcm, 2), 'level': level}
