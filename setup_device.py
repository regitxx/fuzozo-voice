#!/usr/bin/env python3
"""Read-only identity probe and explicit enrollment for another FZ1012."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import time
import serial
from serial.tools import list_ports
from fuzozo_console import ROOT


def parse_identity(data):
    values = {re.sub(rb'[^0-9a-f]', b'', value.lower()).decode()
              for value in re.findall(rb'get mac:\s*((?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}|[0-9a-fA-F]{12})', data)}
    if len(values) != 1:
        raise ValueError('Expected exactly one MAC in the macaddr get reply')
    return values.pop()


def inspect(port):
    matches=[p for p in list_ports.comports() if p.device==port and (p.vid,p.pid)==(0x1a86,0x7523)]
    if len(matches)!=1: raise ValueError('Expected an explicit CH340 USB serial port')
    (ROOT/'run').mkdir(exist_ok=True)
    with (ROOT/'run/console.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        c=serial.Serial(port=None,baudrate=460800,timeout=.1,write_timeout=2)
        try:
            c.dtr=False; c.rts=False; c.port=port; c.open()
            def query(command):
                c.reset_input_buffer(); c.write(command+b'\r\n'); end=time.monotonic()+3; data=bytearray()
                while time.monotonic()<end:
                    data.extend(c.read(8192))
                    if len(data)>200_000: raise ValueError('Reply exceeded bounded size')
                return bytes(data)
            mac=parse_identity(query(b'macaddr get'))
            version=re.search(rb'USER_SW_VER:([\d.]+)',query(b'devget version'))
            if not version: raise ValueError('No firmware version reply; wake robot and retry')
            return {'model':'FZ1012','mac':mac,'firmware':version[1].decode()}
        finally:
            c.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--mac',help='Explicitly enroll this previously inspected MAC after physically identifying your FZ1012')
    args=p.parse_args(); os.umask(0o077)
    destination=ROOT/'run/device.json'
    if args.mac and destination.exists(): p.error('Already enrolled; back up/remove run/device.json explicitly to change robot')
    target=inspect(args.port)
    print(json.dumps(target,indent=2))
    if not args.mac:
        print('Read-only probe. Confirm the physical FZ1012 and repeat with --mac to enroll. No device settings changed.')
        return
    if not re.fullmatch(r'(?:[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})',args.mac): p.error('Invalid --mac')
    if re.sub('[^0-9a-f]','',args.mac.lower())!=target['mac']: p.error('MAC mismatch; nothing enrolled')
    if target['firmware']!='1.0.42': p.error('Unsupported firmware; do not change signatures to bypass this check')
    with destination.open('x') as f: json.dump(target,f,indent=2); f.write('\n')
    print('Enrolled locally. Future connections require this MAC and firmware; RAM helpers also verify live signatures.')

if __name__=='__main__': main()
