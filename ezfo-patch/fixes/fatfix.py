#!/usr/bin/env python3
"""Localiza los tests de fin de cadena FAT no conformes (R9) en la ROM.

FilmPlay comprueba el fin de cadena con igualdad exacta (0x0FFFFFFF / 0xFFFF /
0xFFF), cuando la especificacion FAT define como fin cualquier valor >= ...FF8.
mkfs.vfat escribe 0x0FFFFFF8 para la raiz, lo que cuelga la ROM.

Se decodifica el inmediato en vez de comparar bytes: el compilador original usa
codificaciones distintas de las que emite el ensamblador para el mismo valor.
"""
import struct

def ror(v, r):
    r &= 31
    return ((v >> r) | (v << (32 - r))) & 0xFFFFFFFF if r else v

def dp_imm(w):
    """Devuelve (opcode, S, Rn, valor) si es data-processing con inmediato."""
    if (w >> 26) & 3 or not (w >> 25) & 1:
        return None
    return ((w >> 21) & 0xF, (w >> 20) & 1, (w >> 16) & 0xF,
            ror(w & 0xFF, ((w >> 8) & 0xF) * 2))

CMN, SUB = 0xB, 0x2

def find_sites(rom, base=0x08000000):
    W = lambda o: struct.unpack_from('<I', rom, o)[0]
    fat32, fat16, fat12 = [], [], []
    for o in range(0, len(rom) - 12, 4):
        d = dp_imm(W(o))
        if not d:
            continue
        op, S, rn, val = d
        # FAT32: cmn r0,#0xF0000001 seguido de bne
        if op == CMN and S and rn == 0 and val == 0xF0000001 and (W(o + 4) >> 28) == 1:
            fat32.append(base + o)
        # FAT16/12: sub ip,r0,#0xFF00|0xF00 ; subs ip,ip,#0xFF ; bne
        if op == SUB and not S and rn == 0 and ((W(o + 4) >> 12) & 0xF) == 12:
            d2 = dp_imm(W(o + 4))
            if d2 and d2[0] == SUB and d2[1] and d2[2] == 12 and d2[3] == 0xFF \
               and (W(o + 8) >> 28) == 1:
                (fat16 if val == 0xFF00 else fat12 if val == 0xF00 else []).append(base + o)
    return fat32, fat16, fat12

def apply(rom, base=0x08000000, verbose=True):
    f32, f16, f12 = find_sites(rom, base)
    poke = lambda a, w: rom.__setitem__(slice(a - base, a - base + 4), struct.pack('<I', w))
    W = lambda a: struct.unpack_from('<I', rom, a - base)[0]

    for a in f32:
        poke(a, 0xE370028F)                        # cmn r0,#0xF0000008
        poke(a + 4, (W(a + 4) & 0x0FFFFFFF) | 0x30000000)   # bne -> bcc
    for a in f16:
        poke(a, 0xE280C008)                        # add ip,r0,#8
        poke(a + 4, 0xE31C0801)                    # tst ip,#0x10000
        poke(a + 8, W(a + 8) & 0x0FFFFFFF)         # bne -> beq
    for a in f12:
        poke(a, 0xE280C008)                        # add ip,r0,#8
        poke(a + 4, 0xE31C0A01)                    # tst ip,#0x1000
        poke(a + 8, W(a + 8) & 0x0FFFFFFF)         # bne -> beq

    if verbose:
        for name, lst in (("FAT32", f32), ("FAT16", f16), ("FAT12", f12)):
            print(f"  {name}: {len(lst)} sitios  {[hex(x) for x in lst]}")
    return len(f32) + len(f16) + len(f12)

if __name__ == "__main__":
    rom = bytearray(open("../FilmPlay.gba", "rb").read())
    print("sitios de fin de cadena FAT no conformes:")
    apply(rom)
