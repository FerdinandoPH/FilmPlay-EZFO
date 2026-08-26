"""El nucleo en C tiene que dar el **mismo byte** que el de Python.

Es lo unico que hace mantenible tener dos implementaciones: la de Python es la
de referencia -legible, y la que se lee cuando hay que entender el formato- y
la de C es la que corre. Todo es aritmetica entera, asi que la igualdad exacta
es alcanzable y cualquier diferencia es un error de una de las dos.

Sin la extension compilada las pruebas se saltan, no fallan: el paquete
funciona igual sin ella.
"""
import numpy as np
import pytest

from gbamedia.core import gbm_encode as enc
from gbamedia.core import gbs_encode as aud
from gbamedia.core import fast
from gbamedia.core.gbs_decode import MODOS

pytestmark = pytest.mark.skipif(not fast.hay_c(),
                                reason="no esta compilada la extension en C")

PRESETS = ["alta", "estandar", "compresion"]


def _pelicula(n=6):
    """Degradado con un cuadrado que se mueve y un poco de ruido encima.

    El ruido es lo que hace que el arbol baje hasta las hojas de dos pixeles y
    que el control de tamano tenga que subir la tolerancia.
    """
    rng = np.random.default_rng(11)
    fuera = []
    for t in range(n):
        img = np.zeros((160, 240, 3), dtype=np.uint8)
        img[:, :, 0] = np.arange(240, dtype=np.uint8)[None, :]
        img[:, :, 2] = np.arange(160, dtype=np.uint8)[:, None]
        y, x = 20 + t * 3, 10 + t * 5
        img[y:y + 40, x:x + 40] = (255, 255, 0)
        img[100:130, 40:200] = rng.integers(0, 256, (30, 160, 3), dtype=np.uint8)
        fuera.append(enc.a_bgr555(img))
    return fuera


def _codifica(imagenes, calidad, con_c: bool):
    """Codifica con el nucleo que se pida y comprueba que se ha usado ese."""
    with pytest.MonkeyPatch.context() as m:
        if not con_c:
            m.setattr(enc, "nucleo", None)
        cod = enc.CodificadorVideo(calidad)
        payloads = [cod.frame(img) for img in imagenes]
        _, _, sal = enc.codificar_frame(imagenes[0], imagenes[0], calidad)
    usado_c = isinstance(sal, enc.SalidaC)
    assert usado_c == con_c, "no se ha usado el nucleo que pedia la prueba"
    return payloads, cod.referencia.copy()


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("busqueda", ["rapida", "exhaustiva"])
def test_el_video_sale_identico(preset, busqueda):
    from dataclasses import replace
    calidad = replace(enc.CALIDADES[preset], busqueda=busqueda)
    if not calidad.vectores and busqueda == "exhaustiva":
        pytest.skip("sin vectores no hay busqueda que comparar")
    imagenes = _pelicula()

    con_c, ref_c = _codifica(imagenes, calidad, True)
    con_py, ref_py = _codifica(imagenes, calidad, False)

    assert [len(p) for p in con_c] == [len(p) for p in con_py]
    for n, (a, b) in enumerate(zip(con_c, con_py)):
        assert a == b, f"frame {n}: el payload difiere"
    assert np.array_equal(ref_c, ref_py), "la reconstruccion difiere"


def test_el_video_con_ruido_puro_tambien():
    """Ruido puro: el frame no cabe y el control de tamano tiene que subir la
    tolerancia. Es el camino que menos se recorre y el mas facil de romper."""
    rng = np.random.default_rng(5)
    imagenes = [enc.a_bgr555(rng.integers(0, 256, (160, 240, 3), dtype=np.uint8))
                for _ in range(2)]
    calidad = enc.CALIDADES["estandar"]

    con_c, ref_c = _codifica(imagenes, calidad, True)
    con_py, ref_py = _codifica(imagenes, calidad, False)
    assert con_c == con_py
    assert np.array_equal(ref_c, ref_py)


def _pcm(segundos=1.5):
    """Algo con tono y con ruido, que es donde el cuantizador se moja."""
    rng = np.random.default_rng(3)
    n = int(44100 * segundos)
    t = np.arange(n) / 44100.0
    onda = (12000 * np.sin(2 * np.pi * 440 * t)
            + 6000 * np.sin(2 * np.pi * 97 * t))
    ruido = rng.integers(-3000, 3000, n)
    izq = np.clip(onda + ruido, -32768, 32767)
    der = np.clip(onda * 0.6 - ruido, -32768, 32767)
    return np.stack([izq, der], axis=1).astype(np.int16)


@pytest.mark.parametrize("numero", sorted(MODOS))
def test_el_audio_sale_identico(numero):
    pcm = _pcm()
    modo = MODOS[numero]
    for volumen in (0, 2):
        con_c = aud.codificar(pcm, modo, 0, volumen)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(aud, "nucleo", None)
            con_py = aud.codificar(pcm, modo, 0, volumen)
        assert con_c == con_py, f"modo {numero}, volumen {volumen}"


def test_el_audio_en_c_avisa_y_se_deja_parar():
    """El progreso y la cancelacion tienen que cruzar la frontera con C."""
    import threading

    from gbamedia.errors import Cancelado

    pcm = _pcm(4.0)
    vistos = []
    aud.codificar(pcm, MODOS[2], 0, 0, progreso=lambda h, t: vistos.append(h))
    assert len(vistos) > 1 and vistos == sorted(vistos)

    cancelar = threading.Event()
    cancelar.set()
    with pytest.raises(Cancelado):
        aud.codificar(pcm, MODOS[2], 0, 0, cancelar=cancelar)


def _decodifica(datos, con_c: bool, limite=None):
    from gbamedia.core import gbm_decode as dec
    with pytest.MonkeyPatch.context() as m:
        if not con_c:
            m.setattr(dec, "nucleo", None)
        sumidero = dec.SumideroBuffer()
        stats = [s.__dict__ for s in dec.decodificar(datos, sumidero, limite)]
    return stats, sumidero.frame


def test_el_decodificador_en_c_dice_lo_mismo():
    """La verificacion de lo producido pasa por el decodificador, asi que el
    de C tiene que contar los mismos flujos y pintar los mismos pixeles."""
    imagenes = _pelicula(8)
    cod = enc.CodificadorVideo("estandar")
    datos = enc.envolver([cod.frame(img) for img in imagenes])

    con_c, frame_c = _decodifica(datos, True)
    con_py, frame_py = _decodifica(datos, False)
    assert con_c == con_py
    assert frame_c == frame_py


@pytest.mark.lento
def test_el_decodificador_en_c_sobre_los_originales(videos):
    """Contra los .gbm del conversor original, que es lo unico que prueba el
    decodificador de verdad: nuestro codificador no emite todas las formas."""
    import glob
    for ruta in sorted(glob.glob(str(videos / "*.gbm")))[:3]:
        datos = open(ruta, "rb").read()
        con_c, frame_c = _decodifica(datos, True, limite=120)
        con_py, frame_py = _decodifica(datos, False, limite=120)
        assert con_c == con_py, ruta
        assert frame_c == frame_py, ruta
