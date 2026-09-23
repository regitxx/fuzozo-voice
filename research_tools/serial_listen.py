"""Passively record an explicitly selected CH340 port; transmits no bytes."""
import argparse
from datetime import datetime,timezone
import fcntl
import os
import time
import serial
from serial.tools import list_ports
from fuzozo_console import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',required=True)
    p.add_argument('--baud',type=int,default=460800);p.add_argument('--seconds',type=float,default=4)
    a=p.parse_args()
    if not 0<a.seconds<=30 or a.baud not in (115200,230400,460800):p.error('Use a listed baud and 0–30 seconds')
    if not any(x.device==a.port and (x.vid,x.pid)==(0x1a86,0x7523) for x in list_ports.comports()):p.error('Expected explicit CH340 port')
    os.umask(0o077);folder=ROOT/'run'/('passive-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));folder.mkdir(parents=True)
    with (ROOT/'run/console.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        c=serial.Serial(port=None,baudrate=a.baud,timeout=.1);c.dtr=False;c.rts=False;c.port=a.port
        data=bytearray()
        try:
            c.open();end=time.monotonic()+a.seconds
            while time.monotonic()<end:
                data.extend(c.read(8192))
                if len(data)>2_000_000:raise ValueError('Capture exceeded limit')
        finally:
            c.close();(folder/'serial.bin').write_bytes(data)
    print(f'Saved {len(data)} bytes privately in {folder}; transmitted zero bytes.')
if __name__=='__main__':main()
