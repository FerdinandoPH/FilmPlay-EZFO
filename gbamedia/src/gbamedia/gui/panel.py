"""Panel de parametros: del fichero seleccionado, o del lote si no hay ninguno.

Se aplica **al cambiar el control**, no con un boton de aceptar: asi editar
varias filas a la vez no necesita que los campos que no se tocan aparezcan en
blanco, porque un campo que no se toca no se aplica a nadie. Cuando la
seleccion no coincide en un campo, la etiqueta lo dice con "(varios)".

Sin seleccion, el panel edita los **valores por defecto del lote**, que son dos
y no uno: los del video y los de la musica. La pestana de arriba dice cual se
esta tocando, y de cada uno se ensenan solo los grupos que le importan, que un
mp3 no tiene color de barras.
"""
from PySide6 import QtCore, QtWidgets

from ..settings import modo_depuracion
from ..core.gbs_decode import MODOS
from ..i18n import _
from ..jobs.options import PRESETS
from ..media import fit

def VOLUMENES():
    return [(_("Normal (x1)"), 0), (_("El doble (x2)"), 1),
            (_("Cuatro veces (x4)"), 2), (_("Ocho veces (x8)"), 3)]


def CANALES():
    return [(_("Izquierdo"), 0), (_("Derecho"), 1)]


def AJUSTES():
    return [(_("Barras (no deforma)"), fit.BARRAS),
            (_("Recorte (llena la pantalla)"), fit.RECORTE),
            (_("Estirado (deforma)"), fit.ESTIRADO)]


def BUSQUEDA():
    return [(_("Rápida"), "rapida"), (_("Exhaustiva (más lenta)"),
                                      "exhaustiva")]

VIDEO, MUSICA = "video", "musica"

# Que grupos tienen sentido para cada clase de fichero
GRUPOS = {
    "Imagen": (VIDEO,),
    "Calidad": (VIDEO,),
    "Audio": (VIDEO, MUSICA),
    "Cadencia": (VIDEO,),
    "Velocidad": (VIDEO, MUSICA),
    "Recorte y salida": (VIDEO, MUSICA),
}

# Lo que solo sale con DEBUG_ON al lado del ejecutable: la cadencia se mide
# mal en material real y sus controles no le dicen nada a quien solo quiere
# pasar un video a la consola.
SOLO_DEPURACION = {"Cadencia", "Velocidad"}


class CajaAviso(QtWidgets.QFrame):
    """Un aviso de cadencia con su arreglo a un clic.

    El aviso trae los campos que lo corrigen (`Aviso.arreglo`), asi que aqui no
    hay que saber nada de cadencia: se ensena y se aplica.
    """

    aplicar = QtCore.Signal(dict)

    def __init__(self, aviso):
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        vertical = QtWidgets.QVBoxLayout(self)

        titulo = _que_crezca(QtWidgets.QLabel(f"⚠  {aviso.titulo}"))
        fuente = titulo.font()
        fuente.setBold(True)
        titulo.setFont(fuente)
        vertical.addWidget(titulo)

        vertical.addWidget(_que_crezca(QtWidgets.QLabel(aviso.mensaje)))

        if aviso.sugerencia:
            abajo = QtWidgets.QHBoxLayout()
            abajo.addWidget(_que_crezca(QtWidgets.QLabel(aviso.sugerencia)), 1)
            if aviso.arreglo:
                boton = QtWidgets.QPushButton(_("Aplicar"))
                boton.setToolTip(", ".join(f"{k} = {v}"
                                           for k, v in aviso.arreglo.items()))
                boton.clicked.connect(
                    lambda marcado=False, a=dict(aviso.arreglo):
                    self.aplicar.emit(a))
                abajo.addWidget(boton)
            vertical.addLayout(abajo)


class Campo(QtCore.QObject):
    """Un control atado a un campo de Opciones."""

    cambiado = QtCore.Signal(str, object)

    def __init__(self, nombre, titulo, control, leer, escribir, senal):
        super().__init__()
        self.nombre = nombre
        self.titulo = titulo
        self.control = control
        self._leer = leer
        self._escribir = escribir
        self.etiqueta = QtWidgets.QLabel(titulo)
        self.volver = QtWidgets.QToolButton()
        self.volver.setText("↺")
        self.volver.setToolTip(_("volver al valor del lote"))
        self.volver.setAutoRaise(True)
        senal.connect(self._al_cambiar)

    def _al_cambiar(self, *_):
        if self.control.signalsBlocked():
            return
        self.cambiado.emit(self.nombre, self._leer())

    def mostrar(self, valores: list, propio: bool) -> None:
        iguales = len(set(map(_clave, valores))) <= 1
        self.control.blockSignals(True)
        if valores:
            self._escribir(valores[0])
        self.control.blockSignals(False)
        sufijo = "" if iguales else "  " + _("(varios)")
        self.etiqueta.setText(self.titulo + sufijo)
        fuente = self.etiqueta.font()
        fuente.setBold(propio)
        self.etiqueta.setFont(fuente)
        self.volver.setEnabled(propio)


