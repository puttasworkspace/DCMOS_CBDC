"""Turn 64-bit challenges into the 60 per-core configurations, and write the
challenge matrix that the collectors replay on the board.

Modes
  keyed    configs = KMAC256(K, c, 60 bytes, "CBDC-XOR6 configs")   <- proposed design
  unkeyed  configs = SHAKE256("CBDC-XOR6 configs" || c)             <- paper-style public hash
  random   configs drawn at random (characterisation only)
Each byte is forced to odd parity (bit 0 flipped when needed), as the fixed-AND
cores require.

    python xor6_configs.py --mode keyed --key-file key.bin --count 20000 --out matrix.json
    python xor6_configs.py --mode unkeyed --count 20000 --out matrix_unkeyed.json

The matrix lists challenges and configurations. In keyed mode the configs are
secret-dependent: keep keyed matrices private, exactly like the key itself.
Standard library only.
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # bundled runtime/python ignores the script folder

import argparse
import json
import secrets
from pathlib import Path

from kmac import kmac256, shake256
from xor6_protocol import CORES, make_odd

CUSTOM = b'CBDC-XOR6 configs'


def configs_keyed(key, challenge):
    raw = kmac256(key, challenge.to_bytes(8, 'big'), CORES, CUSTOM)
    return [make_odd(b) for b in raw]


def configs_unkeyed(challenge):
    raw = shake256(CUSTOM + challenge.to_bytes(8, 'big'), CORES)
    return [make_odd(b) for b in raw]


def configs_random(rng=secrets):
    return [make_odd(rng.randbits(8)) for _ in range(CORES)]


def build_matrix(mode, count, key=None, seed=None):
    import random
    rng = random.Random(seed) if seed is not None else secrets.SystemRandom()
    rows = []
    for p in range(count):
        c = rng.getrandbits(64)
        if mode == 'keyed':
            cfg = configs_keyed(key, c)
        elif mode == 'unkeyed':
            cfg = configs_unkeyed(c)
        elif mode == 'random':
            cfg = [make_odd(rng.getrandbits(8)) for _ in range(CORES)]
        else:
            raise ValueError(mode)
        rows.append(dict(pattern=p, challenge_hex=format(c, '016X'), configs=cfg))
    return dict(format='xor6-matrix-v1', mode=mode, cores=CORES, patterns=rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mode', choices=('keyed', 'unkeyed', 'random'), required=True)
    ap.add_argument('--key-file', type=Path, help='32-byte key from xor6_keygen.py (keyed mode)')
    ap.add_argument('--count', type=int, default=1000)
    ap.add_argument('--seed', type=int, help='reproducible challenge sequence (testing only)')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    key = None
    if a.mode == 'keyed':
        if not a.key_file:
            ap.error('--key-file is required in keyed mode')
        key = a.key_file.read_bytes()
        if len(key) != 32:
            ap.error('key file must hold exactly 32 bytes')
    if a.out.exists():
        ap.error(f'{a.out} exists; refusing to overwrite')
    m = build_matrix(a.mode, a.count, key, a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(m) + '\n')
    print(f'Wrote {a.count} {a.mode} challenges to {a.out}')


if __name__ == '__main__':
    main()
