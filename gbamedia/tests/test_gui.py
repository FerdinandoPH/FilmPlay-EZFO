"""La ventana, sin ventana: se prueba con la plataforma Qt fuera de pantalla.

Lo que se comprueba es el modelo de tres capas, que es donde de verdad se puede
meter la pata: perfil del lote, sobrescrituras por fichero, y volver atras.
"""
import os
import threading

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets                                    # noqa: E402

from gbamedia.gui.model import FALLIDO, HECHO, Fila, Lote      # noqa: E402
from gbamedia.jobs.convert import Destinos                     # noqa: E402
from gbamedia.gui.window import Ventana                         # noqa: E402
from gbamedia.jobs.options import Opciones                      # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ventana(app, hay_ffmpeg, monkeypatch):
    """La ventana, con los dialogos modales desactivados.

    Cerrar con ficheros sin convertir pregunta -es lo que se pide-, y un
    modal sin nadie que lo conteste cuelga la suite entera.
    """
    for nombre, respuesta in (
            ("question", QtWidgets.QMessageBox.StandardButton.Close),
            ("critical", QtWidgets.QMessageBox.StandardButton.Ok),
            ("warning", QtWidgets.QMessageBox.StandardButton.Ok),
            ("information", QtWidgets.QMessageBox.StandardButton.Ok)):
        monkeypatch.setattr(QtWidgets.QMessageBox, nombre,
                            staticmethod(lambda *a, r=respuesta, **k: r))
    v = Ventana()
    yield v
    v.close()


# --- modelo, sin Qt de por medio ---------------------------------------

def _fila_de_video(lote, nombre="a.mp4"):
    """Una fila que ya sabe que es un video (normalmente lo dice ffprobe)."""
    fila = lote.anadir(nombre)
    fila.info = _InfoFalsa(True)
    lote.encuadrar(fila)
    return fila


class _InfoFalsa:
    def __init__(self, es_video):
        self.es_video = es_video
        self.duracion = 1.0
        self.frames_destino = 10


def test_una_fila_hereda_del_perfil_hasta_que_decide():
    lote = Lote(Opciones(preset="estandar"))
    fila = _fila_de_video(lote)
    assert fila.opciones.preset == "estandar"

    lote.poner_en_perfil("preset", "compresion", "video")
    assert fila.opciones.preset == "compresion", "sigue al lote"

    fila.poner("preset", "alta")
    lote.poner_en_perfil("preset", "estandar", "video")
    assert fila.opciones.preset == "alta", "ya decide por su cuenta"

    fila.soltar("preset", lote.perfil_de(fila))
    assert fila.opciones.preset == "estandar"
    assert not fila.propias


def test_el_video_y_la_musica_tienen_valores_por_su_cuenta():
    lote = Lote()
    video = _fila_de_video(lote, "a.mp4")
    musica = lote.anadir("b.mp3")
    musica.info = _InfoFalsa(False)
    lote.encuadrar(musica)

    lote.poner_en_perfil("volumen", 3, "musica")
    assert musica.opciones.volumen == 3
    assert video.opciones.volumen == 0, "lo de la musica no toca al video"

    lote.poner_en_perfil("preset", "compresion", "video")
    assert video.opciones.preset == "compresion"
    assert musica.opciones.preset == "alta"


def test_una_sobrescritura_no_arrastra_a_las_demas():
    lote = Lote()
    fila = _fila_de_video(lote)
    fila.poner("brillo", 40)
    lote.poner_en_perfil("volumen", 3, "video")
    assert fila.opciones.brillo == 40
    assert fila.opciones.volumen == 3, "lo no tocado sigue al lote"


def test_no_se_anade_dos_veces_el_mismo_fichero():
    lote = Lote()
    assert lote.anadir("a.mp4") is not None
    assert lote.anadir("a.mp4") is None
    assert len(lote.filas) == 1


def test_la_etiqueta_avisa_de_los_ajustes_propios():
    fila = Fila("a.mp4", Opciones())
    assert fila.etiqueta() == ""
    fila.poner("brillo", 10)
    assert "1 ajuste propio" in fila.etiqueta()
    fila.poner("volumen", 1)
    assert "2 ajustes propios" in fila.etiqueta()


# --- ventana ------------------------------------------------------------

def _anade(ventana, rutas) -> None:
    """Anade y espera al sondeo, que ahora va en su propio hilo."""
    ventana._anadir(rutas)
    if ventana.sondeador is not None:
        ventana.sondeador.wait(30000)
    QtWidgets.QApplication.instance().processEvents()


