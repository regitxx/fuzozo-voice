import hashlib
import json
import lzma
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
try:
    from research_tools.firmware_inspect import unpack_xz,disassemble,strings
    from research_tools.fetch_references import check_blob
    from research_tools.verify_ble_capture import verify,crc16
    from Crypto.Cipher import AES
    HAVE_RESEARCH=True
except ImportError:
    HAVE_RESEARCH=False

@unittest.skipUnless(HAVE_RESEARCH,'Install requirements-research.txt for research tests')
class ResearchTests(unittest.TestCase):
    def test_package_unpack_checks_format_and_bounds(self):
        data=b'\0'*64+lzma.compress(b'example image')
        self.assertEqual(unpack_xz(data),b'example image')
        with self.assertRaises(ValueError):unpack_xz(data,offset=0)
        with self.assertRaises(ValueError):unpack_xz(data,limit=3)
        with self.assertRaises(ValueError):unpack_xz(data+b'trailing')

    def test_thumb_disassembly_and_strings_with_explicit_base(self):
        data=bytes.fromhex('01207047')+b'\0prompt_wav\0'
        listing=disassemble(data,0x1000,0x1000,0x1004)
        self.assertIn('movs',listing);self.assertIn('bx',listing)
        self.assertEqual(strings(data,0x1000)[0]['address'],'0x1005')
        with self.assertRaises(ValueError):disassemble(data,0x1000,0xff0,0x1004)

    def test_upstream_git_blob_integrity(self):
        data=b'example source\n';sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        check_blob(data,sha)
        with self.assertRaises(ValueError):check_blob(data+b'changed',sha)

    def test_synthetic_encrypted_ble_reply_and_corruption(self):
        local='synthetic-key123';prefix=local[:6].encode()
        payload=bytearray(46);payload[2]=4;payload[5]=1;payload[6:12]=b'ABCDEF'
        def packet(mode,cmd,payload,key):
            body=struct.pack('>IIHH',1,0,cmd,len(payload))+payload
            body+=crc16(body).to_bytes(2,'big');n=16-len(body)%16;body+=bytes([n])*n
            frame=bytes([mode])+bytes(16)+AES.new(key,AES.MODE_CBC,bytes(16)).encrypt(body)
            self.assertLess(len(frame),128)
            return {'type':'notification','hex':(bytes([0,len(frame),0x40])+frame).hex()}
        login=hashlib.md5(prefix).digest();session=hashlib.md5(prefix+b'ABCDEF').digest()
        capture={'events':[packet(4,0,payload,login),packet(5,0x801f,b'\0',session)]}
        result=verify(capture,{'localKey':local})
        self.assertEqual(result['commands'],[0,0x801f]);self.assertTrue(result['all_crc_valid'])
        bad=json.loads(json.dumps(capture));raw=bytearray.fromhex(bad['events'][-1]['hex']);raw[-1]^=1;bad['events'][-1]['hex']=raw.hex()
        with self.assertRaises(ValueError):verify(bad,{'localKey':local})

    @unittest.skipUnless(shutil.which('swiftc'),'Xcode Swift compiler required')
    def test_swift_metadata_on_original_compiled_fixture(self):
        from research_tools.swift_metadata import MachO
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fixture.dylib'
            subprocess.run(['swiftc','-target','arm64-apple-macosx13.0','-emit-library','-module-name','Fixture','examples/MetadataFixture.swift','-o',str(path)],check=True,capture_output=True)
            records=MachO(path).types()
            found=next(row for row in records if row['name'].endswith('.RobotSettings'))
            self.assertEqual([f['name'] for f in found['fields']],['volume','muted'])
            from research_tools.macho_inspect import Inspector
            inspector=Inspector(path)
            start,_,size=inspector.sections['__text']
            self.assertTrue(inspector.disassemble(start,start+min(size,256)).strip())

if __name__=='__main__':unittest.main()
