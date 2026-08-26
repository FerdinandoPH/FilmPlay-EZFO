"""Decodificador del formato .gbs, transcrito de savemu.dll.

Los cinco MusicMode: FUN_10002110 (modo 0), FUN_100023d0 (1), FUN_10002210 (2),
FUN_10002560 (3 y 4), y los cuantizadores FUN_10002310 (4 bits),
FUN_100024c0 (3 bits) y FUN_10002730 (2 bits).

Validado sobre los seis .gbs originales (GBS_FORMAT.md); el modo 2 sale
bit-identico al canal izquierdo del modo 0.
"""
import struct
from dataclasses import dataclass

from .containers import TAM_CABECERA, FormatoInvalido, leer_cabecera
from .gbs_tables import STEP, IDX4, IDX3, DELTA2


@dataclass(frozen=True)
class Modo:
    numero: int
    bloque: int          # bytes por bloque
    cabecera: int        # bytes de cabecera de bloque
    muestras: int        # muestras por bloque, contando la de la cabecera
    canales: int
    frecuencia: int
    bits: int            # bits por muestra codificada
    promedia: bool       # True = diezma promediando; False = seleccionando
    diezmado: int        # 1, 2 o 4
    etiqueta: str

    @property
    def codificadas(self) -> int:
        return self.muestras - 1

    @property
    def entrada_por_bloque(self) -> int:
        """Muestras de 44100 Hz que consume un bloque, por canal."""
        return self.muestras * self.diezmado


MODOS = {
    0: Modo(0, 0x400, 8, 1017, 2, 22050, 4, False, 2, "8:1 Stereo"),
    1: Modo(1, 0x400, 4, 2721, 1, 44100, 3, False, 1, "11:1 Mono"),
    2: Modo(2, 0x200, 4, 1017, 1, 22050, 4, False, 2, "16:1 Mono"),
    3: Modo(3, 0x200, 4, 2033, 1, 22050, 2, True, 2, "32:1 Mono"),
    4: Modo(4, 0x100, 4, 1009, 1, 11025, 2, True, 4, "64:1 Mono"),
}


def acota(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else (hi if v > hi else v)


def dec4(codigo: int, pred: int, idx: int) -> tuple[int, int]:
    """IMA de 4 bits. El predictor vive en 0..65535 (muestra + 0x8000)."""
    s = STEP[idx]
    dif = s >> 3
    if codigo & 4:
        dif += s
    if codigo & 2:
        dif += s >> 1
    if codigo & 1:
        dif += s >> 2
    if codigo & 8:
        dif = -dif
    return acota(pred + dif, 0, 0xFFFF), acota(idx + IDX4[codigo], 0, 88)


def dec3(codigo: int, pred: int, idx: int) -> tuple[int, int]:
    """IMA de 3 bits: bit 2 signo, bits 1-0 magnitud."""
    s = STEP[idx]
    dif = s >> 2
    if codigo & 2:
        dif += s
    if codigo & 1:
        dif += s >> 1
    if codigo & 4:
        dif = -dif
    return acota(pred + dif, 0, 0xFFFF), acota(idx + IDX3[codigo], 0, 88)


def dec2(codigo: int, pred: int, idx: int) -> tuple[int, int]:
    """2 bits: NO es IMA. Tabla de deltas propia, indice en pasos de 4."""
    pred = acota(pred + DELTA2[idx + codigo], 0, 0xFFFF)
    idx = acota(idx + (4 if codigo & 1 else -4), 0, 0x160)
    return pred, idx


@dataclass
class Audio:
    modo: Modo
    muestras: list          # tuplas de 1 o 2 valores con signo
    saltos: list            # salto del predictor en cada frontera de bloque

    @property
    def duracion(self) -> float:
        return len(self.muestras) / self.modo.frecuencia

    @property
    def salto_medio(self) -> float:
        return sum(self.saltos) / len(self.saltos) if self.saltos else 0.0


def decodificar(datos: bytes) -> Audio:
    cab = leer_cabecera(datos)
    if not cab.es_audio:
        raise FormatoInvalido("no es un .gbs")
    if cab.modo not in MODOS:
        raise FormatoInvalido(f"MusicMode desconocido: {cab.modo}")
    m = MODOS[cab.modo]
    fuera: list = []
    saltos: list = []
    prev_a = prev_b = prev = 0
    p = TAM_CABECERA
    while p + m.bloque <= len(datos):
        b = datos[p:p + m.bloque]
        if m.numero == 0:
            pa, ia, pb, ib = struct.unpack_from("<HHHH", b, 0)
            if fuera:
                saltos.append(abs(pa - prev_a) + abs(pb - prev_b))
            fuera.append((pa - 0x8000, pb - 0x8000))
            for byte in b[8:8 + m.codificadas]:
                pa, ia = dec4(byte & 15, pa, ia)
                pb, ib = dec4(byte >> 4, pb, ib)
                fuera.append((pa - 0x8000, pb - 0x8000))
            prev_a, prev_b = pa, pb
        else:
            pr, ix = struct.unpack_from("<HH", b, 0)
            if fuera:
                saltos.append(abs(pr - prev))
            fuera.append((pr - 0x8000,))
            if m.numero == 1:
                # 8 codigos de 3 bits en 24 bits big endian, el primero abajo
                for g in range(0, m.codificadas // 8 * 3, 3):
                    v = (b[4 + g] << 16) | (b[5 + g] << 8) | b[6 + g]
                    for k in range(8):
                        pr, ix = dec3((v >> (3 * k)) & 7, pr, ix)
                        fuera.append((pr - 0x8000,))
            elif m.numero == 2:
                for byte in b[4:4 + m.codificadas // 2]:
                    pr, ix = dec4(byte & 15, pr, ix)
                    fuera.append((pr - 0x8000,))
                    pr, ix = dec4(byte >> 4, pr, ix)
                    fuera.append((pr - 0x8000,))
            else:
                for byte in b[4:4 + m.codificadas // 4]:
                    for k in range(4):
                        pr, ix = dec2((byte >> (2 * k)) & 3, pr, ix)
                        fuera.append((pr - 0x8000,))
            prev = pr
        p += m.bloque
    return Audio(m, fuera, saltos)


def contar_bloques(datos: bytes) -> tuple[Modo, int]:
    """Modo y numero de bloques sin decodificar una sola muestra."""
    cab = leer_cabecera(datos)
    if not cab.es_audio:
        raise FormatoInvalido("no es un .gbs")
    m = MODOS[cab.modo]
    return m, (len(datos) - TAM_CABECERA) // m.bloque
