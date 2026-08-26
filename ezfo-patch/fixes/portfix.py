#!/usr/bin/env python3
"""Neutraliza el puerto de estado de tarjeta que vive dentro de la ROM.

La cadena de inicializacion de tarjeta de FilmPlay usa `0x083F0000` como puerto
de hardware, y esa direccion esta DENTRO de la imagen de ROM. La funcion espejo

    ldr  r0, [pc, #X]      ; -> 0x083F0000
    ldr  r1, [pc, #Y]      ; -> variable de estado
    ldrh r0, [r0]
    strh r0, [r1]
    mov  pc, lr

copia ese "registro" a una variable que consultan tres bucles de espera, que
aguardan bit0 = 0, bit6 = 1 y bit3 = 1. En ROM el byte de `0x3F0000` vale
`0xC8`, que cumple los tres a la vez.

En mGBA la ROM es de solo lectura: las escrituras que hace la propia rutina de
inicializacion (`0xA0`, `0x0E`, `0x0A`) se ignoran, la relectura siempre da
`0xC8` y los tres bucles pasan al instante. En una EZ Flash Omega la ROM vive en
PSRAM escribible: la relectura devuelve lo ultimo escrito y dos de los tres
bucles agotan sus 500 intentos.

El arreglo escribe la constante directamente:

    ldr  r1, [pc, #Y']     ; -> variable de estado (mismo destino)
    mov  r0, #0xC8
    strh r0, [r1]
    mov  pc, lr

Es seguro aunque la hipotesis sea falsa: si las escrituras no se graban, el
valor leido ya era `0xC8` y el parche no cambia nada observable.
"""
import struct

VALOR_LISTO = 0xC8

# Las cuatro copias de la funcion espejo, localizadas buscando la secuencia
# ldrh/strh/mov pc,lr precedida de dos cargas del pool de literales.
CUERPOS = [0x08020E0C, 0x08023128, 0x080A22AC, 0x08102088]

LDR_R1_PC = 0xE59F1000
MOV_R0_IMM = 0xE3A00000
STRH_R0_R1 = 0xE1C100B0
MOV_PC_LR = 0xE1A0F00E


def apply(rom, base):
    hechos = []
    for a in CUERPOS:
        off = a - base
        w0 = struct.unpack_from("<I", rom, off)[0]
        w1 = struct.unpack_from("<I", rom, off + 4)[0]
        if (w0 & 0xFFFFF000) != 0xE59F0000 or (w1 & 0xFFFFF000) != 0xE59F1000:
            raise SystemExit(f"portfix: {a:08X} no tiene la forma esperada")

        lit_puerto = a + 8 + (w0 & 0xFFF)
        lit_var = a + 12 + (w1 & 0xFFF)
        puerto = struct.unpack_from("<I", rom, lit_puerto - base)[0]
        if puerto != 0x083F0000:
            raise SystemExit(f"portfix: {a:08X} no apunta al puerto ({puerto:08X})")

        desp = lit_var - (a + 8)
        if not 0 <= desp < 4096:
            raise SystemExit(f"portfix: literal fuera de alcance en {a:08X}")

        var = struct.unpack_from("<I", rom, lit_var - base)[0]
        rom[off:off + 16] = struct.pack("<IIII",
                                        LDR_R1_PC | desp,
                                        MOV_R0_IMM | VALOR_LISTO,
                                        STRH_R0_R1,
                                        MOV_PC_LR)
        hechos.append((a, var))

    print("  " + str(len(hechos)) + " copias: "
          + " ".join(f"{a:08X}->var {v:08X}" for a, v in hechos))
    return len(hechos)
