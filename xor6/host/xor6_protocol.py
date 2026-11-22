"""UART protocol of cbdc_xor6_serial (see xor6/rtl/cbdc_xor6_serial.v).

Request  (64 B): A7 | control | votes | 60 config bytes | checksum
Reply    (83 B): D7 | control | votes | 60 latched configs | flags |
                 8 B majority | 8 B unanimous | 2 B group XOR | checksum
Checksum = XOR of all preceding bytes. Bit fields are LSB first.
Standard library only.
"""
GROUPS, GROUP_SIZE, N_STAGES = 10, 6, 8
CORES = GROUPS * GROUP_SIZE            # 60
REQUEST_BYTES, REPLY_BYTES = 64, 83
FLAG_OK, FLAG_REJECTED, FLAG_ERROR = 0x71, 0x70, 0xE0


def parity(x):
    return bin(x).count('1') & 1


def make_odd(byte):
    """Force odd parity by flipping bit 0 when needed (uniform over the 128 odd bytes)."""
    byte &= 0xFF
    return byte if parity(byte) else byte ^ 1


def xor_all(data):
    c = 0
    for b in data:
        c ^= b
    return c


def control_byte(excite_cycles=8, sequential=False):
    if not 1 <= excite_cycles <= 127:
        raise ValueError('excite_cycles must be 1..127')
    return (excite_cycles << 1) | int(bool(sequential))


def build_request(configs, votes=21, excite_cycles=8, sequential=False):
    if len(configs) != CORES:
        raise ValueError(f'need {CORES} configurations')
    if not 1 <= votes <= 63:
        raise ValueError('votes must be 1..63')
    if any(not 0 <= c <= 255 or not parity(c) for c in configs):
        raise ValueError('every configuration must be an odd-parity byte')
    frame = bytes([0xA7, control_byte(excite_cycles, sequential), votes, *configs])
    return frame + bytes([xor_all(frame)])


def _bits(data, count):
    word = int.from_bytes(bytes(data), 'little')
    return [(word >> i) & 1 for i in range(count)]


def parse_reply(reply, request=None):
    """Decode and validate a reply. Raises ValueError on any inconsistency."""
    reply = bytes(reply)
    if len(reply) != REPLY_BYTES:
        raise ValueError(f'reply length {len(reply)}')
    if reply[0] != 0xD7 or reply[-1] != xor_all(reply[:-1]):
        raise ValueError('bad reply header or checksum')
    out = dict(control=reply[1], votes=reply[2], configs=list(reply[3:3 + CORES]), flags=reply[63],
               majority=_bits(reply[64:72], CORES), unanimous=_bits(reply[72:80], CORES),
               xor=_bits(reply[80:82], GROUPS))
    if request is not None:
        request = bytes(request)
        if out['control'] != request[1] or out['votes'] != request[2]:
            raise ValueError('reply does not echo the request')
        if out['flags'] == FLAG_OK and out['configs'] != list(request[3:3 + CORES]):
            raise ValueError('latched configuration differs from the request')
    if out['flags'] == FLAG_OK:
        expect = [0]*GROUPS
        for g in range(GROUPS):
            for m in range(GROUP_SIZE):
                expect[g] ^= out['majority'][g*GROUP_SIZE + m]
        exposed = any(reply[64:80])
        if exposed and expect != out['xor']:
            raise ValueError('group XOR does not match the per-core majority bits')
    return out


def bits_to_hex(bits):
    return format(sum(b << i for i, b in enumerate(bits)), '0%dX' % ((len(bits) + 3)//4))


def hex_to_bits(text, count):
    v = int(text, 16)
    return [(v >> i) & 1 for i in range(count)]
