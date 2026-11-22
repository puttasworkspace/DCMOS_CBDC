"""Write BUILD_RECORD.json for a finished XOR-6 stage (run inside the stage folder).

The record ties the bitstream hash to the exact sources, layout, route template
and audit evidence. The collector refuses to run against a different bitstream.
"""
from pathlib import Path
import hashlib
import json
import sys

root = Path(__file__).resolve().parents[1]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest().upper()

summary = json.loads((root/'build/route_summary.json').read_text())
if summary['mismatched'] or summary['paired_internal_arcs'] != summary['expected']:
    sys.exit('Route matching not accepted')
structure = (root/'build/structure.txt').read_text()
if structure.count(' PASS:') != 60:
    sys.exit('Structural audit incomplete')
exposed = not any(l.strip() == 'set EXPOSE_CORE_BITS 0' for l in (root/'scripts/params.tcl').read_text().splitlines())
bit = root/'build/xor6_array60.bit'
if not bit.is_file():
    sys.exit('Bitstream missing')

files = [*sorted((root/'rtl').glob('*.v')), root/'basys3_xor6.xdc', root/'layout.tcl', root/'layout.json',
         root/'internal_route_template.tcl', *sorted((root/'scripts').glob('*')),
         root/'build/route_summary.json', root/'build/paired_arcs.csv', root/'build/structure.txt',
         root/'build/drc_final.rpt', root/'build/utilization_final.rpt', root/'build/timing_refined.rpt']
record = dict(
    variant='xor6_array60_8stage', part='xc7a35tcpg236-1', cores=60, stages=8, groups=10, group_size=6,
    bitstream='build/xor6_array60.bit', sha256=sha(bit), core_bits_exposed=exposed,
    protocol=dict(request_header='A7', reply_header='D7', request_bytes=64, reply_bytes=83,
                  configuration_bits=480, response_bits=10, votes_per_core='1..63'),
    paired_internal_arcs=summary['paired_internal_arcs'],
    files={str(p.relative_to(root)).replace('\\', '/'): sha(p) for p in files if p.is_file()},
    limitations=['8-stage macros reuse the 16-stage three-LUT stage and odd-parity restriction.',
                 'Net-delay matching and digital simulation do not establish analog symmetry, bias, entropy, reliability or security.',
                 'Keyed hash and key generation run on the host in this staged version.'])
(root/'BUILD_RECORD.json').write_text(json.dumps(record, indent=2) + '\n')
print('Recorded XOR-6 build', record['sha256'])
