#!/usr/bin/env python3
"""Independently decrypt and CRC-check a private authenticated BLE capture.

Uses PyCryptodome rather than the Swift client's CommonCrypto. Prints only
command numbers and verification counts, never key material or payloads.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from Crypto.Cipher import AES

def crc16(data):
    crc=65535
    for b in data:
        crc^=b
        for _ in range(8): crc=(crc>>1)^(0xa001 if crc&1 else 0)
    return crc

def verify(capture,record):
    local=record['localKey'][:6].encode()
    login=hashlib.md5(local).digest(); session=None
    pending=bytearray(); expected=0; total=0; commands=[]
    for event in capture['events']:
        if event['type']!='notification': continue
        packet=bytes.fromhex(event['hex']); pos=0
        def varint():
            nonlocal pos
            result=0
            for shift in range(0,28,7):
                b=packet[pos];pos+=1;result|=(b&127)<<shift
                if not b&128:return result
            raise ValueError('Oversized varint')
        index=varint()
        if index==0:
            if pending: raise ValueError('Incomplete previous frame')
            total=varint()
            if not 33<=total<=4096 or packet[pos]>>4!=4: raise ValueError('Bad header')
            pos+=1;expected=0
        if index!=expected: raise ValueError('Fragment gap')
        expected+=1;pending.extend(packet[pos:])
        if len(pending)>total:raise ValueError('Overflow')
        if len(pending)<total:continue
        frame=bytes(pending);pending.clear()
        mode=frame[0]
        if mode not in (4,5):raise ValueError('Unexpected encryption mode')
        key=login if mode==4 else session
        if key is None:raise ValueError('Missing session')
        plain=AES.new(key,AES.MODE_CBC,frame[1:17]).decrypt(frame[17:])
        seq,ack,cmd,length=struct.unpack('>IIHH',plain[:12])
        end=12+length
        if end+2>len(plain) or crc16(plain[:end])!=int.from_bytes(plain[end:end+2],'big'):
            raise ValueError('CRC or length mismatch')
        padding=plain[end+2:]
        if padding != bytes([len(padding)])*len(padding):raise ValueError('Invalid PKCS7 reply padding')
        payload=plain[12:end]
        if cmd==0:
            if len(payload)<46 or payload[2]!=4 or not payload[5]:raise ValueError('Unexpected identity response')
            session=hashlib.md5(local+payload[6:12]).digest()
        commands.append(cmd)
    if pending:raise ValueError('Truncated final frame')
    return {'verified_frames':len(commands),'commands':commands,'all_crc_valid':True}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture');p.add_argument('records')
    args=p.parse_args();records=json.loads(Path(args.records).read_text())
    if len(records)!=1:raise ValueError('Expected exactly one verified target')
    print(json.dumps(verify(json.loads(Path(args.capture).read_text()),records[0])))
