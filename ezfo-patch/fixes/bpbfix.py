#!/usr/bin/env python3
"""R10: FilmPlay trunca a 8 bits el numero de sectores reservados del BPB.

El campo `BPB_RsvdSecCnt` (offset 14 del sector de arranque de la particion) es
de 16 bits por especificacion. FilmPlay lo carga bien, con `ldrh`, y acto
seguido lo pasa por un `and #255`:

    ldrh r2, [r0, #14]      @ sectores reservados, 16 bits
    ldr  r1, [r5, #4]       @ LBA de la particion
    and  r2, r2, #255       @ <-- lo trunca
    add  r1, r1, r2         @ fat_lba = particion + reservados

Las tarjetas formateadas con 512 B o 1 KB de zona reservada (32 o 64 sectores)
no notan nada. La SD del usuario, formateada con clusters de 32 KB y la zona de
datos alineada a cluster, tiene 652 sectores reservados: `652 & 0xFF = 140`, y
la FAT, la zona de datos y el directorio raiz quedan 512 sectores por debajo de
donde estan. El "directorio raiz" cae dentro de la segunda FAT, no aparece
nunca la marca de fin de directorio y FilmPlay se queda barriendo sectores de
uno en uno para siempre: pantalla negra sin respuesta.

Reproducido bajo mGBA con una imagen de la geometria exacta de esa tarjeta
(particion en 8192, reservados 652, FAT de 3770 sectores, 2 FAT, clusters de
64 sectores): lecturas 0 -> 8192 -> 8332 (deberia ser 8844) -> 15872, 15873,
15874... exactamente los sectores que devolvio la consola.

El arreglo sustituye cada `and` por un `nop`.
"""
import struct

NOP = 0xE1A00000            # mov r0, r0
LDRH_14 = 0xE1D000BE        # ldrh rD, [rN, #14]   (mascara 0xFFF00FFF)
AND_255 = 0xE20000FF        # and  rD, rN, #255    (mascara 0xFFF00FFF)


def localizar(rom, base):
    """Cada `and #255` que trunca un `ldrh [rN,#14]` leido hasta 6 palabras antes."""
    sitios = []
    for off in range(0, len(rom) - 4, 4):
        if (struct.unpack_from("<I", rom, off)[0] & 0xFFF00FFF) != LDRH_14:
            continue
        for j in range(off + 4, min(off + 24, len(rom) - 4), 4):
            if (struct.unpack_from("<I", rom, j)[0] & 0xFFF00FFF) == AND_255:
                sitios.append(base + j)
                break
    return sitios


def apply(rom, base):
    sitios = localizar(rom, base)
    if not sitios:
        raise SystemExit("bpbfix: no aparece el truncado de sectores reservados")
    for a in sitios:
        struct.pack_into("<I", rom, a - base, NOP)
    print("  " + str(len(sitios)) + " copias: "
          + " ".join(f"{a:08X}" for a in sitios))
    return len(sitios)
