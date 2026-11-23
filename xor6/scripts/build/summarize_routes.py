"""Merge the four delay-audit shards and check upper/lower route matching.

Every internal arc of the upper chain must have exactly the same modeled delay
(slow and fast corner) as the matching arc of the lower chain. The script lists
any mismatched arcs (core, stage, kind) so refine_routes.tcl can be extended,
and exits non-zero if matching is incomplete. Run inside the stage folder:

    python scripts/summarize_routes.py
"""
from pathlib import Path
import collections
import csv
import json
import re
import sys

N_STAGES, CORES = 8, 60
root = Path(__file__).resolve().parents[1]
audit, build = root/'build'/'audit', root/'build'

rows, seen = [], set()
for i in range(4):
    done = list(map(int, (audit/f'net_delays_shard_{i}.complete').read_text().split()))
    rr = list(csv.DictReader((audit/f'net_delays_shard_{i}.csv').open(newline='')))
    if done[0] != i or done[2] != len(rr):
        sys.exit(f'Incomplete shard {i}')
    for row in rr:
        key = (row['driver'], row['sink'])
        if key in seen:
            sys.exit('Duplicate shard arc')
        seen.add(key)
    rows += rr
with (build/'net_delays.csv').open('w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

groups, boundaries = {}, collections.defaultdict(list)
for row in rows:
    source, target = row['driver'], row['sink']
    if 'u_arbiter_dff/' in target or 'u_head_gate/I0' in target or 'u_head_gate/I1' in target:
        m = re.search(r'gen_core\[(\d+)\]', source)
        if m:
            boundaries[int(m[1])].append(row)
    if not (source.endswith('u_head_gate/O') or ('gen_style_p.u_' in source and source.endswith('/O'))):
        continue
    for side in ('upper', 'lower'):
        token = 'u_chain_' + side
        if token in source and token in target:
            key = (source.replace(token, 'u_chain_PAIR'), target.replace(token, 'u_chain_PAIR'))
            groups.setdefault(key, {})[side] = row

pairs = []
for (source, target), p in sorted(groups.items()):
    if set(p) != {'upper', 'lower'}:
        sys.exit(f'Missing paired arc {source} -> {target}')
    d = dict(driver=source, sink=target)
    for corner in ('slow_max_ps', 'fast_min_ps'):
        d['upper_'+corner] = float(p['upper'][corner])
        d['lower_'+corner] = float(p['lower'][corner])
        d['difference_'+corner] = d['upper_'+corner] - d['lower_'+corner]
    pairs.append(d)

expected = CORES * 4 * N_STAGES
with (build/'paired_arcs.csv').open('w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(pairs[0]))
    w.writeheader()
    w.writerows(pairs)

mismatched = [p for p in pairs if p['difference_slow_max_ps'] or p['difference_fast_min_ps']]
by_kind = collections.Counter()
for p in mismatched:
    m = re.search(r'gen_core\[(\d+)\].*gen_elem\[(\d+)\]\.u_elem/gen_style_p\.u_(\w+)/O', p['driver'])
    by_kind[(m[2], m[3]) if m else ('head', 'gate')] += 1

skews = {}
for core in range(CORES):
    rr = boundaries[core]
    checks = {'launch': [v for v in rr if v['sink'].endswith('u_head_gate/I0')],
              'feedback': [v for v in rr if v['sink'].endswith('u_head_gate/I1')],
              'arbiter': [v for v in rr if v['sink'].endswith(('u_arbiter_dff/D', 'u_arbiter_dff/C'))]}
    if any(len(v) != 2 for v in checks.values()):
        sys.exit(f'Incomplete boundary audit: core {core}')
    skews[core] = {k: {c: abs(float(v[0][c]) - float(v[1][c])) for c in ('slow_max_ps', 'fast_min_ps')} for k, v in checks.items()}

summary = dict(paired_internal_arcs=len(pairs), expected=expected, mismatched=len(mismatched),
               mismatched_by_stage_kind={f'stage {s} {k}': n for (s, k), n in sorted(by_kind.items())},
               max_slow_skew_ps=max(abs(p['difference_slow_max_ps']) for p in pairs),
               max_fast_skew_ps=max(abs(p['difference_fast_min_ps']) for p in pairs),
               boundary_skews=skews,
               limitation='Modeled net delays; not proof of analog symmetry, entropy or hardware reliability.')
(build/'route_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print({k: v for k, v in summary.items() if k != 'boundary_skews'})
if len(pairs) != expected or mismatched:
    sys.exit('ROUTE MATCHING NOT ACCEPTED: extend refine_routes.tcl for the listed stage/kind classes and rerun')
print('ROUTE_MATCHING_ACCEPTED')
