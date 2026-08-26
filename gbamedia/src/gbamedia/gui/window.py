"""Ventana principal: lista de ficheros a la izquierda, parametros a la derecha.

La ventana no convierte nada: prepara `Trabajo` y se los da al mismo motor que
usa la linea de ordenes.

Nota sobre los hilos: la conversion vive en un `QThread` que reparte cada video
entre varios procesos (ver jobs/parallel.py). El hilo es lo unico que deja
informar del progreso mientras tanto, y los procesos son los que hacen que un
video de cinco minutos no tarde media hora. Cada fichero se convierte dentro de
un try/except: un fallo marca su fila y el lote sigue.
"""
import multiprocessing
import sys
import threading
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..jobs import batch
from ..jobs.convert import (analizar, asignar_nombres, colisiones,
                              convertir)
from ..jobs.options import Perfiles, cargar_perfil, guardar_perfil
# `_` es la funcion de traduccion: nunca usarlo como variable de descarte, o
# se convierte en local y revienta el resto de la funcion.
from .. import i18n
from ..i18n import _
from ..jobs.parallel import Cancelado, trabajadores_por_defecto
from ..media.ffmpeg import disponible
from ..media.probe import EXTENSIONES, sondear
from .dialogs import pedir_destino
from .model import (CAMPOS, CONVIRTIENDO, FALLIDO, HECHO, MARCAS, PENDIENTE,
                     Fila, Lote)
from .panel import VIDEO, PanelOpciones

# Solo los fallos llevan color: si todo lo lleva, no destaca nada. Lo demas
# se distingue por la marca y por la negrita del que esta en curso.
COLORES = {FALLIDO: "#c0392b"}

# Las ventanas que siguen vivas tras cambiar de idioma: sin esta lista, la
# nueva se la lleva el recolector en cuanto la vieja suelta la referencia.
VIVAS: list = []

# Primera fila fija de la lista. Los valores por defecto se editaban
# deseleccionando todo, que no se le ocurre a nadie; asi estan a la vista.
def fila_de_defectos() -> str:
    return _("⚙  Valores por defecto\n    vídeo y música")
REFRESCO = 0.1          # segundos entre repintados de la lista


class Conversor(QtCore.QThread):
    avance = QtCore.Signal(int, int, int)         # fila, hechos, total
    terminado = QtCore.Signal(int, object, str)   # fila, resultado, error
    empieza = QtCore.Signal(int)                  # fila

    def __init__(self, filas, destinos, trabajadores=0):
        super().__init__()
        self.filas = filas
        self.destinos = destinos
        self.trabajadores = trabajadores
        self.cancelar = threading.Event()

    def parar(self) -> None:
        self.cancelar.set()

    def run(self):
        for n, fila in enumerate(self.filas):
            if self.cancelar.is_set():
                return
            self.empieza.emit(n)
            try:
                resultado = convertir(
                    fila.a_trabajo(), self.destinos,
                    lambda hechos, total, n=n: self.avance.emit(
                        n, hechos, total or 0),
                    trabajadores=self.trabajadores, cancelar=self.cancelar)
            except Cancelado:
                return
            except Exception as e:
                self.terminado.emit(n, None, str(e))
            else:
                self.terminado.emit(n, resultado, "")


class Sondeador(QtCore.QThread):
    """Pregunta a ffprobe por cada fichero, fuera del hilo de la ventana.

    Sondear cuesta un proceso por fichero: en Linux son milisegundos, pero en
    Windows arrancar un proceso es mucho mas caro y anadir un punado de
    ficheros dejaba la ventana sin responder varios segundos.
    """

    sondeado = QtCore.Signal(int, object, str)      # fila, info, error
    terminado = QtCore.Signal()

    def __init__(self, filas):
        super().__init__()
        self.filas = filas
        self.parar = False

    def run(self):
        for n, fila in enumerate(self.filas):
            if self.parar:
                return
            try:
                self.sondeado.emit(n, sondear(fila.origen), "")
            except Exception as e:
                self.sondeado.emit(n, None, str(e))
        self.terminado.emit()


