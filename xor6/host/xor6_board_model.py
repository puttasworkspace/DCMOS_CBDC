"""Software stand-in for the programmed board (dry runs and tests, no hardware).

It speaks exactly the cbdc_xor6_serial UART protocol, so the collector, key
generator and attack scripts can be exercised end to end before the bitstream
exists. Each core follows the additive delay model used throughout this
project: Q = 1 when  sum_i a_i * phi_i(C) + b + noise > 0, with
phi_i = prod_{j>=i} (1 - 2*C_j). `bias_sd` gives some cores a strong 0/1 bias
and `noise_sd` sets how often a single run flips, as on real silicon.
A MODEL, NOT A MEASUREMENT: it never stands in for board results in a report.
Standard library only.
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # bundled runtime/python ignores the script folder

import random

from xor6_protocol import CORES, GROUPS, GROUP_SIZE, N_STAGES, REPLY_BYTES, FLAG_OK, FLAG_REJECTED, parity, xor_all


class BoardModel:
    def __init__(self, seed=1, noise_sd=0.15, bias_sd=0.8, expose_core_bits=True):
        rng = random.Random(seed)
        self.rng = random.Random(seed + 1)
        self.weights = [[rng.gauss(0, 1) for _ in range(N_STAGES)] for _ in range(CORES)]
        self.offset = [rng.gauss(0, bias_sd) for _ in range(CORES)]
        self.noise_sd = noise_sd
        self.expose = expose_core_bits
        self._out = bytearray()
        self._inp = bytearray()

    def delay_difference(self, core, config):
        s = [1 - 2*((config >> i) & 1) for i in range(N_STAGES)]
        total, prod = self.offset[core], 1
        for i in reversed(range(N_STAGES)):
            prod *= s[i]
            total += self.weights[core][i]*prod
        return total

    def run(self, core, config):
        return int(self.delay_difference(core, config) + self.rng.gauss(0, self.noise_sd) > 0)

    def respond(self, request):
        control, votes, configs = request[1], request[2], list(request[3:3 + CORES])
        ok = (control >> 1) != 0 and 1 <= votes <= 63 and all(parity(c) for c in configs)
        maj, una = [0]*CORES, [0]*CORES
        if ok:
            for k in range(CORES):
                ones = sum(self.run(k, configs[k]) for _ in range(votes))
                maj[k] = int(2*ones > votes)
                una[k] = int(ones in (0, votes))
        xr = [0]*GROUPS
        for g in range(GROUPS):
            for m in range(GROUP_SIZE):
                xr[g] ^= maj[g*GROUP_SIZE + m]
        word = lambda bits, n: sum(b << i for i, b in enumerate(bits)).to_bytes(n, 'little')
        body = bytes([0xD7, control, votes, *configs, FLAG_OK if ok else FLAG_REJECTED])
        body += (word(maj, 8) if self.expose else bytes(8)) + (word(una, 8) if self.expose else bytes(8)) + word(xr, 2)
        reply = body + bytes([xor_all(body)])
        assert len(reply) == REPLY_BYTES
        return reply

    # Minimal serial-port interface used by xor6_collect.py
    def write(self, data):
        self._inp += data
        while len(self._inp) >= 64:
            req, self._inp = bytes(self._inp[:64]), self._inp[64:]
            if req[0] == 0xA7 and req[-1] == xor_all(req[:-1]):
                self._out += self.respond(req)
        return len(data)

    def read(self, n):
        data, self._out = bytes(self._out[:n]), self._out[n:]
        return data

    def reset_input_buffer(self):
        self._out.clear()

    def close(self):
        pass
