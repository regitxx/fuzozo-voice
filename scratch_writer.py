"""Constrain temporary volume-helper writes to the borrowed CLI memory."""
from ram_wav_transfer import SCRATCH, SCRATCH_SIZE, SLOT, ScopedWriter

class ScratchWriter(ScopedWriter):
    def __init__(self, reader):
        self.reader = reader
        self.ranges = [(SCRATCH, SCRATCH+SCRATCH_SIZE), (SLOT, SLOT+4)]