class Ventana(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("gbamedia")
        self.resize(1040, 680)
        self.lote = Lote()
        # Sin destino por defecto: uno relativo al directorio desde el que
        # arranca el proceso acaba en cualquier sitio y no hay quien encuentre
        # lo convertido. Se pregunta la primera vez que hace falta.
        self.destinos = None
        self.hilo = None
        self.sondeador = None
        self.mudando = False        # cambiando de idioma, no preguntes al salir
        self.pendientes: list[Fila] = []
        self.items: dict[int, QtWidgets.QListWidgetItem] = {}
        self._pintado = 0.0
        self._arranque = 0.0

        partido = QtWidgets.QSplitter()
        self.setCentralWidget(partido)

        partido.addWidget(self._lado_izquierdo())
        self.panel = PanelOpciones()
        self.panel.cambiado.connect(self._al_cambiar_campo)
        self.panel.soltado.connect(self._al_soltar_campo)
        self.panel.pestana.connect(self._al_cambiar_pestana)
        self.panel.arreglar.connect(self._aplicar_arreglo)
        partido.addWidget(self.panel)
        partido.setSizes([380, 660])

        self._barra_inferior()
        self._menus()
        self.setAcceptDrops(True)
        self._refrescar()

        if not disponible():
            QtWidgets.QMessageBox.warning(
                self, _("Falta ffmpeg"),
                _("No se encuentra ffmpeg/ffprobe. Ponlos en bin/ junto al "
                  "ejecutable o apunta GBAMEDIA_FFMPEG a su carpeta."))

    # --- construccion

    def _lado_izquierdo(self):
        caja = QtWidgets.QWidget()
        vertical = QtWidgets.QVBoxLayout(caja)
        vertical.setContentsMargins(0, 0, 0, 0)

        self.resumen = QtWidgets.QLabel()
        self.resumen.setWordWrap(True)
        vertical.addWidget(self.resumen)

        self.lista = QtWidgets.QListWidget()
        self.lista.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lista.itemSelectionChanged.connect(self._al_cambiar_seleccion)
        self.lista.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_de_fila)
        vertical.addWidget(self.lista, 1)

        botones = QtWidgets.QHBoxLayout()
        for texto, ranura in ((_("Añadir..."), self._pedir_ficheros),
                              (_("Añadir carpeta..."), self._pedir_carpeta),
                              (_("Quitar"), self._quitar)):
            b = QtWidgets.QPushButton(texto)
            b.clicked.connect(ranura)
            botones.addWidget(b)
        vertical.addLayout(botones)

        self.pista = QtWidgets.QLabel(_("Arrastra aquí ficheros o carpetas."))
        self.pista.setWordWrap(True)
        vertical.addWidget(self.pista)
        return caja

    def _barra_inferior(self):
        """Destinos a la izquierda, marcha en medio, el boton grande a la
        derecha. Las dos barras van juntas y debajo de lo que las explica."""
        barra = QtWidgets.QWidget()
        rejilla = QtWidgets.QGridLayout(barra)
        rejilla.setHorizontalSpacing(16)

        self.etiqueta_destino = QtWidgets.QLabel()
        rejilla.addWidget(self.etiqueta_destino, 0, 0)

        carpetas = QtWidgets.QHBoxLayout()
        carpetas.setSpacing(4)
        for texto, ranura in ((_("Elegir carpeta..."), self._elegir_destino),
                              (_("Abrir carpeta"), self._abrir_carpeta)):
            b = QtWidgets.QPushButton(texto)
            b.clicked.connect(ranura)
            carpetas.addWidget(b)
        carpetas.addStretch(1)
        rejilla.addLayout(carpetas, 1, 0)

        self.marcha = QtWidgets.QLabel()
        self.marcha.setMinimumWidth(260)
        rejilla.addWidget(self.marcha, 0, 1, 1, 2)
        rejilla.setColumnStretch(0, 1)
        rejilla.setColumnStretch(1, 1)
        rejilla.setColumnStretch(2, 1)

        # La de la izquierda es el fichero en curso; la de la derecha, el lote
        self.progreso = QtWidgets.QProgressBar()
        self.progreso.setFormat("%v/%m frames")
        rejilla.addWidget(self.progreso, 1, 1)

        self.progreso_lote = QtWidgets.QProgressBar()
        self.progreso_lote.setRange(0, 1000)
        self.progreso_lote.setFormat(_("lote") + ": %p %")
        rejilla.addWidget(self.progreso_lote, 1, 2)

        self.boton_convertir = QtWidgets.QPushButton(_("Convertir todo"))
        self.boton_convertir.setMinimumSize(140, 52)
        self.boton_convertir.clicked.connect(self._convertir_todo)
        rejilla.addWidget(self.boton_convertir, 0, 3, 2, 1)

        self.boton_seleccion = QtWidgets.QPushButton(_("Convertir selección"))
        self.boton_seleccion.setMinimumSize(150, 52)
        self.boton_seleccion.clicked.connect(self._convertir_seleccion)
        rejilla.addWidget(self.boton_seleccion, 0, 4, 2, 1)

        contenedor = QtWidgets.QDockWidget()
        contenedor.setTitleBarWidget(QtWidgets.QWidget())
        contenedor.setWidget(barra)
        contenedor.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(
            QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, contenedor)

    def _menus(self):
        idiomas = self.menuBar().addMenu(_("Idioma"))
        grupo = QtGui.QActionGroup(self)
        for codigo in i18n.IDIOMAS:
            accion = QtGui.QAction(i18n.NOMBRES[codigo], self)
            accion.setCheckable(True)
            accion.setChecked(codigo == i18n.idioma())
            accion.triggered.connect(
                lambda marcado=False, c=codigo: self._cambiar_idioma(c))
            grupo.addAction(accion)
            idiomas.addAction(accion)

        archivo = self.menuBar().addMenu(_("&Lote"))
        for texto, ranura in ((_("Abrir lote..."), self._abrir_lote),
                              (_("Guardar lote..."), self._guardar_lote),
                              (None, None),
                              (_("Cargar valores por defecto..."),
                               self._cargar_perfil),
                              (_("Guardar valores por defecto..."),
                               self._guardar_perfil)):
            if texto is None:
                archivo.addSeparator()
                continue
            accion = QtGui.QAction(texto, self)
            accion.triggered.connect(ranura)
            archivo.addAction(accion)

    def _cambiar_idioma(self, codigo: str) -> None:
        """Rehace la ventana en el otro idioma.

        Retraducir cien widgets uno a uno es una fuente inagotable de textos
        que se quedan a medias; rehacerla llevandose el lote no falla nunca.
        """
        if codigo == i18n.idioma():
            return
        i18n.usar(codigo)
        QtCore.QSettings("gbamedia", "gbamedia").setValue("idioma", codigo)

        nueva = Ventana()
        nueva.lote = self.lote
        nueva.destinos = self.destinos
        nueva.resize(self.size())
        nueva.move(self.pos())
        nueva._refrescar()
        nueva.show()
        VIVAS.append(nueva)
        self.mudando = True
        self.close()

    # --- arrastrar y soltar

    def dragEnterEvent(self, evento):
        if evento.mimeData().hasUrls():
            evento.acceptProposedAction()

    def dropEvent(self, evento):
        rutas = [Path(u.toLocalFile()) for u in evento.mimeData().urls()]
        self._anadir(rutas)

    # --- lista

    def _pedir_ficheros(self):
        rutas, _filtro = QtWidgets.QFileDialog.getOpenFileNames(
            self, _("Añadir ficheros"))
        self._anadir([Path(r) for r in rutas])

    def _pedir_carpeta(self):
        ruta = QtWidgets.QFileDialog.getExistingDirectory(
            self, _("Añadir carpeta"))
        if ruta:
            self._anadir([Path(ruta)])

    def _anadir(self, rutas):
        candidatos = []
        for ruta in rutas:
            if ruta.is_dir():
                candidatos += sorted(f for f in ruta.rglob("*")
                                     if f.suffix.lower() in EXTENSIONES
                                     and f.is_file())
            elif ruta.is_file():
                candidatos.append(ruta)
        nuevas = [f for f in (self.lote.anadir(r) for r in candidatos)
                  if f is not None]
        for fila in nuevas:
            fila.detalle = _("leyendo...")
        self._refrescar()
        if not nuevas:
            return

        # El sondeo va aparte para que la ventana no se quede tiesa; las filas
        # aparecen ya en la lista y se van rellenando segun contesta ffprobe.
        self.sondeador = Sondeador(nuevas)
        self.sondeador.sondeado.connect(
            lambda n, info, error, filas=nuevas: self._al_sondear(
                filas[n], info, error))
        self.sondeador.terminado.connect(self._al_acabar_sondeo)
        self.sondeador.start()

    def _al_sondear(self, fila, info, error):
        if error:
            fila.estado = FALLIDO
            fila.detalle = error
        else:
            fila.info = info
            fila.detalle = ""
            # Hasta saber que clase de fichero es no se sabe que valores por
            # defecto le tocan.
            self.lote.encuadrar(fila)
        self._actualizar_item(fila)
        self._refrescar_resumen()

    def _al_acabar_sondeo(self):
        fallos = [f.origen.name for f in self.sondeador.filas
                  if f.info is None]
        self._refrescar(mantener_seleccion=True)
        if fallos:
            self.statusBar().showMessage(
                _("no se han podido leer: {cuales}",
                  cuales=", ".join(fallos[:5])), 8000)

    def _quitar(self):
        self.lote.quitar(self._seleccionadas())
        self._refrescar()

    def _seleccionadas(self) -> list[Fila]:
        """Las filas de fichero seleccionadas.

        La primera fila de la lista no es un fichero sino los valores por
        defecto, asi que no cuenta para convertir, quitar ni contar.
        """
        filas = [self.lista.item(i.row()).data(QtCore.Qt.ItemDataRole.UserRole)
                 for i in self.lista.selectedIndexes()]
        return [f for f in filas if f is not None]

    # --- panel

    def _al_cambiar_campo(self, nombre, valor):
        filas = self._seleccionadas()
        if not filas:
            self.lote.poner_en_perfil(nombre, valor, self.panel.clase)
        else:
            for fila in filas:
                fila.poner(nombre, valor)
        self._refrescar(mantener_seleccion=True)

    def _al_soltar_campo(self, nombre):
        for fila in self._seleccionadas():
            fila.soltar(nombre, self.lote.perfil_de(fila))
        self._refrescar(mantener_seleccion=True)

    def _al_cambiar_pestana(self, _clase):
        self._refrescar_panel()

    def _al_cambiar_seleccion(self):
        cuantas = len(self._seleccionadas())
        corriendo = bool(self.hilo and self.hilo.isRunning())
        self.boton_seleccion.setEnabled(bool(cuantas) and not corriendo)
        self.boton_seleccion.setText(
            _("Convertir selección ({cuantas})", cuantas=cuantas) if cuantas
            else _("Convertir selección"))
        self._refrescar_panel()

    def _menu_de_fila(self, punto):
        fila = self.lista.itemAt(punto)
        if fila is None or fila.data(QtCore.Qt.ItemDataRole.UserRole) is None:
            return
        if not fila.isSelected():
            self.lista.clearSelection()
            fila.setSelected(True)
        filas = self._seleccionadas()
        hechas = [f for f in filas if f.estado == HECHO]

        menu = QtWidgets.QMenu(self)
        acciones = [
            (_("Volver a convertir ({n})", n=len(filas)) if hechas
             else _("Convertir ({n})", n=len(filas)),
             lambda: self._convertir(filas)),
            (_("Analizar cadencia"), lambda: self._analizar(filas)),
            (None, None),
            (_("Abrir carpeta de salida"), self._abrir_carpeta),
            (_("Quitar de la lista"), self._quitar),
        ]
        for texto, ranura in acciones:
            if texto is None:
                menu.addSeparator()
                continue
            accion = menu.addAction(texto)
            accion.triggered.connect(ranura)
            if ranura is not self._quitar and self.hilo and self.hilo.isRunning():
                accion.setEnabled(False)
        menu.exec(self.lista.mapToGlobal(punto))

    def _analizar(self, filas):
        """Mide la cadencia sin convertir, para poder arreglarla antes.

        Cuesta lo que decodificar 30 s de video, unas decimas por fichero, asi
        que se hace aqui mismo en vez de montar otro hilo.
        """
        videos = [f for f in filas if f.es_video]
        if not videos:
            self.statusBar().showMessage(
                _("la cadencia solo aplica al video"), 5000)
            return
        QtWidgets.QApplication.setOverrideCursor(
            QtCore.Qt.CursorShape.WaitCursor)
        try:
            for fila in videos:
                try:
                    fila.avisos = analizar(fila.a_trabajo())
                except Exception as e:
                    self.statusBar().showMessage(
                        f"{fila.origen.name}: {e}", 8000)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        con_aviso = sum(1 for f in videos if f.avisos)
        self.statusBar().showMessage(
            _("analizados {n}: {avisan} con algo que arreglar",
              n=len(videos), avisan=con_aviso), 8000)
        self._refrescar(mantener_seleccion=True)

    def _aplicar_arreglo(self, arreglo: dict):
        filas = self._seleccionadas()
        for fila in filas:
            for campo, valor in arreglo.items():
                fila.poner(campo, valor)
        dicho = ", ".join(f"{k} = {v}" for k, v in arreglo.items())
        self.statusBar().showMessage(
            _("aplicado a {n}: {que}", n=len(filas), que=dicho), 8000)
        self._refrescar(mantener_seleccion=True)

    def _refrescar_panel(self):
        filas = self._seleccionadas()
        self.panel.mostrar(filas, self.lote.perfil(self.panel.clase),
                           self.panel.clase)

    # --- pintado de la lista

    def _texto(self, fila) -> str:
        clase = _("vídeo") if fila.es_video else _("música")
        texto = f"{MARCAS[fila.estado]} {fila.origen.name}\n    {clase}"
        if fila.info:
            texto += f"  ·  {fila.info.duracion:.1f} s"
        extra = fila.etiqueta()
        if extra:
            texto += f"\n    {extra}"
        return texto

    def _actualizar_item(self, fila) -> None:
        """Repinta una sola fila. Rehacer la lista entera en cada aviso de
        progreso era lo que atascaba la ventana y perdia el scroll."""
        elemento = self.items.get(id(fila))
        if elemento is None:
            return
        elemento.setText(self._texto(fila))
        color = COLORES.get(fila.estado)
        elemento.setForeground(QtGui.QBrush(QtGui.QColor(color)) if color
                               else QtGui.QBrush())
        elemento.setToolTip(fila.detalle or str(fila.origen))
        fuente = elemento.font()
        fuente.setBold(fila.estado == CONVIRTIENDO)
        elemento.setFont(fuente)

    def _refrescar(self, mantener_seleccion=False):
        seleccion = {id(f) for f in self._seleccionadas()} \
            if mantener_seleccion else set()
        self.lista.blockSignals(True)
        self.lista.clear()
        self.items.clear()

        defectos = QtWidgets.QListWidgetItem(fila_de_defectos())
        defectos.setData(QtCore.Qt.ItemDataRole.UserRole, None)
        defectos.setToolTip(_("Se aplican a todo el que no haya decidido "
                              "otra cosa"))
        fuente = defectos.font()
        fuente.setItalic(True)
        defectos.setFont(fuente)
        self.lista.addItem(defectos)
        if not seleccion and not self.lote.filas:
            defectos.setSelected(True)

        for fila in self.lote.filas:
            elemento = QtWidgets.QListWidgetItem()
            elemento.setData(QtCore.Qt.ItemDataRole.UserRole, fila)
            self.lista.addItem(elemento)
            self.items[id(fila)] = elemento
            self._actualizar_item(fila)
            if id(fila) in seleccion:
                elemento.setSelected(True)
        self.lista.blockSignals(False)
        if self.destinos is None:
            self.etiqueta_destino.setText(
                _("Sin carpeta de salida: se pregunta al convertir."))
        else:
            self.etiqueta_destino.setText(
                _("Video: {video}\nMusica: {musica}",
                  video=self.destinos.video, musica=self.destinos.musica))
        self._refrescar_resumen()
        # Repinta tambien el boton de la seleccion: la seleccion se restaura
        # con las senales bloqueadas y no llega sola.
        self._al_cambiar_seleccion()

    def _refrescar_resumen(self):
        filas = self.lote.filas
        videos = sum(1 for f in filas if f.es_video)
        hechos = sum(1 for f in filas if f.estado == HECHO)
        fallidos = sum(1 for f in filas if f.estado == FALLIDO)
        partes = [_("{n} ficheros", n=len(filas)),
                  _("{n} vídeo", n=videos),
                  _("{n} música", n=len(filas) - videos)]
        if hechos:
            partes.append(_("{n} hecho", n=hechos))
        if fallidos:
            partes.append(_("{n} fallido", n=fallidos))
        self.resumen.setText("  ·  ".join(partes) if filas else
                             _("No hay nada en la lista."))

    # --- destinos, perfiles y lotes

    def _elegir_destino(self) -> bool:
        """Un dialogo con una casilla decide si van juntas o separadas."""
        elegido = pedir_destino(self, self.destinos)
        if elegido is None:
            return False
        self.destinos = elegido
        self._refrescar()
        return True

    def _abrir_carpeta(self):
        if self.destinos is None:
            self.statusBar().showMessage(
                _("todavía no hay carpeta de salida elegida"), 5000)
            return
        carpeta = self.destinos.video
        if not carpeta.is_dir():
            carpeta = self.destinos.musica
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(carpeta)))

    def _cargar_perfil(self):
        ruta, _filtro = QtWidgets.QFileDialog.getOpenFileName(
            self, _("Valores por defecto para {clase}",
                    clase=self.panel.clase), filter="JSON (*.json)")
        if not ruta:
            return
        perfil = cargar_perfil(ruta)
        if self.panel.clase == VIDEO:
            self.lote.perfil_video = perfil
        else:
            self.lote.perfil_musica = perfil
        for fila in self.lote.filas:
            fila.seguir(self.lote.perfil_de(fila))
        self._refrescar()

    def _guardar_perfil(self):
        ruta, _filtro = QtWidgets.QFileDialog.getSaveFileName(
            self, _("Valores por defecto para {clase}",
                    clase=self.panel.clase),
            f"perfil-{self.panel.clase}.json", "JSON (*.json)")
        if ruta:
            guardar_perfil(self.lote.perfil(self.panel.clase), ruta)

    def _abrir_lote(self):
        ruta, _filtro = QtWidgets.QFileDialog.getOpenFileName(
            self, _("Abrir lote"), filter="JSON (*.json)")
        if not ruta:
            return
        try:
            perfiles, destinos, trabajos = batch.cargar(ruta)
        except batch.LoteInvalido as e:
            QtWidgets.QMessageBox.critical(self, _("Lote inválido"), str(e))
            return
        self.lote = Lote(perfiles.video, perfiles.musica)
        if destinos:
            self.destinos = destinos
        for trabajo in trabajos:
            fila = self.lote.anadir(trabajo.origen)
            if fila is None:
                continue
            fila.opciones = trabajo.opciones
            fila.nombre = trabajo.nombre
            try:
                fila.info = sondear(trabajo.origen)
            except Exception as e:
                fila.estado = FALLIDO
                fila.detalle = str(e)
            # Lo que se aparta de los valores por defecto de su clase es, por
            # definicion, un ajuste propio de esta fila.
            suyo = self.lote.perfil_de(fila)
            fila.propias = {c for c in CAMPOS
                            if getattr(trabajo.opciones, c) != getattr(suyo, c)}
        self._refrescar()

    def _guardar_lote(self):
        ruta, _filtro = QtWidgets.QFileDialog.getSaveFileName(
            self, _("Guardar lote"), "lote.json", "JSON (*.json)")
        if ruta:
            batch.guardar(ruta,
                          Perfiles(self.lote.perfil_video,
                                   self.lote.perfil_musica),
                          self.destinos,
                          [f.a_trabajo() for f in self.lote.filas])

    # --- conversion

    def _convertir_todo(self):
        if self.hilo and self.hilo.isRunning():
            self._parar()
            return
        pendientes = [f for f in self.lote.filas if f.estado != HECHO]
        if not pendientes and self.lote.filas:
            self.statusBar().showMessage(
                _("ya están todos hechos; para rehacer alguno, "
                  "selecciónalo"), 6000)
            return
        self._convertir(pendientes)

    def _convertir_seleccion(self):
        # Con seleccion se rehace lo que haga falta: marcarlo y darle es una
        # peticion explicita, no un descuido.
        self._convertir(self._seleccionadas())

    def _parar(self):
        self.hilo.parar()
        self.boton_convertir.setText(_("Parando..."))
        self.boton_convertir.setEnabled(False)
        self.marcha.setText(_("parando: se sueltan los trozos que no han "
                              "empezado"))

    def _convertir(self, filas):
        if self.hilo and self.hilo.isRunning():
            return
        ilegibles = [f for f in filas if f.info is None]
        filas = [f for f in filas if f.info is not None]
        if ilegibles:
            self.statusBar().showMessage(
                _("{n} sin leer, se quedan fuera: {cuales}",
                  n=len(ilegibles),
                  cuales=", ".join(f.origen.name for f in ilegibles[:3])),
                8000)
        if not filas:
            self.statusBar().showMessage(_("no hay nada que convertir"),
                                         5000)
            return
        if self.destinos is None and not self._elegir_destino():
            return

        # Los nombres se reparten antes de empezar: dos origenes que se
        # recortan al mismo 8.3 se pisarian, y una fila que ya tiene nombre lo
        # conserva para **reemplazar** su salida en vez de dejar otra al lado.
        trabajos = [f.a_trabajo() for f in filas]
        otras = {f.nombre for f in self.lote.filas
                 if f.nombre and f not in filas}
        asignar_nombres(trabajos, self.destinos, otras)
        if not self._avisar_de_colisiones(trabajos):
            return
        for fila, trabajo in zip(filas, trabajos):
            fila.nombre = trabajo.nombre
            fila.estado = PENDIENTE
            fila.detalle = ""
            fila.hechos = fila.total = 0

        self.pendientes = filas
        self._arranque = time.monotonic()
        self.hilo = Conversor(filas, self.destinos,
                              trabajadores_por_defecto())
        self.hilo.empieza.connect(self._al_empezar)
        self.hilo.avance.connect(self._al_avanzar)
        self.hilo.terminado.connect(self._al_terminar)
        self.hilo.finished.connect(self._al_acabar_todo)
        self.boton_convertir.setText(_("Parar"))
        self.boton_seleccion.setEnabled(False)
        self.hilo.start()
        self._refrescar(mantener_seleccion=True)

    def _avisar_de_colisiones(self, trabajos) -> bool:
        """Pregunta antes de pisar nada. Devuelve si hay que seguir."""
        choques = colisiones(trabajos, self.destinos)
        if not choques:
            return True
        detalle = "\n".join(f"· {t.origen.name}: {motivo}"
                             for t, motivo in choques[:8])
        if len(choques) > 8:
            detalle += "\n" + _("... y {n} más", n=len(choques) - 8)
        respuesta = QtWidgets.QMessageBox.question(
            self, _("Ya hay ficheros ahí"),
            _("{n} conversión(es) van a escribir encima de lo que ya hay:",
              n=len(choques)) + "\n\n" + detalle,
            QtWidgets.QMessageBox.StandardButton.Ok
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Ok)
        return respuesta == QtWidgets.QMessageBox.StandardButton.Ok

    def _al_empezar(self, n):
        fila = self.pendientes[n]
        fila.estado = CONVIRTIENDO
        fila.hechos = 0
        fila.total = (fila.info.frames_destino
                      if fila.info and fila.es_video else 0)
        self.progreso.setFormat("%v/%m " + (_("frames") if fila.es_video
                                            else _("bloques")))
        self._actualizar_item(fila)
        self._pintar_marcha(n, forzar=True)
        if fila.total:
            self.marcha.setText(self.marcha.text()
                                + "  ·  " + _("repartiendo trozos..."))

    def _al_avanzar(self, n, hechos, total):
        fila = self.pendientes[n]
        fila.estado = CONVIRTIENDO
        fila.hechos, fila.total = hechos, total or fila.total
        self._pintar_marcha(n)

    def _pintar_marcha(self, n, forzar=False):
        ahora = time.monotonic()
        if not forzar and ahora - self._pintado < REFRESCO:
            return
        self._pintado = ahora
        fila = self.pendientes[n]
        self._actualizar_item(fila)

        self.progreso.setMaximum(fila.total or 0)
        self.progreso.setValue(fila.hechos)

        parte = (n + fila.parte) / len(self.pendientes)
        self.progreso_lote.setValue(int(parte * 1000))
        texto = _("Fichero {n} de {total}  ·  {nombre}", n=n + 1,
                  total=len(self.pendientes), nombre=fila.origen.name)
        transcurrido = ahora - self._arranque
        if parte > 0.01 and transcurrido > 2:
            queda = transcurrido * (1 - parte) / parte
            texto += "  ·  " + _("quedan {tiempo}", tiempo=_reloj(queda))
        # Recortado al ancho que haya: partirlo en dos lineas descoloca la
        # barra entera cada vez que cambia de fichero.
        metrica = QtGui.QFontMetrics(self.marcha.font())
        self.marcha.setText(metrica.elidedText(
            texto, QtCore.Qt.TextElideMode.ElideMiddle,
            max(self.marcha.width() - 4, 120)))

    def _al_terminar(self, n, resultado, error):
        fila = self.pendientes[n]
        if error:
            fila.estado = FALLIDO
            fila.detalle = error
        else:
            fila.estado = HECHO
            fila.avisos = resultado.avisos
            fila.nombre = resultado.nombre
            fila.detalle = ", ".join(f.name for f in resultado.ficheros)
        self._actualizar_item(fila)
        self._refrescar_resumen()
        self._pintar_marcha(n, forzar=True)

    def _al_acabar_todo(self):
        parado = self.hilo is not None and self.hilo.cancelar.is_set()
        for fila in self.pendientes:
            if fila.estado == CONVIRTIENDO:
                fila.estado = PENDIENTE
                fila.hechos = fila.total = 0
            self._actualizar_item(fila)
        self.boton_convertir.setText(_("Convertir todo"))
        self.boton_convertir.setEnabled(True)
        self._al_cambiar_seleccion()
        self.progreso.reset()
        self.progreso_lote.setValue(0)
        hechos = sum(1 for f in self.lote.filas if f.estado == HECHO)
        self.marcha.setText(_("parado") if parado else "")
        self._refrescar_resumen()
        donde = (_(" en {carpeta}", carpeta=self.destinos.video)
                 if self.destinos else "")
        self.statusBar().showMessage(
            _("{n} convertido(s)", n=hechos) + donde
            + (_(", parado a mitad") if parado else ""), 12000)

    def closeEvent(self, evento):
        if self.mudando:
            super().closeEvent(evento)
            return
        # Solo molesta si hay conversion en marcha: tener ficheros en la lista
        # sin convertir es el estado normal de la aplicacion, no un aviso.
        convirtiendo = bool(self.hilo and self.hilo.isRunning())
        if convirtiendo:
            quedan = sum(1 for f in self.pendientes if f.estado != HECHO)
            respuesta = QtWidgets.QMessageBox.question(
                self, _("Salir de gbamedia"),
                _("Hay una conversión en marcha. Si sales ahora se parará a "
                  "medias y quedarán {n} sin terminar.", n=quedan),
                QtWidgets.QMessageBox.StandardButton.Close
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel)
            if respuesta != QtWidgets.QMessageBox.StandardButton.Close:
                evento.ignore()
                return
        if convirtiendo:
            self.hilo.parar()
            self.hilo.wait(5000)
        if self.sondeador and self.sondeador.isRunning():
            self.sondeador.parar = True
            self.sondeador.wait(5000)
        super().closeEvent(evento)


def _reloj(segundos: float) -> str:
    segundos = int(segundos)
    if segundos < 60:
        return _("{s} s", s=segundos)
    return _("{m} min {s:02d} s", m=segundos // 60, s=segundos % 60)


def main(argv=None) -> int:
    # Sin esto, el ejecutable congelado de Windows abriria una ventana nueva
    # por cada proceso de trabajo.
    multiprocessing.freeze_support()
    app = QtWidgets.QApplication(argv or sys.argv)
    guardado = QtCore.QSettings("gbamedia", "gbamedia").value("idioma")
    i18n.usar(guardado or i18n.del_sistema())
    ventana = Ventana()
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
