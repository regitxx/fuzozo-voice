"""Fetch exactly indexed upstream C files and verify their Git blob hashes."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import httpx
ROOT=Path(__file__).resolve().parents[1]


def check_blob(data, sha):
    actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if actual!=sha:raise ValueError('Upstream Git blob hash mismatch')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'run/references');a=p.parse_args()
    manifest=json.loads((ROOT/'docs/reference-sources.json').read_text())
    with httpx.Client(timeout=30,trust_env=False,follow_redirects=False) as client:
        for row in manifest['files']:
            relative=PurePosixPath(row['repository'])/row['path']
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid reference path')
            dest=a.output.joinpath(*relative.parts)
            if dest.exists():check_blob(dest.read_bytes(),row['git_blob_sha']);continue
            url='https://api.github.com/repos/'+row['repository']+'/git/blobs/'+row['git_blob_sha']
            response=client.get(url);response.raise_for_status();blob=response.json()
            if blob.get('encoding')!='base64' or blob.get('sha')!=row['git_blob_sha']:raise ValueError('Unexpected upstream blob')
            data=base64.b64decode(blob['content']);check_blob(data,row['git_blob_sha'])
            dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as f:f.write(data)
            print(relative)
    print('All indexed references verified. Preserve upstream licensing; these are not build dependencies.')
if __name__=='__main__':main()
