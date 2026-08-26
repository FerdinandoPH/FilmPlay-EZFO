#!/usr/bin/env python3
"""Decodificador de referencia del formato .gbs (GBA Movie Player).

Los cinco MusicMode, transcritos de savemu.dll:
  FUN_10002110 (modo 0), FUN_100023d0 (1), FUN_10002210 (2),
  FUN_10002560 (3 y 4), y los cuantizadores FUN_10002310 / FUN_100024c0 /
  FUN_10002730.
"""
import struct, sys
from gbs_tables import STEP, IDX4, IDX3, DELTA2

HDR = 0x200

# modo -> (bloque, cabecera, muestras, canales, frecuencia)
MODES = {
    0: (0x400, 8, 1017, 2, 22050),
    1: (0x400, 4, 2721, 1, 44100),
    2: (0x200, 4, 1017, 1, 22050),
    3: (0x200, 4, 2033, 1, 22050),
    4: (0x100, 4, 1009, 1, 11025),
}


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def dec4(code, pred, idx):
    """IMA de 4 bits. El predictor vive en 0..65535 (muestra + 0x8000)."""
    s = STEP[idx]
    diff = s >> 3
    if code & 4: diff += s
    if code & 2: diff += s >> 1
    if code & 1: diff += s >> 2
    if code & 8: diff = -diff
    return clamp(pred + diff, 0, 0xFFFF), clamp(idx + IDX4[code], 0, 88)


def dec3(code, pred, idx):
    """IMA de 3 bits: bit 4 signo, bits 1-0 magnitud."""
    s = STEP[idx]
    diff = s >> 2
    if code & 2: diff += s
    if code & 1: diff += s >> 1
    if code & 4: diff = -diff
    return clamp(pred + diff, 0, 0xFFFF), clamp(idx + IDX3[code], 0, 88)


def dec2(code, pred, idx):
    """2 bits: NO es IMA. Tabla de deltas propia, indice en pasos de 4."""
    pred = clamp(pred + DELTA2[idx + code], 0, 0xFFFF)
    idx = clamp(idx + (4 if code & 1 else -4), 0, 0x160)
    return pred, idx


def decode(data):
    if data[0:4] != b'GBAL' or data[8:12] != b'MUSI':
        raise ValueError('no es un .gbs')
    mode = struct.unpack_from('<I', data, 0x10)[0]
    blk, hdr, nsmp, ch, rate = MODES[mode]
    out = []
    saltos = []
    p = HDR
    while p + blk <= len(data):
        b = data[p:p + blk]
        if mode == 0:
            pa, ia, pb, ib = struct.unpack_from('<HHHH', b, 0)
            if out:
                saltos.append(abs(pa - prev_a) + abs(pb - prev_b))
            out.append((pa - 0x8000, pb - 0x8000))
            for byte in b[8:8 + nsmp - 1]:
                pa, ia = dec4(byte & 15, pa, ia)
                pb, ib = dec4(byte >> 4, pb, ib)
                out.append((pa - 0x8000, pb - 0x8000))
            prev_a, prev_b = pa, pb
        else:
            pr, ix = struct.unpack_from('<HH', b, 0)
            if out:
                saltos.append(abs(pr - prev))
            out.append((pr - 0x8000,))
            if mode == 1:
                # 8 codigos de 3 bits en 24 bits big endian, el primero abajo
                for g in range(0, (nsmp - 1) // 8 * 3, 3):
                    v = (b[4 + g] << 16) | (b[5 + g] << 8) | b[6 + g]
                    for k in range(8):
                        pr, ix = dec3((v >> (3 * k)) & 7, pr, ix)
                        out.append((pr - 0x8000,))
            elif mode == 2:
                for byte in b[4:4 + (nsmp - 1) // 2]:
                    pr, ix = dec4(byte & 15, pr, ix)
                    out.append((pr - 0x8000,))
                    pr, ix = dec4(byte >> 4, pr, ix)
                    out.append((pr - 0x8000,))
            else:
                for byte in b[4:4 + (nsmp - 1) // 4]:
                    for k in range(4):
                        pr, ix = dec2((byte >> (2 * k)) & 3, pr, ix)
                        out.append((pr - 0x8000,))
            prev = pr
        p += blk
    return mode, rate, ch, out, saltos


def to_wav(path, rate, ch, smp):
    n = len(smp) * ch * 2
    h = (b'RIFF' + struct.pack('<I', 36 + n) + b'WAVEfmt '
         + struct.pack('<IHHIIHH', 16, 1, ch, rate, rate * ch * 2, ch * 2, 16)
         + b'data' + struct.pack('<I', n))
    body = bytearray()
    for s in smp:
        for v in s:
            body += struct.pack('<h', clamp(v, -32768, 32767))
    open(path, 'wb').write(h + bytes(body))


if __name__ == '__main__':
    mode, rate, ch, smp, saltos = decode(open(sys.argv[1], 'rb').read())
    dur = len(smp) / rate
    med = sum(saltos) / len(saltos) if saltos else 0
    print('modo %d | %d Hz | %d canal(es) | %d muestras | %.2f s' % (mode, rate, ch, len(smp), dur))
    print('salto medio en frontera de bloque: %.0f (fondo de escala 65535)' % med)
    if len(sys.argv) > 2:
        to_wav(sys.argv[2], rate, ch, smp)
        print('escrito', sys.argv[2])
