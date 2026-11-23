"""Pure-Python Keccak, SHAKE256, cSHAKE256 and KMAC256 (FIPS 202, NIST SP 800-185).

Standard library only, so it runs with the bundled runtime/python. Written as a
straightforward reference (one permutation per 136-byte block) to make a later
port to RTL easy to check against. Verified in test_host.py against Python's
hashlib.shake_256 and against KMAC256 values from an independent library.
"""

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
# Rotation offsets r[x][y]
_ROT = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]
_MASK = (1 << 64) - 1
RATE_256 = 136   # bytes, capacity 512 bits (SHAKE256 / cSHAKE256 / KMAC256)


def _rol(v, n):
    n %= 64
    return ((v << n) | (v >> (64 - n))) & _MASK if n else v


def keccak_f(a):
    """Keccak-f[1600] on a 5x5 list of 64-bit lanes a[x][y] (in place)."""
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                a[x][y] ^= d[x]
        b = [[0]*5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2*x + 3*y) % 5] = _rol(a[x][y], _ROT[x][y])
        for x in range(5):
            for y in range(5):
                a[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])
        a[0][0] ^= rc
    return a


def _sponge(data, suffix, out_len, rate=RATE_256):
    """Absorb data with the domain-separation suffix byte, squeeze out_len bytes."""
    msg = bytearray(data)
    msg.append(suffix)
    while len(msg) % rate:
        msg.append(0)
    msg[-1] |= 0x80
    a = [[0]*5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            a[x][y] ^= int.from_bytes(block[8*i:8*i + 8], 'little')
        keccak_f(a)
    out = bytearray()
    while True:
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            out += a[x][y].to_bytes(8, 'little')
        if len(out) >= out_len:
            return bytes(out[:out_len])
        keccak_f(a)


def left_encode(x):
    n = max(1, (x.bit_length() + 7) // 8)
    return bytes([n]) + x.to_bytes(n, 'big')


def right_encode(x):
    n = max(1, (x.bit_length() + 7) // 8)
    return x.to_bytes(n, 'big') + bytes([n])


def encode_string(s):
    return left_encode(8*len(s)) + bytes(s)


def bytepad(x, w):
    z = left_encode(w) + bytes(x)
    return z + bytes((-len(z)) % w)


def shake256(data, out_len):
    return _sponge(data, 0x1F, out_len)


def cshake256(data, out_len, function_name=b'', customization=b''):
    if not function_name and not customization:
        return shake256(data, out_len)
    prefix = bytepad(encode_string(function_name) + encode_string(customization), RATE_256)
    return _sponge(prefix + bytes(data), 0x04, out_len)


def kmac256(key, data, out_len, customization=b''):
    """KMAC256(K, X, L = 8*out_len, S)."""
    x = bytepad(encode_string(key), RATE_256) + bytes(data) + right_encode(8*out_len)
    return cshake256(x, out_len, b'KMAC', customization)