def _que_crezca(etiqueta: QtWidgets.QLabel) -> QtWidgets.QLabel:
    """Deja que una etiqueta con salto de linea pida el alto que necesita.

    Sin esto, dentro de un area de scroll el texto se corta a la altura de una
    linea y media y el aviso se queda a medio leer.
    """
    etiqueta.setWordWrap(True)
    politica = etiqueta.sizePolicy()
    politica.setHeightForWidth(True)
    politica.setVerticalPolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding)
    etiqueta.setSizePolicy(politica)
    return etiqueta


def _clave(v):
    return tuple(v) if isinstance(v, (list, tuple)) else v


def _combo(opciones):
    c = QtWidgets.QComboBox()
    for texto, valor in opciones:
        c.addItem(texto, valor)
    return c


class PanelOpciones(QtWidgets.QScrollArea):
    cambiado = QtCore.Signal(str, object)
    soltado = QtCore.Signal(str)
    pestana = QtCore.Signal(str)
    arreglar = QtCore.Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        cuerpo = QtWidgets.QWidget()
        self.setWidget(cuerpo)
        self.disposicion = QtWidgets.QVBoxLayout(cuerpo)
        # Que el contenido no se aplaste cuando no cabe: lo que tiene que
        # aparecer entonces es la barra de scroll.
        self.disposicion.setSizeConstraint(
            QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
        self.campos: dict[str, Campo] = {}
        self.grupos: dict[str, QtWidgets.QGroupBox] = {}

        self.solapas = QtWidgets.QTabBar()
        self.solapas.addTab(_("Vídeo"))
        self.solapas.addTab(_("Música"))
        self.solapas.setToolTip(
            _("Cada clase de fichero tiene sus propios valores por defecto"))
        self.solapas.currentChanged.connect(
            lambda n: self.pestana.emit(VIDEO if n == 0 else MUSICA))
        self.disposicion.addWidget(self.solapas)

        self.titulo = QtWidgets.QLabel()
        self.titulo.setWordWrap(True)
        self.disposicion.addWidget(self.titulo)

        self.avisos = QtWidgets.QVBoxLayout()
        self.avisos.setContentsMargins(0, 0, 0, 0)
        self.disposicion.addLayout(self.avisos)

        self._grupo("Imagen", [
            self._campo_combo("ajuste", _("Ajuste"), AJUSTES()),
            self._campo_texto("color_barras", _("Color de las barras")),
            self._campo_entero("brillo", _("Brillo"), -100, 100),
            self._campo_entero("contraste", _("Contraste"), 0, 200),
            self._campo_entero("realce", _("Realce"), 0, 100),
        ])
        self._grupo("Calidad", [
            self._campo_combo("preset", _("Preset"),
                              [(_(p.capitalize()), p) for p in PRESETS]),
            self._campo_entero("frame_size", _("Bytes por frame"), 0, 0x8000,
                               cero_es_nada=True),
            self._campo_check("sin_vectores",
                              _("Sin compensación de movimiento")),
            self._campo_combo("busqueda", _("Búsqueda de vectores"),
                              BUSQUEDA()),
        ])
        self._grupo("Audio", [
            self._campo_combo(
                "modo_audio", _("Modo"),
                [(_("El del preset"), None)]
                + [(m.etiqueta, n) for n, m in sorted(MODOS.items())]),
            self._campo_combo("canal", _("Canal (solo mono)"), CANALES()),
            self._campo_combo("volumen", _("Volumen"), VOLUMENES()),
        ])
        self._grupo("Cadencia", [
            self._campo_check("mezclar_frames",
                              _("Mezclar frames en vez de descartarlos")),
        ])
        self._grupo("Velocidad", [
            self._campo_real("tempo", _("Factor de tempo"), 0.25, 4.0),
        ])
        self._grupo("Recorte y salida", [
            self._campo_real("desde", _("Empezar en (s)"), 0.0, 100000.0,
                             cero_es_nada=True),
            self._campo_real("duracion", _("Duración (s)"), 0.0, 100000.0,
                             cero_es_nada=True),
            self._campo_texto("nombre", _("Nombre de salida"),
                              _("automático")),
        ])
        self.disposicion.addStretch(1)

    # --- construccion

    def _registrar(self, campo):
        campo.cambiado.connect(self.cambiado)
        campo.volver.clicked.connect(
            lambda marcado=False, n=campo.nombre: self.soltado.emit(n))
        self.campos[campo.nombre] = campo
        return campo

    def _grupo(self, titulo, campos):
        # El titulo se traduce al pintarlo; la clave del diccionario se queda
        # en espanol porque es con la que se decide que grupo se ensena.
        caja = QtWidgets.QGroupBox(_(titulo))
        rejilla = QtWidgets.QGridLayout(caja)
        for n, campo in enumerate(campos):
            rejilla.addWidget(campo.etiqueta, n, 0)
            rejilla.addWidget(campo.control, n, 1)
            rejilla.addWidget(campo.volver, n, 2)
        rejilla.setColumnStretch(1, 1)
        self.disposicion.addWidget(caja)
        self.grupos[titulo] = caja

    def _campo_combo(self, nombre, titulo, opciones):
        c = _combo(opciones)
        return self._registrar(Campo(
            nombre, titulo, c, c.currentData,
            lambda v, c=c: c.setCurrentIndex(max(0, c.findData(v))),
            c.currentIndexChanged))

    def _campo_entero(self, nombre, titulo, lo, hi, cero_es_nada=False):
        c = QtWidgets.QSpinBox()
        c.setRange(lo, hi)
        if cero_es_nada:
            c.setSpecialValueText(_("el del preset"))
        return self._registrar(Campo(
            nombre, titulo, c,
            (lambda c=c: (c.value() or None)) if cero_es_nada else c.value,
            lambda v, c=c: c.setValue(v or 0), c.valueChanged))

    def _campo_real(self, nombre, titulo, lo, hi, cero_es_nada=False):
        c = QtWidgets.QDoubleSpinBox()
        c.setRange(lo, hi)
        c.setDecimals(6)
        c.setSingleStep(0.01)
        if cero_es_nada:
            c.setSpecialValueText(_("todo"))
        return self._registrar(Campo(
            nombre, titulo, c,
            (lambda c=c: (c.value() or None)) if cero_es_nada else c.value,
            lambda v, c=c: c.setValue(v or 0.0), c.valueChanged))

    def _campo_texto(self, nombre, titulo, marcador=""):
        c = QtWidgets.QLineEdit()
        c.setPlaceholderText(marcador)
        return self._registrar(Campo(
            nombre, titulo, c, lambda c=c: c.text() or None,
            lambda v, c=c: c.setText(v or ""), c.editingFinished))

    def _campo_check(self, nombre, titulo):
        c = QtWidgets.QCheckBox()
        return self._registrar(Campo(
            nombre, titulo, c, c.isChecked,
            lambda v, c=c: c.setChecked(bool(v)), c.toggled))

    # --- estado

    @property
    def clase(self) -> str:
        """Que valores por defecto se estan editando: los de video o los de musica."""
        return VIDEO if self.solapas.currentIndex() == 0 else MUSICA

    def _poner_avisos(self, avisos) -> None:
        if not modo_depuracion():
            avisos = []
        while self.avisos.count():
            viejo = self.avisos.takeAt(0).widget()
            if viejo is not None:
                # Quitarlo del layout no lo quita de la vista: sin soltarlo del
                # padre se queda pintado encima del panel siguiente hasta que
                # el bucle de eventos atiende al deleteLater.
                viejo.setParent(None)
                viejo.deleteLater()
        for aviso in avisos:
            caja = CajaAviso(aviso)
            caja.aplicar.connect(self.arreglar)
            self.avisos.addWidget(caja)

    def _solo_para(self, clases: set) -> None:
        depurando = modo_depuracion()
        for titulo, caja in self.grupos.items():
            vale = bool(clases & set(GRUPOS[titulo]))
            if titulo in SOLO_DEPURACION and not depurando:
                vale = False
            caja.setVisible(vale)

    def mostrar(self, filas, perfil, clase: str = VIDEO) -> None:
        """`filas` seleccionadas (o ninguna, y entonces manda `perfil`)."""
        self.solapas.setVisible(not filas)
        if not filas:
            que = _("los vídeos") if clase == VIDEO else _("la música")
            self.titulo.setText(
                "<b>" + _("Valores por defecto para {que}", que=que)
                + "</b><br>"
                + _("Se aplican a todo el que no haya decidido otra cosa. "
                    "Selecciona ficheros para darles ajustes propios."))
            self._poner_avisos([])
            self._solo_para({clase})
            for nombre, campo in self.campos.items():
                campo.mostrar([getattr(perfil, nombre)], False)
            return

        clases = {VIDEO if f.es_video else MUSICA for f in filas}
        self._solo_para(clases)
        if len(filas) == 1:
            fila = filas[0]
            clase = _("vídeo") if fila.es_video else _("música")
            self.titulo.setText(f"<b>{fila.origen.name}</b><br>{clase}")
            self._poner_avisos(fila.avisos)
        else:
            self.titulo.setText(
                "<b>" + _("{n} ficheros seleccionados", n=len(filas))
                + "</b><br>" + _("Lo que cambies se aplica a todos."))
            self._poner_avisos([])

        for nombre, campo in self.campos.items():
            campo.mostrar([getattr(f.opciones, nombre) for f in filas],
                          any(nombre in f.propias for f in filas))
