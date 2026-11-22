"""Derive the 8-stage internal route template from the verified 16-stage one.

The 16-stage template (../../layout/internal_route_template.tcl) fixes, per
chain, the entrance-gate output, every buffer/inverter/mux output of stages
0..14 and the buffer/inverter outputs of stage 15. The last mux output is left
to the router because it leaves the macro (arbiter D/clock and cross feedback).

Every routed net is local (a stage feeds the slice directly above it), so the
8-stage template is the same records for stages 0..6 plus the buffer/inverter
of stage 7:  2 chains x (1 + 7*3 + 2) = 48 records.

    python xor6/layout/make_route_template8.py
"""
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]/'layout'/'internal_route_template.tcl'
TARGET = HERE/'internal_route_template8.tcl'
N_STAGES = 8

keep = []
for line in SOURCE.read_text().splitlines():
    if not line.strip():
        continue
    side, rest = line.split(' ', 1)
    m = re.match(r'\{?gen_elem\[(\d+)\]\.u_elem/gen_style_p\.u_(buf|inv|mux)/O\}?', rest)
    if 'u_head_gate/O' in rest.split(' ', 1)[0]:
        keep.append(line)
    elif m:
        stage, kind = int(m[1]), m[2]
        if stage < N_STAGES - 1 or (stage == N_STAGES - 1 and kind in ('buf', 'inv')):
            keep.append(line)
expected = 2*(1 + 3*(N_STAGES - 1) + 2)
if len(keep) != expected:
    raise SystemExit(f'Expected {expected} records, got {len(keep)}')
TARGET.write_text('\n'.join(keep) + '\n')
print('Wrote', TARGET.name, 'with', len(keep), 'records')
