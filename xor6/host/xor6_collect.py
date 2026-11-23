"""Replay a challenge matrix on the board and record every reply.

    python xor6_collect.py --matrix matrix.json --port COM5 --trials 3 --votes 21 --out run.csv
    python xor6_collect.py --matrix matrix.json --model 7 --trials 3 --out dry.csv   # no hardware

--port needs pyserial (pip install pyserial). Without pyserial use the
PowerShell twin xor6_collect.ps1, which writes the same CSV format.

CSV columns (one row per query):
  utc, pattern, trial, challenge_hex, configs_hex (60 bytes), flags_hex, votes,
  excite_cycles, mode, majority_hex (60 bits), unanimous_hex (60 bits), xor_hex (10 bits)
A metadata file <out>.metadata.json records the settings, the matrix hash and,
if given, the bitstream hash from the XOR-6 BUILD_RECORD.json.
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # bundled runtime/python ignores the script folder

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from xor6_protocol import REPLY_BYTES, FLAG_OK, CORES, build_request, parse_reply, bits_to_hex

FIELDS = ['utc', 'pattern', 'trial', 'challenge_hex', 'configs_hex', 'flags_hex', 'votes', 'excite_cycles',
          'mode', 'majority_hex', 'unanimous_hex', 'xor_hex']


def open_port(args):
    if args.model is not None:
        from xor6_board_model import BoardModel
        return BoardModel(seed=args.model, noise_sd=args.model_noise, bias_sd=args.model_bias)
    try:
        import serial
    except ImportError:
        sys.exit('pyserial is not installed: pip install pyserial  (or use xor6_collect.ps1)')
    port = serial.Serial(args.port, 115200, bytesize=8, parity='N', stopbits=1, timeout=2.0, write_timeout=2.0)
    time.sleep(0.1)
    port.reset_input_buffer()
    return port


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--matrix', type=Path, required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--port', help='serial port, e.g. COM5 or /dev/ttyUSB1')
    src.add_argument('--model', type=int, help='use the software board model with this seed (dry run)')
    ap.add_argument('--model-noise', type=float, default=0.15)
    ap.add_argument('--model-bias', type=float, default=0.8)
    ap.add_argument('--trials', type=int, default=1, help='repeat each challenge (reliability)')
    ap.add_argument('--votes', type=int, default=21, help='runs per core per query, 1..63 (odd)')
    ap.add_argument('--excite-cycles', type=int, default=8)
    ap.add_argument('--sequential', action='store_true', help='one core at a time (diagnostic)')
    ap.add_argument('--build-record', type=Path, help='BUILD_RECORD.json of the programmed XOR-6 bitstream')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()

    matrix = json.loads(a.matrix.read_text())
    if matrix.get('format') != 'xor6-matrix-v1':
        sys.exit('not an xor6 matrix file')
    for p in (a.out, Path(str(a.out) + '.metadata.json')):
        if p.exists():
            sys.exit(f'{p} exists; refusing to overwrite')
    meta = dict(utc=datetime.now(timezone.utc).isoformat(), variant='xor6_array60_8stage',
                matrix=str(a.matrix), matrix_sha256=hashlib.sha256(a.matrix.read_bytes()).hexdigest().upper(),
                matrix_mode=matrix['mode'], patterns=len(matrix['patterns']), trials=a.trials, votes=a.votes,
                excite_cycles=a.excite_cycles, mode='Sequential' if a.sequential else 'Parallel',
                source=f'model seed {a.model}' if a.model is not None else f'board on {a.port}')
    if a.build_record:
        rec = json.loads(a.build_record.read_text())
        meta.update(bitstream_sha256=rec['sha256'], bitstream_variant=rec['variant'])
    if a.model is not None:
        meta['warning'] = 'SOFTWARE MODEL - not hardware data'

    a.out.parent.mkdir(parents=True, exist_ok=True)
    port = open_port(a)
    t0, n = time.time(), 0
    try:
        with a.out.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for row in matrix['patterns']:
                req = build_request(row['configs'], a.votes, a.excite_cycles, a.sequential)
                for trial in range(1, a.trials + 1):
                    port.write(req)
                    reply = port.read(REPLY_BYTES)
                    if len(reply) != REPLY_BYTES:
                        sys.exit(f'timeout at pattern {row["pattern"]} trial {trial}: got {len(reply)} bytes; '
                                 'check the port and that the XOR-6 bitstream is loaded')
                    r = parse_reply(reply, req)
                    if r['flags'] != FLAG_OK:
                        sys.exit(f'board returned flags {r["flags"]:02X} at pattern {row["pattern"]}')
                    w.writerow(dict(utc=datetime.now(timezone.utc).isoformat(), pattern=row['pattern'], trial=trial,
                                    challenge_hex=row['challenge_hex'], configs_hex=bytes(r['configs']).hex().upper(),
                                    flags_hex=f'{r["flags"]:02X}', votes=a.votes, excite_cycles=a.excite_cycles,
                                    mode=meta['mode'], majority_hex=bits_to_hex(r['majority']),
                                    unanimous_hex=bits_to_hex(r['unanimous']), xor_hex=bits_to_hex(r['xor'])))
                    n += 1
                if row['pattern'] % 500 == 499:
                    f.flush()
                    print(f'{row["pattern"] + 1} patterns, {n} queries, {time.time() - t0:.0f} s', flush=True)
    finally:
        port.close()
    meta['queries'] = n
    Path(str(a.out) + '.metadata.json').write_text(json.dumps(meta, indent=2) + '\n')
    print(f'Saved {n} queries ({n*CORES} core bits, {n*10} XOR bits) to {a.out} in {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
