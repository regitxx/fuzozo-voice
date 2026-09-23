"""Read-only snapshot of the published 1.0.42 signatures and registry state."""
import argparse
import json
from fuzozo_console import Console
from bkreg_probe import DebugReader
from ram_wav_transfer import SIGNATURES, SLOT, ORIGINAL_SLOT, SCRATCH, SCRATCH_SIZE
from mic_stream import CODE,SIZE
from mic_capture import CALLBACK, CALLBACK_SIGNATURE


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',required=True);a=p.parse_args()
    with Console(a.port) as c:
        reader=DebugReader(c);reader.link();rows=[]
        for address,expected in {**SIGNATURES,CALLBACK & ~1:CALLBACK_SIGNATURE}.items():
            actual=reader.read_image(address,(len(expected)+3)//4)[:len(expected)]
            rows.append({'address':hex(address),'expected':expected.hex(),'actual':actual.hex(),'matches':actual==expected})
        registry={'entry':reader.read_ram(SLOT).hex(),'expected_entry':ORIGINAL_SLOT.to_bytes(4,'little').hex(),
                  'scratch_clear':reader.read_ram(SCRATCH,SCRATCH_SIZE//4)==bytes(SCRATCH_SIZE),
                  'mic_scratch_clear':reader.read_ram(CODE,SIZE//4)==bytes(SIZE)}
        report={'firmware_profile':'FZ1012 1.0.42','signatures':rows,'registry':registry,'writes_performed':False}
        path=c.folder/'profile.json';path.write_text(json.dumps(report,indent=2)+'\n')
        print('Read-only profile report:',path)
        print('Signature comparison:',all(r['matches'] for r in rows))
if __name__=='__main__':main()
