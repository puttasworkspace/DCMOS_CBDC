"""Unit tests for the XOR-6 host tools (standard library only).

    python xor6/host/test_host.py
"""
import csv
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from kmac import kmac256, shake256, cshake256                                   # noqa: E402
import xor6_protocol as P                                                       # noqa: E402
from xor6_configs import configs_keyed, configs_unkeyed                         # noqa: E402
from xor6_board_model import BoardModel                                         # noqa: E402
from xor6_keygen import FE                                                      # noqa: E402


class TestKeccak(unittest.TestCase):
    def test_shake256_matches_hashlib(self):
        rng = random.Random(1)
        for n in (0, 1, 135, 136, 137, 271, 272, 500):
            data = bytes(rng.getrandbits(8) for _ in range(n))
            self.assertEqual(shake256(data, 300), hashlib.shake_256(data).digest(300))

    def test_kmac256_nist_sample_4(self):
        # NIST SP 800-185 KMAC sample #4 (KMAC256, 512-bit output)
        key = bytes(range(0x40, 0x60))
        out = kmac256(key, bytes([0, 1, 2, 3]), 64, b'My Tagged Application')
        self.assertEqual(out.hex().upper(),
                         '20C570C31346F703C9AC36C61C03CB64C3970D0CFC787E9B79599D273A68D2F7'
                         'F69D4CC3DE9D104A351689F27CF6F5951F0103F33F4F24871024D9C27773A8DD')

    def test_cshake_without_names_is_shake(self):
        self.assertEqual(cshake256(b'abc', 32), hashlib.shake_256(b'abc').digest(32))


class TestProtocol(unittest.TestCase):
    def test_request_layout(self):
        cfg = [P.make_odd(i) for i in range(60)]
        req = P.build_request(cfg, votes=21, excite_cycles=8)
        self.assertEqual(len(req), P.REQUEST_BYTES)
        self.assertEqual(req[:3], bytes([0xA7, 16, 21]))
        self.assertEqual(req[-1], P.xor_all(req[:-1]))

    def test_rejects_bad_requests(self):
        cfg = [P.make_odd(i) for i in range(60)]
        with self.assertRaises(ValueError):
            P.build_request(cfg, votes=0)
        with self.assertRaises(ValueError):
            P.build_request(cfg, votes=64)
        bad = list(cfg)
        bad[5] ^= 1
        with self.assertRaises(ValueError):
            P.build_request(bad)

    def test_make_odd_is_uniform_over_odd_bytes(self):
        self.assertEqual(sorted({P.make_odd(b) for b in range(256)}), [b for b in range(256) if P.parity(b)])

    def test_model_round_trip_and_xor(self):
        board = BoardModel(seed=3)
        cfg = [P.make_odd(i*37) for i in range(60)]
        req = P.build_request(cfg, votes=11)
        r = P.parse_reply(board.respond(req), req)
        self.assertEqual(r['flags'], P.FLAG_OK)
        for g in range(P.GROUPS):
            self.assertEqual(r['xor'][g], sum(r['majority'][g*6:(g + 1)*6]) % 2)

    def test_corrupted_reply_detected(self):
        board = BoardModel(seed=3)
        req = P.build_request([P.make_odd(i) for i in range(60)])
        rep = bytearray(board.respond(req))
        rep[70] ^= 1
        with self.assertRaises(ValueError):
            P.parse_reply(rep, req)

    def test_deployment_reply_hides_core_bits(self):
        board = BoardModel(seed=3, expose_core_bits=False)
        req = P.build_request([P.make_odd(i) for i in range(60)])
        r = P.parse_reply(board.respond(req), req)
        self.assertEqual(sum(r['majority']) + sum(r['unanimous']), 0)


class TestConfigs(unittest.TestCase):
    def test_keyed_configs(self):
        k1, k2 = bytes(32), bytes([1]*32)
        a, b = configs_keyed(k1, 12345), configs_keyed(k2, 12345)
        self.assertEqual(len(a), 60)
        self.assertTrue(all(P.parity(x) for x in a + b))
        self.assertNotEqual(a, b)                       # different key -> different configs
        self.assertEqual(a, configs_keyed(k1, 12345))   # deterministic
        self.assertNotEqual(a, configs_keyed(k1, 12346))

    def test_unkeyed_is_public(self):
        self.assertEqual(configs_unkeyed(7), configs_unkeyed(7))
        self.assertTrue(all(P.parity(x) for x in configs_unkeyed(7)))


class TestBCH(unittest.TestCase):
    def test_corrects_three_errors(self):
        rng = random.Random(4)
        for _ in range(200):
            w = rng.getrandbits(31)
            s, h = FE.generate(w)
            noisy = w
            for pos in rng.sample(range(31), 3):
                noisy ^= 1 << pos
            r, errs, ok = FE.reproduce(noisy, h)
            self.assertTrue(ok)
            self.assertEqual(r, s)


class TestEndToEnd(unittest.TestCase):
    def run_py(self, *args):
        r = subprocess.run([sys.executable, *map(str, args)], cwd=HERE, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def test_keygen_and_keyed_collection(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertEqual(self.run_py('xor6_keygen.py', 'matrix', '--rounds', '8', '--out', d/'km.json')[0], 0)
            self.assertEqual(self.run_py('xor6_collect.py', '--matrix', d/'km.json', '--model', '5', '--trials', '4',
                                         '--votes', '31', '--out', d/'enroll.csv')[0], 0)
            code, out = self.run_py('xor6_keygen.py', 'enroll', '--capture', d/'enroll.csv', '--rounds', '8',
                                    '--helper', d/'helper.json', '--key-out', d/'key.bin')
            self.assertEqual(code, 0, out)
            self.run_py('xor6_collect.py', '--matrix', d/'km.json', '--model', '5', '--trials', '1', '--votes', '31', '--out', d/'again.csv')
            code, out = self.run_py('xor6_keygen.py', 'reconstruct', '--capture', d/'again.csv', '--helper', d/'helper.json',
                                    '--key-out', d/'key2.bin')
            self.assertEqual(code, 0, out)
            self.assertEqual((d/'key.bin').read_bytes(), (d/'key2.bin').read_bytes())
            # Another "chip" must not reproduce the key.
            self.run_py('xor6_collect.py', '--matrix', d/'km.json', '--model', '77', '--trials', '1', '--votes', '31', '--out', d/'other.csv')
            self.assertNotEqual(self.run_py('xor6_keygen.py', 'reconstruct', '--capture', d/'other.csv', '--helper', d/'helper.json')[0], 0)
            # Keyed matrix and collection with that key.
            self.assertEqual(self.run_py('xor6_configs.py', '--mode', 'keyed', '--key-file', d/'key.bin', '--count', '50',
                                         '--out', d/'m.json')[0], 0)
            self.assertEqual(self.run_py('xor6_collect.py', '--matrix', d/'m.json', '--model', '5', '--out', d/'run.csv')[0], 0)
            with (d/'run.csv').open(newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 50)
            m = json.loads((d/'m.json').read_text())
            key = (d/'key.bin').read_bytes()
            for row, pat in zip(rows, m['patterns']):
                self.assertEqual(list(bytes.fromhex(row['configs_hex'])), configs_keyed(key, int(pat['challenge_hex'], 16)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