def _marca(ventana, n: int) -> None:
    """Selecciona la fila n-esima **de fichero**.

    La primera fila de la lista son los valores por defecto, asi que los
    indices de la lista y los del lote no coinciden.
    """
    fila = ventana.lote.filas[n]
    ventana.items[id(fila)].setSelected(True)

def test_sin_seleccion_se_edita_el_lote(ventana, fuentes):
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4"])
    ventana.lista.clearSelection()
    ventana._al_cambiar_campo("volumen", 2)
    assert ventana.lote.perfil_video.volumen == 2
    assert ventana.lote.filas[0].opciones.volumen == 2
    assert not ventana.lote.filas[0].propias


def test_con_seleccion_se_editan_solo_esos(ventana, fuentes, wav_prueba):
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4",
                     wav_prueba])
    assert len(ventana.lote.filas) == 2
    _marca(ventana, 0)
    ventana._al_cambiar_campo("preset", "compresion")

    assert ventana.lote.filas[0].opciones.preset == "compresion"
    assert ventana.lote.filas[1].opciones.preset == "alta"
    assert ventana.lote.filas[0].propias == {"preset"}

    ventana._al_soltar_campo("preset")
    assert ventana.lote.filas[0].opciones.preset == "alta"
    assert not ventana.lote.filas[0].propias


def test_el_panel_marca_lo_que_no_coincide(ventana, fuentes, wav_prueba):
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4",
                     wav_prueba])
    ventana.lote.filas[0].poner("brillo", 50)
    ventana.lista.selectAll()
    ventana._refrescar_panel()
    assert "(varios)" in ventana.panel.campos["brillo"].etiqueta.text()
    assert "(varios)" not in ventana.panel.campos["volumen"].etiqueta.text()


def test_un_fichero_ilegible_se_marca_y_no_tumba_la_lista(ventana, tmp_path):
    malo = tmp_path / "roto.mp4"
    malo.write_bytes(b"esto no es un mp4")
    _anade(ventana, [malo])
    assert ventana.lote.filas[0].estado == FALLIDO
    assert ventana.lote.filas[0].detalle


def test_el_lote_va_y_vuelve_por_la_ventana(ventana, fuentes, tmp_path):
    from gbamedia.jobs import batch
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4"])
    ventana.lote.perfil_video = Opciones(preset="estandar")
    ventana.lote.filas[0].seguir(ventana.lote.perfil_video)
    ventana.lote.filas[0].poner("brillo", 25)

    ruta = tmp_path / "lote.json"
    batch.guardar(ruta, ventana.lote.perfil_video, ventana.destinos,
                  [f.a_trabajo() for f in ventana.lote.filas])
    _, _, trabajos = batch.cargar(ruta)
    assert trabajos[0].opciones.brillo == 25
    assert trabajos[0].opciones.preset == "estandar"


def test_la_fila_dice_por_donde_va():
    from gbamedia.gui.model import CONVIRTIENDO
    fila = Fila("a.mp4", Opciones())
    fila.info = _InfoFalsa(True)
    fila.estado = CONVIRTIENDO
    fila.hechos, fila.total = 50, 200
    assert "50/200 frames" in fila.etiqueta()
    assert "25 %" in fila.etiqueta()
    assert fila.parte == 0.25


def test_el_panel_solo_ensena_lo_que_le_toca_a_cada_clase(ventana):
    """El color de las barras no pinta nada en un mp3, y ensenarlo junto a los
    valores por defecto de la musica es lo que confundia."""
    from gbamedia.gui.panel import MUSICA, VIDEO
    panel = ventana.panel
    panel.mostrar([], ventana.lote.perfil_video, VIDEO)
    assert not panel.grupos["Imagen"].isHidden()
    assert not panel.grupos["Audio"].isHidden()

    panel.mostrar([], ventana.lote.perfil_musica, MUSICA)
    assert panel.grupos["Imagen"].isHidden()
    assert panel.grupos["Calidad"].isHidden()
    assert not panel.grupos["Audio"].isHidden()
    assert not panel.grupos["Recorte y salida"].isHidden()


def test_la_lista_se_repinta_fila_a_fila(ventana, fuentes):
    """El progreso no puede rehacer la lista entera: se perderia la seleccion
    y con veinte ficheros la ventana se atasca."""
    from gbamedia.gui.model import CONVIRTIENDO
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4"])
    elemento = ventana.items[id(ventana.lote.filas[0])]
    fila = ventana.lote.filas[0]
    fila.estado, fila.hechos, fila.total = CONVIRTIENDO, 10, 100
    ventana._actualizar_item(fila)
    assert ventana.items[id(fila)] is elemento, "el mismo item, no otro"
    assert "10/100 frames" in elemento.text()


