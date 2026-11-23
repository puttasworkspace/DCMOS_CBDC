"""Modelling attacks and reliability for XOR-6 captures (needs numpy + scikit-learn).

    pip install numpy scikit-learn
    python xor6_attack.py --capture run.csv [--capture more.csv] --report report.json

Attacks (each against the right baseline: always guessing the most common bit):
  core        per-core logistic regression on flip-count features of that core's
              8-bit configuration, using the per-core voted bits. Shows how
              learnable a single 8-stage core is (expected: high).
  xor-visible per group: the six configurations are known (unkeyed hash, or the
              key has leaked); features = 6 x 8 flip-count features.
              Logistic regression and an MLP, over several training sizes.
  keyed       per group: the attacker sees only the 64-bit challenge (keyed hash
              intact); features = challenge bits. Logistic regression and an MLP.
Reliability (needs --trials >= 2 in the capture): how often a core's voted bit or
a group's XOR bit differs from that challenge's majority over trials, uniformity
(fraction of ones per group) and the fraction of unanimous core runs.

Use captures with many challenges (tens of thousands) for meaningful MLP results.
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # bundled runtime/python ignores the script folder

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

try:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
except ImportError:
    sys.exit('This script needs numpy and scikit-learn: pip install numpy scikit-learn')

from xor6_protocol import CORES, GROUPS, GROUP_SIZE, N_STAGES, hex_to_bits


def flip_features(cfg):
    """cfg: (n,) uint8 -> (n, 8) with phi_i = prod_{j>=i} (1 - 2*c_j)."""
    bits = ((cfg[:, None] >> np.arange(N_STAGES)) & 1).astype(np.int8)
    s = 1 - 2*bits
    return np.cumprod(s[:, ::-1], axis=1)[:, ::-1].astype(np.float32)


def load(paths):
    rows = []
    for p in paths:
        with Path(p).open(newline='') as f:
            rows += list(csv.DictReader(f))
    by_pattern = collections.OrderedDict()
    for r in rows:
        key = (r['challenge_hex'], r['configs_hex'])
        by_pattern.setdefault(key, []).append(r)
    chal, cfg, maj, xor, una, trials_maj, trials_xor = [], [], [], [], [], [], []
    for (ch, cf), rr in by_pattern.items():
        m = np.array([hex_to_bits(r['majority_hex'], CORES) for r in rr], dtype=np.int8)
        x = np.array([hex_to_bits(r['xor_hex'], GROUPS) for r in rr], dtype=np.int8)
        u = np.array([hex_to_bits(r['unanimous_hex'], CORES) for r in rr], dtype=np.int8)
        chal.append(int(ch, 16))
        cfg.append(list(bytes.fromhex(cf)))
        maj.append((2*m.sum(0) > len(rr)).astype(np.int8))
        xor.append((2*x.sum(0) > len(rr)).astype(np.int8))
        una.append(u.mean(0))
        trials_maj.append(m)
        trials_xor.append(x)
    return dict(chal=np.array(chal, dtype=np.uint64), cfg=np.array(cfg, dtype=np.uint8), maj=np.array(maj),
                xor=np.array(xor), una=np.array(una), trials_maj=trials_maj, trials_xor=trials_xor)


def split(n, test_frac, seed):
    idx = np.random.default_rng(seed).permutation(n)
    t = max(1, int(n*test_frac))
    return idx[t:], idx[:t]


def baseline(y_train, y_test):
    guess = int(y_train.mean() >= 0.5)
    return float((y_test == guess).mean())


def fit_score(kind, X, y, tr, te, seed):
    if len(set(y[tr])) < 2:
        return baseline(y[tr], y[te])
    if kind == 'lr':
        clf = LogisticRegression(max_iter=3000)
    else:
        clf = MLPClassifier((64, 64, 32), max_iter=300, early_stopping=True, random_state=seed)
    return float(clf.fit(X[tr], y[tr]).score(X[te], y[te]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--capture', action='append', required=True)
    ap.add_argument('--report', type=Path)
    ap.add_argument('--test-fraction', type=float, default=0.2)
    ap.add_argument('--sizes', default='1000,5000,20000,50000,200000', help='training sizes to try (capped by data)')
    ap.add_argument('--groups', type=int, default=GROUPS, help='attack only the first N groups (faster)')
    ap.add_argument('--no-mlp', action='store_true')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()

    d = load(a.capture)
    n = len(d['chal'])
    print(f'{n} distinct challenges loaded')
    tr_all, te = split(n, a.test_fraction, a.seed)
    sizes = sorted({min(int(s), len(tr_all)) for s in a.sizes.split(',')})
    report = dict(challenges=n, test_size=len(te), sizes=sizes)
    exposed = bool(d['maj'].any())

    # --- reliability -------------------------------------------------------
    multi = [i for i, m in enumerate(d['trials_maj']) if len(m) >= 2]
    if multi:
        core_flip = np.mean([(d['trials_maj'][i] != d['maj'][i]).mean(0) for i in multi], axis=0)
        xor_flip = np.mean([(d['trials_xor'][i] != d['xor'][i]).mean(0) for i in multi], axis=0)
        report['reliability'] = dict(patterns_with_repeats=len(multi), core_flip_rate_mean=float(core_flip.mean()),
                                     core_flip_rate_max=float(core_flip.max()), xor_flip_rate_per_group=xor_flip.round(5).tolist(),
                                     xor_flip_rate_mean=float(xor_flip.mean()))
        print(f'Reliability over {len(multi)} repeated challenges: core flip {core_flip.mean():.4f} '
              f'(max {core_flip.max():.4f}), XOR flip {xor_flip.mean():.4f}')
    report['uniformity_per_group'] = d['xor'].mean(0).round(4).tolist()
    if exposed:
        report['core_ones_fraction'] = d['maj'].mean(0).round(4).tolist()
        report['unanimous_fraction_mean'] = float(d['una'].mean())
    print('Group uniformity (fraction of ones):', ' '.join(f'{v:.2f}' for v in report['uniformity_per_group']))

    # --- attack 1: single cores ---------------------------------------------
    if exposed:
        acc, base = [], []
        for k in range(CORES):
            X, y = flip_features(d['cfg'][:, k]), d['maj'][:, k]
            acc.append(fit_score('lr', X, y, tr_all, te, a.seed))
            base.append(baseline(y[tr_all], y[te]))
        report['core_attack'] = dict(lr_mean=float(np.mean(acc)), lr_min=float(np.min(acc)), baseline_mean=float(np.mean(base)),
                                     per_core=np.round(acc, 4).tolist())
        print(f'Single-core LR: {np.mean(acc):.3f} (baseline {np.mean(base):.3f})')

    # --- attacks 2 and 3: XOR groups ---------------------------------------
    chal_bits = ((d['chal'][:, None] >> np.arange(64, dtype=np.uint64)) & np.uint64(1)).astype(np.float32)*2 - 1
    for name in ('xor-visible', 'keyed'):
        res = {}
        for size in sizes:
            tr = tr_all[:size]
            row = collections.defaultdict(list)
            for g in range(min(a.groups, GROUPS)):
                y = d['xor'][:, g]
                if name == 'xor-visible':
                    X = np.hstack([flip_features(d['cfg'][:, g*GROUP_SIZE + m]) for m in range(GROUP_SIZE)])
                else:
                    X = chal_bits
                row['baseline'].append(baseline(y[tr], y[te]))
                row['lr'].append(fit_score('lr', X, y, tr, te, a.seed))
                if not a.no_mlp:
                    row['mlp'].append(fit_score('mlp', X, y, tr, te, a.seed))
            res[size] = {k: float(np.mean(v)) for k, v in row.items()}
            print(f'{name:11s} train {size:7d}: ' + '  '.join(f'{k} {v:.3f}' for k, v in res[size].items()))
        report[name] = res

    if a.report:
        a.report.write_text(json.dumps(report, indent=2) + '\n')
        print('Report written to', a.report)


if __name__ == '__main__':
    main()
