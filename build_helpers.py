#!/usr/bin/env python3
"""Build auditable ARM helpers from source; never connects to a device."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    (ROOT/'run').mkdir(exist_ok=True)
    for source in sorted(ROOT.glob('ram_*.S')):
        output=ROOT/'run'/(source.stem.replace('_','-')+'.o')
        subprocess.run(['clang','--target=arm-none-eabi','-mcpu=cortex-m33','-mthumb','-c',str(source),'-o',str(output)],check=True)
        print(output.name)