# --- convertir uno, rehacer, cerrar -------------------------------------

def test_convertir_seleccion_no_toca_a_los_demas(ventana, fuentes, monkeypatch,
                                                 tmp_path):
    """Convertir la seleccion es lo que pedia el usuario: uno suelto, sin
    tener que quitar los otros de la lista."""
    from gbamedia.gui import window as modulo
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4",
                     fuentes / "furret walk (full version)_360p.mp4"])
    ventana.destinos = Destinos(tmp_path / "v", tmp_path)

    encargados = []
    def espia(filas, destinos, trabajadores):
        encargados.append(filas)
        return _HiloFalso()

    monkeypatch.setattr(modulo, "Conversor", espia)
    _marca(ventana, 1)
    ventana._convertir_seleccion()

    assert [f.origen.name for f in encargados[0]] == [
        "furret walk (full version)_360p.mp4"]


class _SenalFalsa:
    def connect(self, *a):
        pass


class _HiloFalso:
    """Un Conversor que no convierte.

    Lo que se prueba aqui es **que se le encarga**, y con que nombres; que
    convierta bien es cosa de test_jobs.
    """

    def __init__(self, *a, corriendo=False, **k):
        self.avance = self.terminado = self.empieza = _SenalFalsa()
        self.finished = _SenalFalsa()
        self.cancelar = threading.Event()
        self.corriendo = corriendo

    def isRunning(self):
        return self.corriendo

    def parar(self):
        self.corriendo = False

    def wait(self, ms=0):
        return True

    def start(self):
        pass


def test_rehacer_reutiliza_el_nombre(ventana, fuentes, monkeypatch, tmp_path):
    """Volver a convertir tiene que **reemplazar** su salida, no dejar otra al
    lado con el nombre libre siguiente."""
    from gbamedia.gui import window as modulo
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4"])
    ventana.destinos = Destinos(tmp_path / "v", tmp_path)
    fila = ventana.lote.filas[0]

    monkeypatch.setattr(modulo, "Conversor", _HiloFalso)
    ventana._convertir([fila])
    primero = fila.nombre
    assert primero == "audiovid"

    fila.estado = HECHO
    ventana._convertir([fila])
    assert fila.nombre == primero, "el segundo pase pisa el fichero del primero"


def test_cerrar_solo_pregunta_si_esta_convirtiendo(ventana, fuentes,
                                                   monkeypatch):
    """Tener ficheros en la lista sin convertir es el estado normal de la
    aplicacion; preguntar por eso al salir es un incordio."""
    from PySide6 import QtGui
    preguntas = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **k: preguntas.append(a[2])
                     or QtWidgets.QMessageBox.StandardButton.Cancel))
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4"])

    evento = QtGui.QCloseEvent()
    evento.accept()
    ventana.closeEvent(evento)
    assert not preguntas, "con la lista cargada y quieta, se sale sin mas"
    assert evento.isAccepted()

    ventana.hilo = _HiloFalso(corriendo=True)
    ventana.pendientes = ventana.lote.filas
    evento = QtGui.QCloseEvent()
    ventana.closeEvent(evento)
    assert preguntas and "en marcha" in preguntas[0]
    assert not evento.isAccepted(), "cancelar deja la ventana abierta"
    ventana.hilo = None


def test_aplicar_el_arreglo_de_un_aviso(ventana, fuentes):
    """El boton del aviso escribe el ajuste en la fila; el usuario no copia
    ningun factor a mano."""
    from gbamedia.media.cadence import aviso_ciclo
    _anade(ventana, [fuentes / "furret walk (full version)_360p.mp4"])
    _marca(ventana, 0)
    aviso = aviso_ciclo(140 / 60.0)

    ventana._aplicar_arreglo(aviso.arreglo)
    fila = ventana.lote.filas[0]
    assert fila.opciones.tempo == aviso.arreglo["tempo"]
    assert "tempo" in fila.propias


def test_la_fila_de_defectos_no_es_un_fichero(ventana, fuentes):
    """Esta siempre, muestra los valores del lote y no cuenta para nada."""
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4"])
    assert ventana.lista.count() == 2, "los defectos mas el fichero"

    ventana.lista.item(0).setSelected(True)
    assert ventana._seleccionadas() == [], "no es una fila de fichero"

    ventana._quitar()
    assert len(ventana.lote.filas) == 1, "quitar no se lleva los defectos"
    ventana._convertir(ventana._seleccionadas())
    assert ventana.hilo is None, "no hay nada que convertir"


