# XOR-6 CBDC variant: 60 cores × 8 stages, on-chip voting, 10 XOR responses

This folder adds a second design next to the 16-stage paper replication. **Nothing outside `xor6/` is changed**: the original RTL, layout, bitstream, measurements and scripts are reused read-only.

## Why this variant exists

On the 64-core board, each 16-stage CBDC core can be predicted with **~95%** accuracy by per-core logistic regression on flip-count features. The paper's SHA-3 step has no key, so an attacker can compute the configurations themselves and it adds no ML resistance. This variant tests two fixes:

1. **XOR of several cores.** Each response bit is the XOR of 6 independently configured cores. That is real non-linearity: a linear model drops to coin-flipping. Software simulation suggested **8 stages × 6 cores** resists a neural-network attack at 200k CRPs, while 16 × 4 does not, and at lower LUT cost.
2. **A keyed hash.** Configurations come from `KMAC256(K, challenge)`, with K derived from the PUF. In this **staged** version, KMAC and key generation run on the PC; moving them into RTL is the next stage.

## Architecture

```
challenge c (64-bit) ──► KMAC256(K, c) ──► 60 odd-parity 8-bit configs      (PC, staged)
                                              │ UART
FPGA:  60 × [ CBDC core (8 stages) ─► run VOTES times ─► majority ]          (cbdc_vote_engine)
       group g = cores 6g..6g+5 ─► XOR ─► response bit R[g],  g = 0..9         (cbdc_xor6_serial)
```

| Item | Value |
|---|---|
| Cores / stages | 60 × 8 (10 groups of 6) |
| Configuration bits per query | 480 (60 bytes, each odd parity) |
| Response bits per query | 10 XOR bits (+ 60 voted per-core bits and 60 stability flags in the characterisation build) |
| Votes per core | 1..63 per request (odd recommended; 21 is a good default) |
| PUF LUTs | 60 × 2 × (8×3 + 1) = 3,000, i.e. 300 per XOR group (a 16-stage × 4-core group would need 392) |
| Whole design (Yosys estimate) | ~10.7k LUTs, ~5.4k FFs of 20,800 / 41,600; Vivado will differ somewhat |
| Query time | ~13–14 ms at 115200 baud (≈ 70 queries/s, 50k queries ≈ 12 min) |

The CBDC cell is unchanged: fixed AND entrance gates, 3-LUT buffer/inverter/mux stages, a falling-edge FF capturing Qu on Qb's falling edge (Q = 1 means the upper chain was slower), and odd-parity configurations only.

### Two builds

| Build | Command switch | Per-core bits in reply | Use |
|---|---|---|---|
| Characterisation (default) | — | yes | bias/reliability studies, key enrollment (staged), single-core attacks |
| Deployment | `-HideCoreBits` | zeroed | security evaluation of the XOR responses |

**Important:** if per-core bits leave the chip, an attacker learns each 8-stage core separately (~99%) and the XOR gives no protection. Security claims about XOR-6 must use the deployment build, or attacks that use only the XOR bits.

## Files

| Path | Purpose |
|---|---|
| `rtl/cbdc_puf_core_n.v` | CBDC core with the stage count as a parameter (same hierarchy names as the 16-stage core) |
| `rtl/cbdc_vote_engine.v` | One core + its controller, repeated `votes` times, on-chip majority and unanimity flag |
| `rtl/cbdc_xor6_serial.v` | Top level: UART protocol, 60 vote engines, parallel/sequential activation, 10-group XOR |
| `constraints/basys3_xor6.xdc` | Same pins/clock as the 64-core design |
| `sim/tb_chain8_truth.v`, `sim/tb_xor6_serial.v`, `sim/run_sim.py` | Icarus testbenches (characterisation and deployment builds) |
| `layout/plan_layout8.py` → `layout.tcl/json`, `placement.csv` | 60 macros, chain spacing ≤ 6 columns, no clock-region crossing |
| `layout/make_route_template8.py` → `internal_route_template8.tcl` | 8-stage subset of the verified 16-stage local route template |
| `scripts/build/*.tcl`, `*.py` | Synthesis, constrained placement, fixed routing, refinement, structural + delay audits, finalize, build record |
| `scripts/build_xor6.ps1` | One-command isolated build (like `scripts/rebuild.ps1`) |
| `host/kmac.py` | Pure-Python Keccak / SHAKE256 / cSHAKE256 / KMAC256 (NIST vector checked) |
| `host/xor6_protocol.py` | Frame building/parsing |
| `host/xor6_configs.py` | Challenge matrices: `keyed`, `unkeyed` (paper-style), `random` |
| `host/xor6_keygen.py` | PUF key: public key-round matrix, enroll (stable-bit mask + BCH(31,16,3) code-offset), reconstruct |
| `host/xor6_collect.py` / `host/xor6_collect.ps1` | Replay a matrix on the board (pyserial / .NET); identical CSV output |
| `host/xor6_attack.py` | Single-core, XOR-with-configs and keyed attacks (LR + MLP) and reliability; needs numpy + scikit-learn |
| `host/xor6_board_model.py`, `host/xor6_virtual_board.py` | Software board for dry runs and collector tests (**a model, never hardware data**) |
| `host/test_host.py` | Unit and end-to-end tests of the host tools |

