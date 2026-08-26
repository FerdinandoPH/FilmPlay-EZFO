"""Codificador de video: ida y vuelta contra el decodificador de la ROM.

La igualdad byte a byte con el conversor original no es alcanzable, asi que el
criterio es otro: que lo que producimos lo lea el decodificador de referencia
consumiendo los flujos exactos y reconstruyendo **exactamente** lo que el
codificador creia estar dejando, que es lo que garantiza que no haya deriva.
"""
import numpy as np
import pytest

from gbamedia.core import gbm_decode as gbm
from gbamedia.core import gbm_encode as enc
from gbamedia.core.bitwriter import EscritorBits

PRESETS = ["alta", "estandar", "compresion"]


def _muestra(t: int) -> np.ndarray:
    """Degradado fijo con un cuadrado que se desplaza: fuerza copias,
    rellenos solidos y, con vectores activos, compensacion de movimiento."""
    img = np.zeros((160, 240, 3), dtype=np.uint8)
    img[:, :, 0] = np.arange(240, dtype=np.uint8)[None, :]
    img[:, :, 2] = np.arange(160, dtype=np.uint8)[:, None]
    y, x = 20 + t * 3, 10 + t * 5
    img[y:y + 40, x:x + 40] = (255, 255, 0)
    return img


def _ida_y_vuelta(imagenes, calidad):
    """Codifica y devuelve (datos, reconstrucciones del codificador)."""
    cod = enc.CodificadorVideo(calidad)
    payloads, recons = [], []
    for img in imagenes:
        payloads.append(cod.frame(img))
        recons.append(cod.referencia.copy())
    return enc.envolver(payloads), recons


def _comprueba(datos, recons):
    sumidero = gbm.SumideroBuffer()
    n = 0
    for st in gbm.decodificar(datos, sumidero):
        assert st.colores_exactos, f"frame {st.indice}: colores sin consumir"
        assert st.bits_sobrantes < 32, f"frame {st.indice}: bits de mas"
        assert st.vectores_usados == st.tam_vectores, \
            f"frame {st.indice}: vectores sin consumir"
        fb = np.frombuffer(sumidero.frame, dtype="<u2").reshape(160, 240)
        assert np.array_equal(fb, recons[n]), \
            f"frame {st.indice}: la ROM reconstruiria otra cosa"
        n += 1
    assert n == len(recons)


def test_escritor_de_bits_cuadra_con_el_lector():
    rng = np.random.default_rng(7)
    for _ in range(50):
        secuencia = rng.integers(0, 2, rng.integers(1, 300)).tolist()
        w = EscritorBits()
        w.bits(*secuencia)
        datos = w.terminar()
        assert len(datos) == w.bytes_finales
        lector = gbm.LectorBits(datos)
        assert [lector.bit() for _ in secuencia] == secuencia
        assert lector.sobran < 32


def test_conversion_de_color():
    rng = np.random.default_rng(1)
    rgb = rng.integers(0, 256, (160, 240, 3), dtype=np.uint8)
    v = enc.a_bgr555(rgb)
    assert v.dtype == np.uint16
    assert int(v.max()) < 0x8000, "el bit 15 tiene que quedar a cero"
    # cuantizar dos veces no cambia nada
    assert np.array_equal(v, enc.a_bgr555(enc.a_rgb888(v)))


@pytest.mark.parametrize("calidad", PRESETS)
def test_ida_y_vuelta(calidad):
    imagenes = [_muestra(t) for t in range(6)]
    datos, recons = _ida_y_vuelta(imagenes, calidad)
    _comprueba(datos, recons)


def test_calidad_alta_no_pierde_nada():
    """Con tolerancia cero toda hoja es exacta, y la de 2 px siempre lo es."""
    imagenes = [_muestra(t) for t in range(4)]
    _, recons = _ida_y_vuelta(imagenes, "alta")
    for img, rec in zip(imagenes, recons):
        assert np.array_equal(rec, enc.a_bgr555(img))


def test_calidad_alta_no_emite_vectores():
    imagenes = [_muestra(t) for t in range(4)]
    datos, _ = _ida_y_vuelta(imagenes, "alta")
    assert all(st.tam_vectores == 0 for st in gbm.decodificar(datos))


