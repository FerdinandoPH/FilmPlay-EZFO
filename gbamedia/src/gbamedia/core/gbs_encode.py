"""Codificador del formato .gbs.

Contrapartida de `gbs_decode`. La entrada es siempre PCM de 16 bits con signo
a 44100 Hz y dos canales, que es lo que asume el conversor original; el
diezmado hasta la frecuencia de cada modo lo hace este modulo, respetando la
distincion critica entre **seleccionar** (modos 0 y 2) y **promediar**
(modos 3 y 4).

Orden de las operaciones, tomado de savemu.dll: volumen y seleccion de canal
van ANTES del diezmado, de modo que la media se hace siempre sobre muestras del
mismo canal y no sobre una mezcla.
"""
import struct

import numpy as np

from ..errors import Cancelado
from .containers import MAGICO_AUDIO, TAM_CABECERA, escribir_cabecera
from .gbs_decode import MODOS, Modo, acota, dec2, dec3, dec4
from .fast import nucleo
from .gbs_tables import STEP, DELTA2

IZQUIERDO = 0
DERECHO = 1

# Volume del INI: 0..3 = x1, x2, x4, x8
GANANCIAS = (1, 2, 4, 8)

# Al escribir la cabecera de bloque, los modos 2, 3 y 4 acotan el indice a
# 0xA0. En los modos de 2 bits el indice llega hasta 0x160, asi que el recorte
# se nota de verdad: el codificador tiene que continuar desde el valor
# recortado o se desincroniza con el decodificador.
TOPE_INDICE_CABECERA = 0xA0


def enc4(objetivo: int, pred: int, idx: int) -> int:
    """IMA de 4 bits: bit 3 signo, bits 2-0 magnitud."""
    dif = objetivo - pred
    codigo = 0
    if dif < 0:
        codigo = 8
        dif = -dif
    paso = STEP[idx]
    if dif >= paso:
        codigo |= 4
        dif -= paso
    if dif >= paso >> 1:
        codigo |= 2
        dif -= paso >> 1
    if dif >= paso >> 2:
        codigo |= 1
    return codigo


def enc3(objetivo: int, pred: int, idx: int) -> int:
    """IMA de 3 bits: bit 2 signo, bits 1-0 magnitud."""
    dif = objetivo - pred
    codigo = 0
    if dif < 0:
        codigo = 4
        dif = -dif
    paso = STEP[idx]
    if dif >= paso:
        codigo |= 2
        dif -= paso
    if dif >= paso >> 1:
        codigo |= 1
    return codigo


def enc2(objetivo: int, pred: int, idx: int) -> int:
    """2 bits: no es IMA, asi que se elige el mas cercano de los cuatro.

    Son solo cuatro candidatos, y la tabla no es monotona en las filas altas
    (desborda el int16), asi que buscar es mas seguro que despejar.
    """
    mejor = 0
    mejor_error = None
    for codigo in range(4):
        recon = acota(pred + DELTA2[idx + codigo], 0, 0xFFFF)
        error = abs(objetivo - recon)
        if mejor_error is None or error < mejor_error:
            mejor, mejor_error = codigo, error
    return mejor


CUANTIZADORES = {4: (enc4, dec4), 3: (enc3, dec3), 2: (enc2, dec2)}