## Step by step

All commands run from the repository root on Windows (PowerShell). `python` can be the bundled `runtime\python\python.exe` for every tool **except** `xor6_attack.py` (numpy/scikit-learn) and `xor6_collect.py --port` (pyserial). Use `xor6_collect.ps1` when pyserial is not installed.

### 1. Check the design

```powershell
python xor6\sim\run_sim.py --icarus-bin C:\iverilog\bin    # 3 testbenches must print PASS
python xor6\host\test_host.py                               # 13 tests must pass
```

### 2. Build the bitstream (Vivado 2025.2, same as the 64-core flow)

```powershell
powershell -ExecutionPolicy Bypass -File xor6\scripts\build_xor6.ps1                 # characterisation build
powershell -ExecutionPolicy Bypass -File xor6\scripts\build_xor6.ps1 -HideCoreBits   # deployment build
```

Each run creates `xor6\rebuilds\run_<id>\` and stops on the first failed check: simulation, structural audit of all 60 macros, **paired upper/lower route delays (1,920 pairs must match exactly)**, DRC, or timing. The bitstream is `build\xor6_array60.bit`, recorded with its hash in `BUILD_RECORD.json`.

If route matching fails, `build\route_summary.json` lists the mismatched stage/kind classes (for example `stage 3 inv`). The local route corrections in `refine_routes.tcl` were derived for the 16-stage layout and may need extending for the new rows. Add the correction, then run the command the error message prints:

```powershell
powershell -ExecutionPolicy Bypass -File xor6\scripts\build_xor6.ps1 -ResumeStage xor6\rebuilds\run_<id>
```

### 3. Program the board

```powershell
& 'C:\AMDDesignTools\2025.2\Vivado\bin\vivado.bat' -mode batch -source scripts\program.tcl -tclargs xor6\rebuilds\run_<id>\build\xor6_array60.bit PROGRAM_SELECTED_BITSTREAM
```

LEDs: `led[7:0]` = last XOR bits, `led[8]` idle, `led[9]` replying, `led[10]` cores busy, `led[11]` always on.

### 4. Characterise the cores (bias, reliability, single-core learnability)

```powershell
python xor6\host\xor6_configs.py --mode random --count 5000 --out xor6\runs\random.json
powershell -File xor6\host\xor6_collect.ps1 -Port COM5 -Matrix xor6\runs\random.json -Output xor6\runs\random.csv -Trials 5 -Votes 21 -BuildRecord xor6\rebuilds\run_<id>\BUILD_RECORD.json
python xor6\host\xor6_attack.py --capture xor6\runs\random.csv --report xor6\runs\random_report.json
```

Look at the per-core ones fraction (`core_ones_fraction`). Cores stuck near 0% or 100% add nothing to an XOR group. Also check `core_flip_rate` and `xor_flip_rate`.

### 5. Generate the PUF key (staged: on the PC)

```powershell
python xor6\host\xor6_keygen.py matrix --rounds 8 --out xor6\runs\key_matrix.json
powershell -File xor6\host\xor6_collect.ps1 -Port COM5 -Matrix xor6\runs\key_matrix.json -Output xor6\runs\key_enroll.csv -Trials 5 -Votes 31
python xor6\host\xor6_keygen.py enroll --capture xor6\runs\key_enroll.csv --rounds 8 --helper xor6\runs\helper.json --key-out xor6\runs\key.bin
# later, e.g. after power cycling:
powershell -File xor6\host\xor6_collect.ps1 -Port COM5 -Matrix xor6\runs\key_matrix.json -Output xor6\runs\key_check.csv -Trials 3 -Votes 31
python xor6\host\xor6_keygen.py reconstruct --capture xor6\runs\key_check.csv --helper xor6\runs\helper.json
```

`helper.json` is public; `key.bin` is **secret**. Keep it, and keyed matrices, out of git: `xor6/runs/` is git-ignored for this reason. Key enrollment needs the characterisation build.

### 6. Security experiments (use the deployment build)

```powershell
python xor6\host\xor6_configs.py --mode unkeyed --count 200000 --out xor6\runs\unkeyed.json        # paper-style public hash
python xor6\host\xor6_configs.py --mode keyed --key-file xor6\runs\key.bin --count 200000 --out xor6\runs\keyed.json
powershell -File xor6\host\xor6_collect.ps1 -Port COM5 -Matrix xor6\runs\unkeyed.json -Output xor6\runs\unkeyed.csv -Votes 21
powershell -File xor6\host\xor6_collect.ps1 -Port COM5 -Matrix xor6\runs\keyed.json  -Output xor6\runs\keyed.csv  -Votes 21
python xor6\host\xor6_attack.py --capture xor6\runs\unkeyed.csv --report xor6\runs\unkeyed_report.json
python xor6\host\xor6_attack.py --capture xor6\runs\keyed.csv   --report xor6\runs\keyed_report.json
```

Collect a few thousand repeated challenges (`-Trials 3`) as well, to measure XOR reliability. Always compare accuracies with the printed **baseline** (always guessing the most common bit), not with 50%.

### Dry run without hardware

Every step above works against the software model by replacing the port with `--model <seed>` in `xor6_collect.py`. Results from the model only show the tools work; they are **not measurements**.

## What has and has not been verified

| Verified here | Not verified (needs your Vivado and board) |
|---|---|
| RTL simulation: 8-stage chain truth table (all 256 configs); top level framing, checksums, Latch-controlled capture, voting (minority on first and last run), unanimity flags, group XOR, readback, parallel/sequential, rejections, recovery, deployment build; mutation tests (broken vote or XOR is caught) | Vivado synthesis, placement legality, routing and timing closure |
| Yosys synthesis: no latches, no structural problems, resource estimate | Whether the 16-stage route template and refinements give exact upper/lower matching for every new macro row |
| Placement plan: 60 non-overlapping macros, ≤ 6 column spacing, inside clock regions | Real bias, reliability and uniqueness of 8-stage cores |
| Tcl dry runs with stubbed Vivado: 3,120 placed cells, 2,880 fixed routes, 468 refinements; full `build_xor6.ps1` flow incl. mismatch detection and resume | Real attack results on XOR-6 hardware data |
| KMAC256 (NIST SP 800-185 sample 4), SHAKE256 (hashlib), BCH(31,16,3) correction of 3 errors, key enroll/reconstruct, keyed configs, PowerShell and Python collectors byte-identical over a serial link | Key entropy on silicon |

## Known limitations

- **Key entropy:** BCH(31,16) code-offset publicly leaks 15 of every 31 bits, and bits from the same 8-stage core across rounds are correlated. On the software model, the bias-only estimate after leakage was already **below 128 bits**. Real entropy must be measured. If it is short, use more key cores or a dedicated key PUF; more rounds on the same cores do not help much.
- **Configuration space per core is small:** 128 odd-parity configurations. The XOR of 6 cores with independent configurations gives 128^6 ≈ 4·10^12 combinations per group, but an attacker who obtains per-core bits needs only 128 queries per core. Keep per-core bits on chip (deployment build).
- **Physical non-linearity is not cryptographic security:** XOR-k PUFs have been broken by specialised attacks given enough CRPs. The keyed hash is what stops CRP collection; XOR-6 raises the cost if the key leaks.
- **Staged:** K, KMAC and BCH run on the PC here. Moving them into RTL (an iterative Keccak core plus a BCH decoder) is the next step, together with bitstream encryption and disabled readback so a modified bitstream cannot read the key cores.
- Net-delay matching and digital simulation do not establish analog symmetry, entropy or environmental reliability.