def test_sin_debug_no_hay_cadencia_a_la_vista(ventana, fuentes, monkeypatch):
    """El aviso de cadencia llego a proponer acelerar un 700 %: por defecto no
    se ensena ni el aviso ni sus controles."""
    from gbamedia.gui import panel as modulo_panel
    from gbamedia.media.cadence import aviso_ciclo
    _anade(ventana, [fuentes / "furret walk (full version)_360p.mp4"])
    fila = ventana.lote.filas[0]
    fila.avisos = [aviso_ciclo(140 / 60.0)]

    monkeypatch.setattr(modulo_panel, "modo_depuracion", lambda: False)
    _marca(ventana, 0)
    assert ventana.panel.grupos["Cadencia"].isHidden()
    assert ventana.panel.grupos["Velocidad"].isHidden()
    assert ventana.panel.avisos.count() == 0

    monkeypatch.setattr(modulo_panel, "modo_depuracion", lambda: True)
    ventana._refrescar_panel()
    assert not ventana.panel.grupos["Cadencia"].isHidden()
    assert ventana.panel.avisos.count() == 1, "con DEBUG_ON si sale"


def test_el_dialogo_de_destino_da_una_o_dos_carpetas(app, tmp_path):
    from gbamedia.gui.dialogs import SUBCARPETA, DialogoDestino
    dialogo = DialogoDestino()
    dialogo.campos["una"].setText(str(tmp_path))
    destinos = dialogo.destinos()
    assert destinos.musica == tmp_path
    assert destinos.video == tmp_path / SUBCARPETA

    dialogo.separar.setChecked(True)
    dialogo.campos["video"].setText(str(tmp_path / "v"))
    dialogo.campos["musica"].setText(str(tmp_path / "m"))
    destinos = dialogo.destinos()
    assert (destinos.video, destinos.musica) == (tmp_path / "v",
                                                 tmp_path / "m")

    dialogo.campos["musica"].setText("  ")
    assert dialogo.destinos() is None, "sin ruta no hay destino"


def test_los_dialogos_de_fichero_no_revientan(ventana, monkeypatch, tmp_path):
    """Cubre las cuatro rutas que abren un dialogo.

    Sin esto no las tocaba nadie, y ahi se escondia un `ruta, _ = ...` que
    dejaba `_` -la funcion de traduccion- como variable local y rompia la
    llamada de la misma linea.
    """
    perfil = tmp_path / "p.json"
    lote = tmp_path / "l.json"

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(perfil), "")))
    ventana._guardar_perfil()
    assert perfil.is_file()

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(perfil), "")))
    ventana._cargar_perfil()

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(lote), "")))
    ventana._guardar_lote()
    assert "perfil_video" in lote.read_text(encoding="utf-8")

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(lote), "")))
    ventana._abrir_lote()      # el lote esta vacio: avisa y no revienta


def test_cambiar_de_idioma_rehace_la_ventana(ventana, fuentes, monkeypatch):
    """Se lleva el lote y los destinos; retraducir widget a widget deja
    siempre alguno a medias."""
    from PySide6 import QtCore

    from gbamedia import i18n
    from gbamedia.gui import window as modulo

    monkeypatch.setattr(QtCore.QSettings, "setValue",
                        lambda *a, **k: None)
    _anade(ventana, [fuentes / "Audio Video Sync Test_360p.mp4"])
    lote = ventana.lote
    anterior = i18n.idioma()
    try:
        ventana._cambiar_idioma("en")
        nueva = modulo.VIVAS[-1]
        assert nueva.lote is lote, "se lleva los ficheros"
        assert nueva.boton_convertir.text() == "Convert all"
        assert ventana.mudando, "la vieja se cierra sin preguntar"
    finally:
        for v in modulo.VIVAS:
            v.mudando = True
            v.close()
        modulo.VIVAS.clear()
        i18n.usar(anterior)


def test_anadir_no_bloquea_la_ventana(ventana, fuentes):
    """Sondear cuesta un proceso por fichero; en Windows eso dejaba la ventana
    tiesa varios segundos. Las filas tienen que aparecer ya, y rellenarse
    despues."""
    ventana._anadir([fuentes / "Audio Video Sync Test_360p.mp4",
                     fuentes / "furret walk (full version)_360p.mp4"])
    assert len(ventana.lote.filas) == 2, "las filas estan antes del sondeo"
    assert all(f.info is None for f in ventana.lote.filas)
    assert "leyendo" in ventana.lote.filas[0].etiqueta()

    ventana.sondeador.wait(30000)
    QtWidgets.QApplication.instance().processEvents()
    assert all(f.info is not None for f in ventana.lote.filas)
    assert ventana.lote.filas[0].es_video
