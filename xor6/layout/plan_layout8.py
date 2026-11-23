"""Placement plan for the XOR-6 variant: 60 CBDC macros with 8 stages each.

Same rules as ../../scripts/build/plan_compact.py (the 64-core 16-stage plan),
adapted to the shorter macro:

  - upper chain in column x, lower chain in column z (same tile type), rows
    y .. y+8 (entrance AND gate + 8 stages, one stage per slice)
  - arbiter FF at (ax, y+9) and excite driver FF at (ax, y-1), ax = (x+z)/2
  - footprints never overlap; a macro never crosses a 50-row clock region
  - minimum column separation is preferred (shortest feedback wiring)
  - no response-based tuning: the plan is chosen before any measurement

Input : ../../layout/sites.csv (exported from Vivado by the 64-core flow)
Output: layout.tcl, layout.json, placement.csv (this folder)

    python xor6/layout/plan_layout8.py           # report only
    python xor6/layout/plan_layout8.py --apply   # write the layout files
"""
from pathlib import Path
import csv
import functools
import json
import re
import sys

HERE = Path(__file__).resolve().parent
SITES = HERE.parents[1]/'layout'/'sites.csv'
N_STAGES = 8
CORES = 60
HEIGHT = N_STAGES + 1                  # entrance gate + stages
# Four macro rows per 50-row clock region: y-1 .. y+HEIGHT must stay inside it.
BANDS = [r + off for r in (0, 50, 100) for off in (1, 12, 23, 34)]

rows = [s for s in csv.DictReader(SITES.open()) if s['prohibit'].lower() not in ('1', 'true')]
sites = {tuple(map(int, re.fullmatch(r'SLICE_X(\d+)Y(\d+)', s['site']).groups())): s for s in rows}


def plan_for(limit):
    plan, used = [], set()
    for y in BANDS:
        valid = {x: sites[x, y]['tile_type'] for x in range(1, 66, 2)
                 if all((x, b) in sites for b in range(y, y + HEIGHT))}

        @functools.lru_cache(None)
        def solve(i, cm, am):
            """Max number of pairs (then min total separation) from column 2i+1 on."""
            if i >= 33:
                return (0, 0, ())
            best = solve(i + 1, cm >> 1, am >> 2)
            x = 2*i + 1
            if cm & 1 or x not in valid:
                return best
            for delta in range(1, limit//2 + 1):
                z, ax = x + 2*delta, x + delta
                if z not in valid or valid[z] != valid[x] or (cm >> delta) & 1 or (am >> delta) & 1:
                    continue
                if any((ax, b) not in sites for b in (y - 1, y + HEIGHT)):
                    continue
                n, c, p = solve(i + 1, (cm | (1 << delta)) >> 1, (am | (1 << delta)) >> 2)
                cand = (n + 1, c + 2*delta, ((x, z, ax),) + p)
                if (cand[0], -cand[1]) > (best[0], -best[1]):
                    best = cand
            return best

        for x, z, ax in solve(0, 0, 0)[2]:
            fp = {(a, b) for a in (x, z) for b in range(y, y + HEIGHT)} | {(ax, y - 1), (ax, y + HEIGHT)}
            if used & fp:
                raise ValueError('Unexpected footprint overlap')
            used |= fp
            plan.append(dict(core=len(plan), upper_x=x, lower_x=z, head_y=y, arbiter_x=ax, tile_type=valid[x]))
    return plan


for limit in (6, 8, 10, 12, 16):
    plan = plan_for(limit)
    print('Maximum separation', limit, 'gives', len(plan), 'compatible macros')
    if len(plan) >= CORES:
        break
if len(plan) < CORES:
    raise SystemExit('Insufficient short-distance pairs')

# Spread the selected macros evenly over all candidates (whole device area).
indices = [i*(len(plan) - 1)//(CORES - 1) for i in range(CORES)]
plan = [dict(plan[j], core=i) for i, j in enumerate(indices)]
print('Selected', len(plan), 'macros; max separation', max(s['lower_x'] - s['upper_x'] for s in plan),
      '; tile types', sorted({s['tile_type'] for s in plan}))

if '--apply' in sys.argv:
    (HERE/'layout.json').write_text(json.dumps(plan, indent=2) + '\n')
    (HERE/'layout.tcl').write_text('\n'.join('{%s %s %s %s %s}' % (s['upper_x'], s['lower_x'], s['head_y'], s['arbiter_x'], s['tile_type']) for s in plan) + '\n')
    with (HERE/'placement.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(plan[0]))
        w.writeheader()
        w.writerows(plan)
    print('Wrote layout.tcl / layout.json / placement.csv')