def preparar(pcm: np.ndarray, modo: Modo, canal: int = IZQUIERDO,
             volumen: int = 0) -> np.ndarray:
    """PCM 44100/estereo -> muestras sin signo (0..65535) ya diezmadas.

    Devuelve un array (n,) para los modos mono y (n,2) para el modo 0.
    """
    if pcm.ndim != 2 or pcm.shape[1] != 2:
        raise ValueError("se espera PCM estereo con forma (n, 2)")
    x = pcm.astype(np.int32)

    ganancia = GANANCIAS[volumen]
    if ganancia != 1:
        x = np.clip(x * ganancia, -32768, 32767)

    if modo.canales == 1:
        # Channel desplaza el puntero de entrada un short, de modo que todo lo
        # que venga despues trabaja sobre un solo canal.
        x = x[:, canal]

    d = modo.diezmado
    if d > 1:
        n = (len(x) // d) * d
        x = x[:n]
        if modo.promedia:
            forma = (n // d, d) if x.ndim == 1 else (n // d, d, 2)
            x = x.reshape(forma).mean(axis=1).astype(np.int32)
        else:
            x = x[::d]

    return (x + 0x8000).astype(np.int32)


def _empaqueta(codigos: list[int], modo: Modo) -> bytes:
    """Codigos de una cadena mono al empaquetado del modo."""
    n = modo.bloque - modo.cabecera
    fuera = bytearray(n)
    if modo.bits == 4:
        for i in range(0, len(codigos), 2):
            fuera[i // 2] = codigos[i] | (codigos[i + 1] << 4)
    elif modo.bits == 3:
        # 8 codigos en 24 bits big endian, el primero en los bits mas bajos
        for g in range(len(codigos) // 8):
            v = 0
            for k in range(8):
                v |= codigos[g * 8 + k] << (3 * k)
            o = g * 3
            fuera[o] = (v >> 16) & 0xFF
            fuera[o + 1] = (v >> 8) & 0xFF
            fuera[o + 2] = v & 0xFF
    else:
        for i in range(0, len(codigos), 4):
            fuera[i // 4] = (codigos[i] | (codigos[i + 1] << 2)
                             | (codigos[i + 2] << 4) | (codigos[i + 3] << 6))
    return bytes(fuera)


def _bloque_mono(muestras, modo: Modo, pred: int, idx: int):
    """Un bloque mono. Devuelve (bytes, pred, idx) para encadenar."""
    enc, dec = CUANTIZADORES[modo.bits]
    pred = int(muestras[0])
    idx = min(idx, TOPE_INDICE_CABECERA)
    cab = struct.pack("<HH", pred, idx)
    codigos = []
    for objetivo in muestras[1:]:
        c = enc(int(objetivo), pred, idx)
        codigos.append(c)
        pred, idx = dec(c, pred, idx)
    return cab + _empaqueta(codigos, modo), pred, idx


def _bloque_estereo(muestras, modo: Modo, estado):
    """Modo 0: los dos canales entrelazados nibble a nibble."""
    pa, ia, pb, ib = estado
    pa = int(muestras[0, 0])
    pb = int(muestras[0, 1])
    cab = struct.pack("<HHHH", pa, ia, pb, ib)
    cuerpo = bytearray(modo.bloque - modo.cabecera)
    for i in range(1, modo.muestras):
        ca = enc4(int(muestras[i, 0]), pa, ia)
        cb = enc4(int(muestras[i, 1]), pb, ib)
        # nibble bajo = canal izquierdo
        cuerpo[i - 1] = ca | (cb << 4)
        pa, ia = dec4(ca, pa, ia)
        pb, ib = dec4(cb, pb, ib)
    return cab + bytes(cuerpo), (pa, ia, pb, ib)


def codificar_muestras(muestras: np.ndarray, modo: Modo,
                       progreso=None, cancelar=None) -> bytes:
    """Muestras ya diezmadas y con sesgo -> cuerpo del fichero, sin cabecera."""
    n = modo.muestras
    completos = len(muestras) // n
    resto = len(muestras) - completos * n
    if resto:
        # El ultimo bloque se completa repitiendo la ultima muestra: rellenar
        # con silencio meteria un chasquido al final.
        relleno = np.repeat(muestras[-1:], n - resto, axis=0)
        muestras = np.concatenate([muestras, relleno])
        completos += 1

    # El ADPCM es secuencial de cabo a rabo (cada muestra parte de la
    # anterior), asi que aqui no hay nada que repartir: lo unico que se puede
    # hacer es contar por donde va y dejarse parar.
    aviso = max(1, completos // 100)

    if nucleo is not None:
        def asoma(hechos, total):
            if cancelar is not None and cancelar.is_set():
                raise Cancelado()
            if progreso:
                progreso(hechos, total)
        datos = np.ascontiguousarray(muestras, dtype=np.int32)
        return nucleo.codifica_adpcm(datos, modo.numero, modo.bloque,
                                     modo.cabecera, n, modo.bits,
                                     asoma if (progreso or cancelar) else None,
                                     aviso)

    fuera = bytearray()
    if modo.numero == 0:
        estado = (0, 0, 0, 0)
        for b in range(completos):
            trozo = muestras[b * n:(b + 1) * n]
            datos, estado = _bloque_estereo(trozo, modo, estado)
            fuera += datos
            _asoma(b, completos, aviso, progreso, cancelar)
    else:
        pred = idx = 0
        for b in range(completos):
            trozo = muestras[b * n:(b + 1) * n]
            datos, pred, idx = _bloque_mono(trozo, modo, pred, idx)
            fuera += datos
            _asoma(b, completos, aviso, progreso, cancelar)
    return bytes(fuera)


def _asoma(b, completos, cada, progreso, cancelar):
    if b % cada:
        return
    if cancelar is not None and cancelar.is_set():
        raise Cancelado()
    if progreso:
        progreso(b + 1, completos)


def codificar(pcm: np.ndarray, modo: int | Modo = 0, canal: int = IZQUIERDO,
              volumen: int = 0, progreso=None, cancelar=None) -> bytes:
    """PCM 44100 Hz / 16 bits / estereo -> fichero .gbs completo."""
    m = modo if isinstance(modo, Modo) else MODOS[modo]
    cuerpo = codificar_muestras(preparar(pcm, m, canal, volumen), m,
                                progreso, cancelar)
    tamano = TAM_CABECERA + len(cuerpo)
    return escribir_cabecera(*MAGICO_AUDIO, tamano, m.numero) + cuerpo
