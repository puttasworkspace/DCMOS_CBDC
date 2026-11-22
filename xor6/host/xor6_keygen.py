"""PUF key K for the keyed hash: enrollment and reconstruction (host side, staged version).

Key cores run a FIXED, PUBLIC set of configurations ("key rounds"); the secret
is how this particular chip answers them. Steps:

 1. matrix       write the key-round matrix (public)
                     python xor6_keygen.py matrix --rounds 8 --out key_matrix.json
 2. collect      run it on the board, several trials, many votes
                     python xor6_collect.py --matrix key_matrix.json --port COM5 --trials 5 --votes 31 --out key_enroll.csv
 3. enroll       keep only bits that were stable in every trial and every vote
                 (dark-bit mask), split into 31-bit blocks, code-offset BCH(31,16,3)
                 helper data (repo's DodisCodeOffsetFuzzyExtractor), K = SHAKE256(secrets)
                     python xor6_keygen.py enroll --capture key_enroll.csv --helper helper.json --key-out key.bin
 4. reconstruct  later / after power-up: new capture + public helper -> same K
                     python xor6_keygen.py reconstruct --capture key_check.csv --helper helper.json --key-out key_check.bin

helper.json is public (mask, BCH offsets, a key check value). key.bin is SECRET.
In this staged version K lives on the PC; the next stage moves this into RTL.
The entropy figures printed are ESTIMATES from bias only; bits from the same
8-stage core are correlated, so real entropy is lower. Standard library only.
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # bundled runtime/python ignores the script folder

import argparse
import collections
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'scripts'))
from crypto_engine import DodisCodeOffsetFuzzyExtractor as FE  # noqa: E402  (repo BCH(31,16,3) code-offset)

from kmac import shake256                                       # noqa: E402
from xor6_protocol import CORES, make_odd, hex_to_bits           # noqa: E402

TAG_CFG, TAG_KEY, TAG_CHECK = b'CBDC-XOR6 key configs', b'CBDC-XOR6 key', b'CBDC-XOR6 key check'
BLOCK = 31


def key_configs(rounds):
    return [[make_odd(shake256(TAG_CFG + bytes([r, k]), 1)[0]) for k in range(CORES)] for r in range(rounds)]


def matrix_id(cfgs):
    return hashlib.sha256(json.dumps(cfgs).encode()).hexdigest().upper()


def read_capture(path, rounds):
    """Return {(round, core): [(majority, unanimous) per trial]} after checking the configs."""
    expected = key_configs(rounds)
    obs = collections.defaultdict(list)
    with Path(path).open(newline='') as f:
        for row in csv.DictReader(f):
            r = int(row['pattern'])
            if r >= rounds:
                sys.exit(f'capture has pattern {r} but helper/rounds expect {rounds}')
            if list(bytes.fromhex(row['configs_hex'])) != expected[r]:
                sys.exit(f'round {r}: capture configs are not the public key configs (wrong matrix?)')
            maj, una = hex_to_bits(row['majority_hex'], CORES), hex_to_bits(row['unanimous_hex'], CORES)
            if not any(maj) and not any(una):
                sys.exit('capture has no per-core bits: build with EXPOSE_CORE_BITS=1 for key enrollment')
            for k in range(CORES):
                obs[r, k].append((maj[k], una[k]))
    missing = [(r, k) for r in range(rounds) for k in range(CORES) if (r, k) not in obs]
    if missing:
        sys.exit(f'capture is missing {len(missing)} key bits')
    return obs


def bits_to_blocks(bits):
    n = len(bits)//BLOCK
    return [sum(b << i for i, b in enumerate(bits[j*BLOCK:(j + 1)*BLOCK])) for j in range(n)]


def derive_key(secrets16):
    k = shake256(TAG_KEY + b''.join(s.to_bytes(2, 'big') for s in secrets16), 32)
    return k, shake256(TAG_CHECK + k, 8).hex().upper()


def min_entropy(p):
    q = max(p, 1 - p)
    return 0.0 if q >= 1 else -math.log2(q)


def enroll(a):
    obs = read_capture(a.capture, a.rounds)
    trials = min(len(v) for v in obs.values())
    if trials < 3:
        print('WARNING: fewer than 3 trials per key bit; stability mask will be weak')
    positions, bits = [], []
    for r in range(a.rounds):
        for k in range(CORES):
            v = obs[r, k]
            if all(u for _, u in v) and len({m for m, _ in v}) == 1:
                positions.append([r, k])
                bits.append(v[0][0])
    blocks = bits_to_blocks(bits)
    if not blocks:
        sys.exit('not enough stable bits for one 31-bit block; add rounds')
    used = len(blocks)*BLOCK
    positions = positions[:used]
    secrets16, helpers = [], []
    for w in blocks:
        s, h = FE.generate(w)
        secrets16.append(s)
        helpers.append(h)
    key, check = derive_key(secrets16)

    # Bias-only entropy estimate of the selected bits (per-core bias over its key rounds).
    per_core = collections.defaultdict(list)
    for (r, k), v in obs.items():
        per_core[k].append(v[0][0])
    est = sum(min_entropy(sum(per_core[k])/len(per_core[k])) for _, k in positions)
    residual = est - 15*len(blocks)
    helper = dict(format='xor6-helper-v1', rounds=a.rounds, key_configs_sha256=matrix_id(key_configs(a.rounds)),
                  positions=positions, block_bits=BLOCK, blocks=len(blocks), helpers=[f'{h:08X}' for h in helpers],
                  key_check=check, enrollment_trials=trials,
                  stats=dict(key_bits=a.rounds*CORES, stable_bits=len(bits), used_bits=used,
                             bias_entropy_estimate_bits=round(est, 1),
                             after_helper_leakage_estimate_bits=round(residual, 1)),
                  note='Public. Entropy figures are bias-only estimates; correlations between rounds of the same core lower them.')
    for p in (a.helper, a.key_out):
        if p.exists():
            sys.exit(f'{p} exists; refusing to overwrite')
    a.helper.parent.mkdir(parents=True, exist_ok=True)
    a.key_out.parent.mkdir(parents=True, exist_ok=True)
    a.helper.write_text(json.dumps(helper, indent=1) + '\n')
    a.key_out.write_bytes(key)
    print(f'Enrolled: {len(bits)}/{a.rounds*CORES} stable bits, {len(blocks)} BCH blocks, key check {check}')
    print(f'Bias-only entropy estimate {est:.0f} bits; after helper leakage ~{residual:.0f} bits '
          f'({"OK" if residual >= 128 else "BELOW 128: add rounds"}; real value is lower, see note)')
    print(f'SECRET key written to {a.key_out}; public helper data to {a.helper}')


def reconstruct(a):
    helper = json.loads(a.helper.read_text())
    if helper.get('format') != 'xor6-helper-v1':
        sys.exit('not an xor6 helper file')
    obs = read_capture(a.capture, helper['rounds'])
    secrets16, errors = [], 0
    bits = []
    for r, k in helper['positions']:
        v = [m for m, _ in obs[r, k]]
        bits.append(int(2*sum(v) > len(v)))          # majority over this capture's trials
    for j, w in enumerate(bits_to_blocks(bits)):
        s, e, ok = FE.reproduce(w, int(helper['helpers'][j], 16))
        if not ok:
            sys.exit(f'block {j}: more errors than BCH(31,16,3) can correct; key NOT recovered')
        secrets16.append(s)
        errors += e
    key, check = derive_key(secrets16)
    if check != helper['key_check']:
        sys.exit('reconstructed key does not match the enrolled key check value')
    if a.key_out:
        if a.key_out.exists():
            sys.exit(f'{a.key_out} exists; refusing to overwrite')
        a.key_out.write_bytes(key)
    print(f'Key reconstructed and verified ({errors} bit errors corrected in {len(secrets16)} blocks), check {check}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('matrix')
    m.add_argument('--rounds', type=int, default=8)
    m.add_argument('--out', type=Path, required=True)
    e = sub.add_parser('enroll')
    e.add_argument('--capture', type=Path, required=True)
    e.add_argument('--rounds', type=int, default=8)
    e.add_argument('--helper', type=Path, required=True)
    e.add_argument('--key-out', type=Path, required=True)
    r = sub.add_parser('reconstruct')
    r.add_argument('--capture', type=Path, required=True)
    r.add_argument('--helper', type=Path, required=True)
    r.add_argument('--key-out', type=Path)
    a = ap.parse_args()
    if a.cmd == 'matrix':
        if not 1 <= a.rounds <= 128:
            ap.error('rounds must be 1..128')
        if a.out.exists():
            ap.error(f'{a.out} exists')
        a.out.parent.mkdir(parents=True, exist_ok=True)
        rows = [dict(pattern=i, challenge_hex=format(i, '016X'), configs=c) for i, c in enumerate(key_configs(a.rounds))]
        a.out.write_text(json.dumps(dict(format='xor6-matrix-v1', mode='key', cores=CORES, patterns=rows)) + '\n')
        print(f'Wrote {a.rounds} public key rounds to {a.out}')
    elif a.cmd == 'enroll':
        enroll(a)
    else:
        reconstruct(a)


if __name__ == '__main__':
    main()
