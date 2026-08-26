"""Regresion del decodificador de video sobre los siete .gbm originales.

Cubren los tres presets del conversor. Lo que se comprueba es lo que se
establecio al descifrar el formato (GBM_FORMAT.md):

  - el flujo de colores se consume hasta el ultimo byte exacto
  - sobran siempre menos de 32 bits (relleno de la ultima palabra)
  - los frames teselan el fichero y el tamano de la cabecera cuadra
"""
import struct

import pytest

from gbamedia.core import gbm_decode as gbm
from gbamedia.core.containers import leer_cabecera

# fichero -> (frames, preset, usa vectores)
FICHEROS = {
    "M00000.gbm": (1080, "alta", False),
    "M00001.gbm": (1080, "alta", False),
    "M00003.gbm": (1080, "alta", False),
    "M00004.gbm": (630, "alta", False),
    "M00005.gbm": (1005, "alta", False),
    "M00006.gbm": (1005, "compresion", True),
    "M00008.gbm": (630, "estandar", True),
}

# Frames que dejan un byte de vector sin consumir. Es un byte que el
# codificador original escribe y que nadie referencia: M00004 no usa vectores
# en ningun frame y aun asi trae dos. No es un fallo del decodificador.
BYTE_SUELTO = {("M00004.gbm", 358), ("M00004.gbm", 558), ("M00006.gbm", 625)}

# Cola inerte de 0x1002 bytes que el codificador anade a los frames 20 a 27.
COLA_BLOB = range(20, 28)
TAM_COLA = 0x1002


def _sin_consumir(nombre, st):
    """Bytes del flujo de vectores que quedan sin leer, ya justificados."""
    sobra = st.tam_vectores - st.vectores_usados
    if st.indice in COLA_BLOB:
        sobra -= TAM_COLA
    if (nombre, st.indice) in BYTE_SUELTO:
        sobra -= 1
    return sobra


@pytest.mark.parametrize("nombre", sorted(FICHEROS))
def test_cabecera_y_teselado(videos, nombre):
    datos = (videos / nombre).read_bytes()
    cab = leer_cabecera(datos)
    assert cab.es_video
    assert cab.tamano == len(datos), "el tamano de la cabecera no cuadra"
    assert cab.modo == 4, "el campo Mode vale 4 en todos los originales"

    # Los frames teselan exactamente hasta el ultimo byte
    p = 0x200
    n = 0
    while p + 2 <= len(datos):
        tam, = struct.unpack_from("<H", datos, p)
        if tam == 0:
            break
        p += 2 + tam
        n += 1
    assert p == len(datos), "los frames no llegan justos al final"
    assert n == FICHEROS[nombre][0]


@pytest.mark.parametrize("nombre", sorted(FICHEROS))
def test_flujos_primeros_frames(videos, nombre):
    """Tramo corto, para que la suite rapida siga siendo rapida."""
    datos = (videos / nombre).read_bytes()
    for st in gbm.decodificar(datos, limite=40):
        assert st.colores_exactos, f"frame {st.indice}: colores sin consumir"
        assert st.bits_sobrantes < 32, f"frame {st.indice}: sobran bits"
        assert _sin_consumir(nombre, st) == 0


@pytest.mark.lento
@pytest.mark.parametrize("nombre", sorted(FICHEROS))
def test_flujos_fichero_entero(videos, nombre):
    datos = (videos / nombre).read_bytes()
    frames, _, usa_vectores = FICHEROS[nombre]
    n = 0
    vectores = 0
    for st in gbm.decodificar(datos):
        assert st.colores_exactos, f"frame {st.indice}: colores sin consumir"
        assert st.bits_sobrantes < 32, f"frame {st.indice}: sobran bits"
        assert _sin_consumir(nombre, st) == 0, f"frame {st.indice}: vectores"
        vectores += st.vectores_usados
        n += 1
    assert n == frames
    assert (vectores > 0) is usa_vectores


@pytest.mark.lento
def test_imagen_frame_cero(videos):
    """El primer frame de M00004 son 600 copias de un buffer a negro."""
    datos = (videos / "M00004.gbm").read_bytes()
    sumidero = gbm.SumideroBuffer()
    st = next(gbm.decodificar(datos, sumidero, limite=1))
    assert st.hojas == {gbm.COPIA: 600}
    assert sumidero.frame == bytes(240 * 160 * 2)


@pytest.mark.lento
def test_estadisticas_de_hojas_por_preset(videos):
    """La calidad alta no usa compensacion de movimiento; la estandar si.

    Los dos ficheros son el mismo video de 630 frames, asi que la comparacion
    es directa (ver la tabla de GBM_FORMAT.md).
    """
    def hojas(nombre):
        total = {}
        for st in gbm.decodificar((videos / nombre).read_bytes()):
            for k, v in st.hojas.items():
                total[k] = total.get(k, 0) + v
        return total

    alta = hojas("M00004.gbm")
    estandar = hojas("M00008.gbm")

    assert alta.get(gbm.COPIA_VECTOR, 0) == 0
    assert estandar[gbm.COPIA_VECTOR] / sum(estandar.values()) > 0.20
    assert sum(alta.values()) > sum(estandar.values())
