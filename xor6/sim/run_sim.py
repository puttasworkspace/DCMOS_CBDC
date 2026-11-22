"""Run the XOR-6 Icarus Verilog testbenches.

Usage:
    python xor6/sim/run_sim.py                       # iverilog/vvp on PATH
    python xor6/sim/run_sim.py --icarus-bin C:/iverilog/bin
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
XOR6 = HERE.parent
ROOT = XOR6.parent
SHARED = [ROOT/'rtl'/n for n in ('cbdc_puf_element.v', 'cbdc_puf_chain.v', 'cbdc_puf_ctrl.v', 'cbdc_uart.v', 'cbdc_button.v')]
PRIMITIVES = ROOT/'sim'/'sim_unisim_primitives.v'
LOCAL = sorted((XOR6/'rtl').glob('*.v'))
TOP_FILES = [PRIMITIVES, *SHARED, *LOCAL, HERE/'tb_xor6_serial.v']
# (log name, top module, extra iverilog flags, files)
TESTS = [
    ('tb_chain8_truth', 'tb_chain8_truth', [], [PRIMITIVES, ROOT/'rtl'/'cbdc_puf_element.v', ROOT/'rtl'/'cbdc_puf_chain.v', HERE/'tb_chain8_truth.v']),
    ('tb_xor6_serial', 'tb_xor6_serial', [], TOP_FILES),
    ('tb_xor6_serial_deploy', 'tb_xor6_serial', ['-Ptb_xor6_serial.EXPOSE=0'], TOP_FILES),
]


def tool(name, folder):
    if folder:
        for candidate in (folder/(name+'.exe'), folder/name):
            if candidate.is_file():
                return str(candidate)
    found = shutil.which(name)
    if not found:
        sys.exit(f'{name} not found; install Icarus Verilog or pass --icarus-bin')
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--icarus-bin', type=Path)
    p.add_argument('--log-dir', type=Path, help='keep compile/run logs here')
    a = p.parse_args()
    iverilog, vvp = tool('iverilog', a.icarus_bin), tool('vvp', a.icarus_bin)
    out = a.log_dir or Path(tempfile.mkdtemp(prefix='xor6_sim_'))
    out.mkdir(parents=True, exist_ok=True)
    for name, top, flags, files in TESTS:
        binary = out/(name+'.vvp')
        r = subprocess.run([iverilog, '-g2012', '-s', top, *flags, '-o', str(binary), *map(str, files)],
                           capture_output=True, text=True, timeout=300)
        (out/(name+'.compile.log')).write_text(r.stdout+r.stderr, encoding='utf-8')
        if r.returncode:
            sys.exit(f'{name}: compile failed\n{r.stdout}{r.stderr}')
        r = subprocess.run([vvp, '-n', str(binary)], capture_output=True, text=True, timeout=1800)
        (out/(name+'.log')).write_text(r.stdout+r.stderr, encoding='utf-8')
        if r.returncode or 'PASS' not in r.stdout or 'FATAL' in r.stdout:
            sys.exit(f'{name}: FAILED\n{r.stdout}{r.stderr}')
        print(next(line for line in r.stdout.splitlines() if line.startswith('PASS')))
    print('Logs:', out)


if __name__ == '__main__':
    main()