def test_el_desplazamiento_puro_usa_vectores():
    """Una imagen que solo se mueve es el caso para el que existen."""
    base = np.zeros((160, 240, 3), dtype=np.uint8)
    y, x = np.mgrid[40:120, 60:180]
    base[40:120, 60:180, 0] = ((x // 3) * 37) % 256
    base[40:120, 60:180, 1] = ((y // 3) * 53) % 256
    movida = np.roll(base, (3, 5), axis=(0, 1))

    datos, recons = _ida_y_vuelta([base, movida], "estandar")
    _comprueba(datos, recons)
    st = list(gbm.decodificar(datos))
    assert st[1].vectores_usados > 0


@pytest.mark.lento
def test_control_de_tamano_con_ruido():
    """Ruido puro no cabe en el formato: hay que subir la tolerancia.

    Cada pareja de pixeles pediria dos colores propios, 76800 bytes solo de
    color, y los campos de tamano son u16.
    """
    rng = np.random.default_rng(0)
    imagenes = [rng.integers(0, 256, (160, 240, 3), dtype=np.uint8)
                for _ in range(2)]
    for nombre in PRESETS:
        calidad = enc.CALIDADES[nombre]
        datos, recons = _ida_y_vuelta(imagenes, nombre)
        _comprueba(datos, recons)
        for st in gbm.decodificar(datos):
            total = 4 + st.tam_bitstream + st.tam_colores + st.tam_vectores
            assert total <= calidad.tope, f"{nombre}: se pasa del tope duro"


def test_el_ruido_puro_respeta_el_tope_duro():
    """Version rapida del control de tamano: un frame y sin busqueda."""
    rng = np.random.default_rng(0)
    imagen = rng.integers(0, 256, (160, 240, 3), dtype=np.uint8)
    datos, recons = _ida_y_vuelta([imagen], "alta")
    _comprueba(datos, recons)
    st = next(iter(gbm.decodificar(datos)))
    total = 4 + st.tam_bitstream + st.tam_colores + st.tam_vectores
    assert total <= enc.CALIDADES["alta"].tope


def test_cabecera_del_fichero():
    datos, _ = _ida_y_vuelta([_muestra(0)], "alta")
    assert datos[0:4] == b"GBAM" and datos[8:12] == b"MOVI"
    assert int.from_bytes(datos[4:8], "little") == len(datos)
    assert int.from_bytes(datos[0x10:0x14], "little") == 4


@pytest.mark.lento
def test_reencodar_un_original_es_sin_perdida(videos):
    """Los frames de M00004 vuelven a salir intactos, y en menos bytes.

    Sirve de prueba con material real sin depender de ffmpeg: se decodifica un
    .gbm original, se usan sus frames como fuente y se vuelve a codificar.
    """
    datos = (videos / "M00004.gbm").read_bytes()
    sumidero = gbm.SumideroBuffer()
    fuente, tam_original = [], 0
    for st in gbm.decodificar(datos, sumidero, limite=80):
        fuente.append(np.frombuffer(sumidero.frame, dtype="<u2")
                      .reshape(160, 240).copy())
        tam_original += 4 + st.tam_bitstream + st.tam_colores + st.tam_vectores

    salida, recons = _ida_y_vuelta(fuente, "alta")
    _comprueba(salida, recons)
    for original, nuestro in zip(fuente, recons):
        assert np.array_equal(original, nuestro), "la calidad alta pierde"
    nuestro_tam = len(salida) - 0x200 - 2 * len(fuente)
    assert nuestro_tam < tam_original


# --- troceado y busqueda -----------------------------------------------

def test_los_trozos_se_decodifican_igual_de_bien():
    """Cortar el video y arrancar cada trozo contra negro sigue siendo valido.

    El formato no tiene keyframes: el decodificador solo aplica diferencias, y
    un trozo que empieza contra negro se describe entero. Es lo que permite
    repartir un video entre varios procesos.
    """
    from gbamedia.jobs.parallel import codificar_video
    imagenes = [_muestra(t) for t in range(9)]
    payloads = codificar_video(iter(imagenes), "estandar",
                               trabajadores=1, trozo=3)
    assert len(payloads) == len(imagenes)

    datos = enc.envolver(payloads)
    frames = 0
    for st in gbm.decodificar(datos):
        assert st.colores_exactos and st.bits_sobrantes < 32
        assert st.vectores_usados == st.tam_vectores
        frames += 1
    assert frames == len(imagenes)


def test_el_resultado_no_depende_del_numero_de_procesos():
    """Los cortes son los mismos con uno o con varios procesos: si no, dos
    maquinas darian ficheros distintos del mismo original."""
    from gbamedia.jobs.parallel import codificar_video
    imagenes = [_muestra(t) for t in range(8)]
    uno = codificar_video(iter(imagenes), "estandar", trabajadores=1, trozo=3)
    varios = codificar_video(iter(imagenes), "estandar", trabajadores=4,
                             trozo=3)
    assert uno == varios


def test_la_busqueda_rapida_encuentra_lo_mismo_en_lo_facil():
    """Con un desplazamiento limpio y uniforme, la criba tiene que dar con el
    vector exacto igual que la exhaustiva."""
    rng = np.random.default_rng(3)
    base = rng.integers(0, 1 << 15, (160, 240), dtype=np.uint16)
    movida = np.roll(base, (2, -3), axis=(0, 1))
    activos = np.ones((enc.BLOQUES_Y, enc.BLOQUES_X), dtype=bool)

    idx_lento, _, err_lento = enc.buscar_vectores(movida, base, activos)
    idx_rapido, _, err_rapido = enc.buscar_vectores_rapido(movida, base, activos)
    # En los bordes el vector lee la fila de al lado y no hay solucion buena;
    # dentro, las dos busquedas tienen que coincidir en error cero.
    dentro = (slice(1, -1), slice(1, -1))
    assert np.array_equal(idx_lento[dentro], idx_rapido[dentro])
    assert err_rapido[8:-8, 8:-8].max() == 0


@pytest.mark.lento
def test_la_busqueda_rapida_no_empeora_el_resultado():
    """Sobre material sintetico con movimiento, la rapida no puede costar
    mucho mas ni reconstruir mucho peor que la exhaustiva."""
    from dataclasses import replace
    imagenes = [_muestra(t) for t in range(12)]
    medidas = {}
    for busqueda in ("rapida", "exhaustiva"):
        calidad = replace(enc.CALIDADES["estandar"], busqueda=busqueda)
        datos, recons = _ida_y_vuelta(imagenes, calidad)
        _comprueba(datos, recons)
        error = np.mean([
            (enc.componentes(r).astype(np.float64)
             - enc.componentes(enc.a_bgr555(i))) ** 2
            for r, i in zip(recons, imagenes)])
        medidas[busqueda] = (len(datos), error)
    bytes_rapida, error_rapida = medidas["rapida"]
    bytes_lenta, error_lenta = medidas["exhaustiva"]
    assert bytes_rapida <= bytes_lenta * 1.05
    assert error_rapida <= max(error_lenta * 1.2, 0.01)
