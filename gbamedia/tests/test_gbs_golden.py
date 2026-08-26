"""Regresion del decodificador de audio sobre los seis .gbs originales.

Todos salen del mismo furretwalk.wav (Channel Left, Volume Normal), lo que
permite compararlos entre si. Las cifras son las de GBS_FORMAT.md.
"""
import pytest

from gbamedia.core import gbs_decode as gbs
from gbamedia.core.containers import leer_cabecera

# fichero -> (modo, muestras, duracion)
FICHEROS = {
    "furretwalk.gbs": (0, 2373678, 107.65),
    "furretwalk_mono11.gbs": (1, 4748145, 107.67),
    "furretwalk_mono16.gbs": (2, 2373678, 107.65),
    "furretwalk_mono32.gbs": (3, 2372511, 107.60),
    "furretwalk_mono64_l.gbs": (4, 1186584, 107.63),
    "furretwalk_mono64_r.gbs": (4, 1186584, 107.63),
}


@pytest.mark.parametrize("nombre", sorted(FICHEROS))
def test_cabecera_y_bloques(originales, nombre):
    datos = (originales / nombre).read_bytes()
    modo_esperado, muestras, duracion = FICHEROS[nombre]

    cab = leer_cabecera(datos)
    assert cab.es_audio
    assert cab.tamano == len(datos)
    assert cab.modo == modo_esperado

    modo, bloques = gbs.contar_bloques(datos)
    assert bloques * modo.muestras == muestras
    assert bloques * modo.bloque + 0x200 == len(datos), "sobran bytes sueltos"
    assert muestras / modo.frecuencia == pytest.approx(duracion, abs=0.01)


def test_ratios_de_compresion():
    """Los cinco ratios son los que ofrece el desplegable del conversor."""
    esperados = {0: 8, 1: 11, 2: 16, 3: 32, 4: 64}
    for n, modo in gbs.MODOS.items():
        # La fuente es SIEMPRE 44100 Hz, 16 bits, estereo, tambien en los
        # modos mono: el ratio se cuenta contra esa entrada.
        entrada = modo.entrada_por_bloque * 2 * 2
        assert entrada / modo.bloque == pytest.approx(esperados[n], rel=0.05)
        assert modo.etiqueta.startswith(f"{esperados[n]}:1")


@pytest.mark.lento
def test_modo_2_identico_al_canal_izquierdo_del_modo_0(originales):
    """La validacion mas fuerte que hay: cero muestras difieren.

    Confirma de golpe el cuantizador de 4 bits, el diezmado por seleccion, el
    convenio del predictor con sesgo +0x8000 y que en el modo 0 el nibble bajo
    es el canal izquierdo.
    """
    est = gbs.decodificar((originales / "furretwalk.gbs").read_bytes())
    mono = gbs.decodificar((originales / "furretwalk_mono16.gbs").read_bytes())
    assert len(est.muestras) == len(mono.muestras)
    difieren = sum(1 for a, b in zip(est.muestras, mono.muestras)
                   if a[0] != b[0])
    assert difieren == 0


@pytest.mark.lento
@pytest.mark.parametrize("nombre", sorted(FICHEROS))
def test_duracion_y_continuidad(originales, nombre):
    _, muestras, duracion = FICHEROS[nombre]
    audio = gbs.decodificar((originales / nombre).read_bytes())
    assert len(audio.muestras) == muestras
    assert audio.duracion == pytest.approx(duracion, abs=0.01)
    # Cada bloque es autonomo, pero el predictor no debe saltar de golpe: si
    # el empaquetado estuviera mal, las fronteras chirriarian.
    assert audio.salto_medio < 3000, "saltos grandes en frontera de bloque"


@pytest.mark.lento
def test_canal_izquierdo_y_derecho_difieren(originales):
    izq = (originales / "furretwalk_mono64_l.gbs").read_bytes()
    der = (originales / "furretwalk_mono64_r.gbs").read_bytes()
    assert len(izq) == len(der)
    assert izq != der, "la opcion Channel no esta actuando"
    primero = next(i for i, (a, b) in enumerate(zip(izq, der)) if a != b)
    assert primero == 13149
