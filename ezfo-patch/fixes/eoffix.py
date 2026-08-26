#!/usr/bin/env python3
"""R13: que FilmPlay pare en el tamano del fichero, no al final de la cadena.

La rutina "lee el siguiente sector de este fichero" de FilmPlay solo declara
el fin cuando se acaba la cadena de clusters, asi que con clusters de 32 KB
reproduce hasta 32 KB de basura tras el ultimo byte util (informe §28).

Su retorno de exito es comun a los tres caminos (FAT12, FAT16 y FAT32):

    ldr r0, [r4, #44]      <- contador de sector dentro del cluster
    add r0, r0, #1
    str r0, [r4, #44]
    ...
    str rY, [r4, #44]
    mov r0, #1             <- R
    b   <epilogo>          <- epilogo = ldmia sp!, {r3-r9, pc}

Esas dos ultimas palabras se sustituyen por un salto absoluto al gancho del
blob, que lleva la cuenta de sectores y remata con el mismo epilogo. Absoluto
y no relativo porque FilmPlay tiene varias copias de la rutina y la misma
copia corre unas veces desde EWRAM y otras desde IWRAM.
"""
import struct

MOV_R0_1 = 0xE3A00001
EPILOGO  = 0xE8BD83F8          # ldmia sp!, {r3,r4,r5,r6,r7,r8,r9,pc}
LDR_R0_44 = 0xE594002C
ADD_R0_1  = 0xE2800001
STR_R0_44 = 0xE584002C
STR_RY_44 = 0xE584002C         # con el registro fuente enmascarado


def find_sites(rom, base=0x08000000):
    W = lambda o: struct.unpack_from('<I', rom, o)[0]
    sitios = []
    for o in range(0x1C, len(rom) - 8, 4):
        if W(o) != MOV_R0_1:
            continue
        b = W(o + 4)
        if (b >> 24) != 0xEA:                      # b (siempre, sin enlace)
            continue
        # destino del salto: tiene que ser el epilogo de la rutina
        off = b & 0xFFFFFF
        if off & 0x800000:
            off -= 0x1000000
        destino = o + 4 + 8 + off * 4
        if not (0 <= destino < len(rom)) or W(destino) != EPILOGO:
            continue
        # y por delante, el avance del contador de sector
        if W(o - 0x1C) != LDR_R0_44 or W(o - 0x18) != ADD_R0_1 or W(o - 0x14) != STR_R0_44:
            continue
        if (W(o - 0x04) & 0xFFFF0FFF) != STR_RY_44:
            continue
        sitios.append(base + o)
    return sitios


def apply(rom, gancho, base=0x08000000, verbose=True):
    sitios = find_sites(rom, base)
    for a in sitios:
        o = a - base
        rom[o:o + 8] = struct.pack('<II', 0xE51FF004, gancho)   # ldr pc,[pc,#-4]
    if verbose:
        print(f"  {len(sitios)} copias -> gancho 0x{gancho:08X}  {[hex(x) for x in sitios]}")
    return len(sitios)


if __name__ == "__main__":
    rom = bytearray(open("../FilmPlay.gba", "rb").read())
    print("retornos de exito de la rutina de lectura de fichero:")
    for a in find_sites(rom):
        print(" ", hex(a))
