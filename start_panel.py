#!/usr/bin/env python3
"""Start/reuse the local panel and open it in the user's browser."""
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import json

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8787'


def ready():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL+'/api/health', timeout=1) as response:
            if json.load(response).get('service') != 'fuzozo-panel-v1':
                raise RuntimeError('Port 8787 is occupied by another service')
        return True
    except OSError:
        return False


if __name__ == '__main__':
    if not ready():
        (ROOT/'run').mkdir(exist_ok=True)
        with (ROOT/'run/panel-server.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-u', str(ROOT/'panel_server.py')],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)
        (ROOT/'run/panel-server.pid').write_text(str(process.pid)+'\n')
        for _ in range(50):
            if ready():
                break
            time.sleep(.2)
        else:
            raise SystemExit('Panel could not start. See run/panel-server.log.')
    print('Fuzozo panel: '+URL)
    subprocess.run(['open', URL], check=True)
