"""Dialogos de la ventana.

El de destino sustituye a los cuatro botones de carpeta que habia en la barra:
una casilla decide si video y musica van juntos o separados, y solo entonces
aparece la segunda ruta.
"""
from pathlib import Path

from PySide6 import QtWidgets

from ..i18n import _
from ..jobs.convert import Destinos

SUBCARPETA = "videos"


class DialogoDestino(QtWidgets.QDialog):
    """Elige donde dejar lo convertido.

    Ni la subcarpeta ni la separacion son obligatorias: la ROM lista por
    extension y le da igual el arbol. Lo unico que importa de verdad es que un
    `.gbs` de musica no acabe con el mismo nombre que un video, porque
    entonces se convierte en su banda sonora.
    """

    def __init__(self, padre=None, destinos: Destinos | None = None):
        super().__init__(padre)
        self.setWindowTitle(_("Carpeta de salida"))
        self.setMinimumWidth(560)
        vertical = QtWidgets.QVBoxLayout(self)

        self.separar = QtWidgets.QCheckBox(
            _("Carpetas distintas para video y música"))
        self.separar.toggled.connect(self._al_separar)
        vertical.addWidget(self.separar)

        self.subcarpeta = QtWidgets.QCheckBox(
            _("Poner los videos en una subcarpeta {sub}/", sub=SUBCARPETA))
        self.subcarpeta.setChecked(True)
        self.subcarpeta.toggled.connect(
            lambda marcado: self._al_separar(self.separar.isChecked()))
        vertical.addWidget(self.subcarpeta)

        rejilla = QtWidgets.QGridLayout()
        self.campos, self.etiquetas = {}, {}
        for fila, (clave, texto) in enumerate((("una", _("Carpeta")),
                                               ("video", _("Video")),
                                               ("musica", _("Música")))):
            etiqueta = QtWidgets.QLabel(texto)
            campo = QtWidgets.QLineEdit()
            boton = QtWidgets.QPushButton(_("Examinar..."))
            boton.clicked.connect(
                lambda marcado=False, c=clave: self._examinar(c))
            rejilla.addWidget(etiqueta, fila, 0)
            rejilla.addWidget(campo, fila, 1)
            rejilla.addWidget(boton, fila, 2)
            rejilla.setColumnStretch(1, 1)
            self.campos[clave] = campo
            self.etiquetas[clave] = (etiqueta, boton)
        vertical.addLayout(rejilla)

        self.pista = QtWidgets.QLabel()
        self.pista.setWordWrap(True)
        vertical.addWidget(self.pista)
        vertical.addStretch(1)

        botones = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        vertical.addWidget(botones)

        self._poner(destinos)
        self._al_separar(self.separar.isChecked())

    # --- estado

    def _poner(self, destinos: Destinos | None) -> None:
        if destinos is None:
            base = Path.home() / "gbamedia"
            self.campos["una"].setText(str(base))
            self.campos["video"].setText(str(base / SUBCARPETA))
            self.campos["musica"].setText(str(base))
            return
        con_sub = destinos.video == destinos.musica / SUBCARPETA
        self.separar.setChecked(not (con_sub or destinos.video == destinos.musica))
        self.subcarpeta.setChecked(con_sub)
        self.campos["una"].setText(str(destinos.musica))
        self.campos["video"].setText(str(destinos.video))
        self.campos["musica"].setText(str(destinos.musica))

    def _al_separar(self, separadas: bool) -> None:
        for clave in ("video", "musica"):
            self.campos[clave].setVisible(separadas)
            for w in self.etiquetas[clave]:
                w.setVisible(separadas)
        self.campos["una"].setVisible(not separadas)
        for w in self.etiquetas["una"]:
            w.setVisible(not separadas)
        self.subcarpeta.setVisible(not separadas)
        if separadas:
            self.pista.setText("")
        elif self.subcarpeta.isChecked():
            self.pista.setText(
                _("Los videos irán a {sub}/ y la música a la carpeta "
                  "elegida.", sub=SUBCARPETA))
        else:
            self.pista.setText(
                _("Todo en la misma carpeta. Ojo: un .gbs de música que se "
                  "llame como un video pasa a ser su banda sonora, así que se "
                  "avisará si va a pasar."))

    def _examinar(self, clave: str) -> None:
        actual = self.campos[clave].text()
        ruta = QtWidgets.QFileDialog.getExistingDirectory(
            self, _("Elegir carpeta"), actual)
        if ruta:
            self.campos[clave].setText(ruta)

    def destinos(self) -> Destinos | None:
        """Lo elegido, o None si algun campo se ha quedado vacio."""
        if self.separar.isChecked():
            video, musica = (self.campos["video"].text().strip(),
                             self.campos["musica"].text().strip())
            if not video or not musica:
                return None
            return Destinos(Path(video).expanduser().resolve(),
                            Path(musica).expanduser().resolve())
        una = self.campos["una"].text().strip()
        if not una:
            return None
        raiz = Path(una).expanduser().resolve()
        return Destinos(raiz / SUBCARPETA if self.subcarpeta.isChecked()
                        else raiz, raiz)


def pedir_destino(padre, destinos: Destinos | None) -> Destinos | None:
    dialogo = DialogoDestino(padre, destinos)
    if dialogo.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return None
    return dialogo.destinos()
