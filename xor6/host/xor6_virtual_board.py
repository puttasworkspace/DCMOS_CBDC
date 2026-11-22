"""Serve the software board model on a serial port, to test a collector without
hardware (needs pyserial). Pair two ports with a null-modem tool (Linux:
`socat -d -d pty,raw,echo=0 pty,raw,echo=0`; Windows: com0com), then:

    python xor6_virtual_board.py --port /dev/pts/5 --seed 7
    python xor6_collect.py --matrix m.json --port /dev/pts/6 --out test.csv

A MODEL, NOT HARDWARE. Stops after --idle seconds without traffic.
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # bundled runtime/python ignores the script folder

import argparse
import time

import serial

from xor6_board_model import BoardModel
from xor6_protocol import REQUEST_BYTES, xor_all


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', required=True)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--idle', type=float, default=20.0)
    ap.add_argument('--noise', type=float, default=0.15, help='per-run noise (0 = deterministic)')
    ap.add_argument('--hide-core-bits', action='store_true')
    a = ap.parse_args()
    board = BoardModel(seed=a.seed, noise_sd=a.noise, expose_core_bits=not a.hide_core_bits)
    port = serial.Serial(a.port, 115200, timeout=0.2)
    buf, last, served = bytearray(), time.time(), 0
    while time.time() - last < a.idle:
        chunk = port.read(256)
        if chunk:
            buf += chunk
            last = time.time()
        while buf:
            if buf[0] != 0xA7:          # resynchronise like the RTL parser
                del buf[0]
                continue
            if len(buf) < REQUEST_BYTES:
                break
            req = bytes(buf[:REQUEST_BYTES])
            del buf[:REQUEST_BYTES]
            if req[-1] == xor_all(req[:-1]):
                port.write(board.respond(req))
                served += 1
    print(f'virtual board served {served} requests')


if __name__ == '__main__':
    main()
