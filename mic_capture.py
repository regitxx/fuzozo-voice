#!/usr/bin/env python3
"""Bounded 1.0.42 microphone capture via a temporary, forwarding RAM callback.

Captures the first PCM16 channel from the existing stereo recorder stream.
Restores the original callback and scratch before downloading audio. Does not
change the dump UART or flash firmware. Keep the robot awake throughout.
"""
import argparse
import json
import re
import struct
import time
import wave
from pathlib import Path

from fuzozo_console import Console, ROOT
from bkreg_probe import DebugReader
from ram_wav_transfer import SCRATCH, SCRATCH_SIZE, ScopedWriter, elf_text

CONTEXT = SCRATCH + 128
RECORDER_GLOBAL = 0x280180b8
CALLBACK = 0x021895e5
CALLBACK_SIGNATURE = bytes.fromhex('f8b53a4a3a4e13680446307801330228')


def read_psram(reader, address, words):
    if address % 4 or not 1 <= words <= 64 or not 0x60000000 <= address < address + words*4 <= 0x60800000:
        raise ValueError('Invalid bounded recorder/allocated-buffer read')
    return reader._read_words(address, words)


def capture(console, seconds=3, on_record=None, channel=0, stimulus_path=None):
    if not 1 <= seconds <= 4:
        raise ValueError('Bench recording must be one to four seconds')
    if channel not in (0,1):
        raise ValueError('Choose recorder channel 0 or 1')
    r = DebugReader(console)
    if r.read_image(CALLBACK & ~1, 4) != CALLBACK_SIGNATURE:
        raise ValueError('Microphone callback firmware signature changed')
    if r.read_image(0x2186dec,4).hex() != 'f8b51d465b682c4e93f90030312b47d1':
        raise ValueError('Microphone command firmware signature changed')
    if r.read_ram(0x28017ff8) != bytes(4):
        raise ValueError('Dump UART configured; do not disturb it')
    if r.read_ram(0x2802f630) != struct.pack('<I',137):
        raise ValueError('CLI registry size changed')
    original_scratch = r.read_ram(SCRATCH, SCRATCH_SIZE//4)
    if original_scratch != bytes(SCRATCH_SIZE):
        raise ValueError('Scratch is not unused')
    recorder = int.from_bytes(r.read_ram(RECORDER_GLOBAL), 'little')
    metadata = read_psram(r, recorder, 22)
    callback_slot = recorder + 0x50
    if struct.unpack_from('<I',metadata,0x50)[0] != CALLBACK:
        raise ValueError('Recorder callback is not the expected original')
    # Only start from the observed idle stream, so restoring OFF preserves it.
    count1 = r.read_ram(0x28018004)
    time.sleep(.1)
    if r.read_ram(0x28018004) != count1:
        raise ValueError('Factory microphone stream is already active; leave it untouched')
    capacity = int(seconds * 32000)
    reply = console.exchange(f'psram_malloc {capacity}', .5, 'allocate-mic-buffer')
    match = re.search(rb'psram_malloc ret\((?:0x)?([0-9a-fA-F]+)\)',reply)
    if not match:
        raise ValueError('No microphone buffer allocation result')
    buffer = int(match[1],16)
    writer = ScopedWriter(r,buffer,capacity)
    writer.ranges = [(buffer,buffer+capacity),(SCRATCH,SCRATCH+SCRATCH_SIZE),(callback_slot,callback_slot+4)]
    code = elf_text(ROOT/'run/ram-mic-tap.o')
    if len(code)>128:
        raise ValueError('Microphone tap too large')
    scratch = bytearray(SCRATCH_SIZE)
    scratch[:len(code)] = code
    struct.pack_into('<8I',scratch,128,buffer,capacity,0,CALLBACK,1,0,0,channel*2)
    report = {'seconds_requested':seconds,'callback_restored':False,'scratch_restored':False,
              'bytes_captured':0,'recorder':hex(recorder),'buffer':hex(buffer),'channel':channel}
    report_path = console.folder/'mic-result.json'
    def save():report_path.write_text(json.dumps(report,indent=2)+'\n')
    borrowed = installed = started = False
    restored = False
    failure = None
    try:
        borrowed = True
        writer.block(SCRATCH,bytes(scratch))
        if r.read_ram(SCRATCH,SCRATCH_SIZE//4)!=scratch:
            raise IOError('Microphone helper readback mismatch')
        installed = True
        writer.word(callback_slot,SCRATCH|1)
        if read_psram(r,callback_slot,1)!=struct.pack('<I',SCRATCH|1):
            raise IOError('Microphone callback registration mismatch')
        print('RECORDING NOW: speak near Fuzozo for '+str(seconds)+' seconds.',flush=True)
        started = True
        if on_record is not None:
            on_record()
        if stimulus_path is None:
            console.exchange('mic_set 1 0 x', seconds+.4, 'mic-capture-start')
        else:
            # Bench-only acoustic loopback: start capture before the existing
            # validated player, through the same exclusive serial owner.
            console.exchange('mic_set 1 0 x', .2, 'mic-capture-start')
            report['stimulus_playback'] = console.play(stimulus_path)
        console.exchange('mic_set 0', .7, 'mic-capture-stop')
        started = False
        values = struct.unpack('<7I',r.read_ram(CONTEXT,7))
        report.update(bytes_captured=values[2],callback_calls=values[5])
        if not 0 < values[2] <= capacity or values[2]%4:
            raise IOError('Microphone returned no valid complete samples')
    except BaseException as error:
        failure = error
    finally:
        if not r.session_invalidated and not console.session_invalidated:
            if started:
                console.exchange('mic_set 0', .7, 'mic-stop-after-error')
            if installed:
                writer.word(CONTEXT+16,0)
                writer.word(callback_slot,CALLBACK)
                report['callback_restored'] = read_psram(r,callback_slot,1)==struct.pack('<I',CALLBACK)
                time.sleep(.1)
                if r.read_ram(CONTEXT+24)!=bytes(4):
                    raise IOError('Capture helper still in flight; keep its RAM allocated')
            else:
                report['callback_restored'] = True
            if borrowed and report['callback_restored']:
                writer.block(SCRATCH,original_scratch)
                report['scratch_restored'] = r.read_ram(SCRATCH,SCRATCH_SIZE//4)==original_scratch
            restored = report['callback_restored'] and report['scratch_restored']
        else:
            report['session_invalidated'] = True
        save()
    if not restored:
        raise IOError('Microphone helper restoration not verified')
    if failure is not None:
        console.exchange(f'psram_free {buffer:#x}', .5, 'free-mic-buffer-after-error')
        raise failure
    data = bytearray()
    try:
        from ram_bulk_io import BulkSession
        start = time.monotonic()
        with BulkSession(r,buffer,report['bytes_captured'],'get') as bulk:
            data.extend(bulk.get())
        report['download_seconds'] = round(time.monotonic()-start,2)
    finally:
        if not r.session_invalidated and not console.session_invalidated:
            console.exchange(f'psram_free {buffer:#x}',.5,'free-mic-buffer')
    path = console.folder/'microphone.wav'
    with wave.open(str(path),'wb') as audio:
        audio.setparams((1,2,16000,0,'NONE','not compressed'))
        audio.writeframes(data)
    report['wav'] = str(path)
    save()
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--seconds',type=int,default=3)
    args=p.parse_args()
    with Console(args.port) as c:
        print(json.dumps({'captures':str(c.folder)}),flush=True)
        print(json.dumps(capture(c,args.seconds)),flush=True)
