"""Igualdad byte a byte del codificador de audio contra los .gbs originales.

No tenemos el WAV exacto que se le dio al conversor original, pero no hace
falta: el cuantizador es determinista y su salida es alcanzable. Si se
decodifica un .gbs original y se vuelve a construir con ello una entrada de
44100 Hz que el diezmado del modo devuelva intacta —repitiendo cada muestra
`diezmado` veces, cosa que tanto seleccionar como promediar deshacen— entonces
codificar esa entrada tiene que reproducir el fichero **byte a byte**.

Es una prueba exacta y cubre de golpe el diezmado, la cabecera de bloque, el
recorte del indice, los tres cuantizadores y los tres empaquetados.
"""
import struct

import numpy as np
import pytest

from gbamedia.core import gbs_decode as gbs
from gbamedia.core import gbs_encode as enc

FICHEROS = {
    "furretwalk.gbs": 0,
    "furretwalk_mono11.gbs": 1,
    "furretwalk_mono16.gbs": 2,
    "furretwalk_mono32.gbs": 3,
    "furretwalk_mono64_l.gbs": 4,
    "furretwalk_mono64_r.gbs": 4,
}


def _entrada_equivalente(datos: bytes, modo: gbs.Modo) -> np.ndarray:
    """PCM 44100/estereo que el diezmado del modo devuelve tal cual."""
    audio = gbs.decodificar(datos)
    s = np.array(audio.muestras, dtype=np.int32)
    if modo.canales == 1:
        p = np.repeat(s[:, 0], modo.diezmado)
        pcm = np.stack([p, p], axis=1)
    else:
        pcm = np.repeat(s, modo.diezmado, axis=0)
    return pcm.astype(np.int16)


def _comprueba(datos: bytes, numero: int):
    modo = gbs.MODOS[numero]
    salida = enc.codificar(_entrada_equivalente(datos, modo), modo)
    assert len(salida) == len(datos), "el tamano no cuadra"
    assert salida[:0x200] == datos[:0x200], "la cabecera no cuadra"
    if salida != datos:
        primero = next(i for i, (a, b) in enumerate(zip(salida, datos))
                       if a != b)
        pytest.fail(f"primer byte distinto en {primero:#x} "
                    f"(bloque {(primero - 0x200) // modo.bloque})")


def _recorta(datos: bytes, modo: gbs.Modo, bloques: int) -> bytes:
    """Los primeros bloques, con el tamano de la cabecera puesto al dia."""
    corto = bytearray(datos[:0x200 + modo.bloque * bloques])
    struct.pack_into("<I", corto, 4, len(corto))
    return bytes(corto)


@pytest.mark.parametrize("nombre", sorted(FICHEROS))
def test_identico_primeros_bloques(originales, nombre):
    """Tramo corto, para la suite rapida."""
    modo = gbs.MODOS[FICHEROS[nombre]]
    _comprueba(_recorta((originales / nombre).read_bytes(), modo, 8),
               modo.numero)


@pytest.mark.lento
@pytest.mark.parametrize("nombre", sorted(FICHEROS))
def test_identico_fichero_entero(originales, nombre):
    _comprueba((originales / nombre).read_bytes(), FICHEROS[nombre])


# --- opciones de codificacion -------------------------------------------

def _rampa(n=64):
    izq = np.arange(n, dtype=np.int16) * 100
    der = -izq
    return np.stack([izq, der], axis=1)


@pytest.mark.parametrize("numero", [1, 2, 3, 4])
def test_canal_selecciona_columna(numero):
    """Channel elige un canal entero; nunca mezcla los dos."""
    modo = gbs.MODOS[numero]
    pcm = _rampa()
    izq = enc.preparar(pcm, modo, canal=enc.IZQUIERDO)
    der = enc.preparar(pcm, modo, canal=enc.DERECHO)
    assert np.all(izq >= 0x8000)
    assert np.all(der <= 0x8000)


def test_volumen_satura():
    pcm = np.full((16, 2), 20000, dtype=np.int16)
    modo = gbs.MODOS[2]
    assert enc.preparar(pcm, modo, volumen=0)[0] == 20000 + 0x8000
    assert enc.preparar(pcm, modo, volumen=1)[0] == 32767 + 0x8000


def test_diezmado_selecciona_o_promedia():
    """Los modos 0 y 2 seleccionan; los modos 3 y 4 promedian."""
    pcm = np.stack([np.array([0, 1000, 0, 1000] * 8, dtype=np.int16)] * 2,
                   axis=1)
    selecciona = enc.preparar(pcm, gbs.MODOS[2])
    promedia = enc.preparar(pcm, gbs.MODOS[3])
    assert selecciona[0] - 0x8000 == 0 and selecciona[1] - 0x8000 == 0
    assert promedia[0] - 0x8000 == 500


def test_bloque_incompleto_se_rellena():
    """La salida es siempre un numero entero de bloques."""
    modo = gbs.MODOS[4]
    pcm = np.zeros((modo.entrada_por_bloque + 400, 2), dtype=np.int16)
    salida = enc.codificar(pcm, modo)
    assert (len(salida) - 0x200) % modo.bloque == 0
    assert len(salida) - 0x200 == modo.bloque * 2
