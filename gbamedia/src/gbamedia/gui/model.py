"""Los datos del lote que ve la ventana.

Dos niveles: los **valores por defecto del lote**, que son dos juegos (uno para
video y otro para musica, porque casi nada de lo que decide un video le importa
a un mp3), y las **sobrescrituras** de cada fichero. Una fila solo guarda los
nombres de los campos que ha tocado; el resto sigue a su perfil, asi que
cambiar el perfil se propaga solo a quien no haya decidido otra cosa.
"""
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from ..settings import modo_depuracion
from ..i18n import _
from ..jobs.convert import Trabajo
from ..jobs.options import Opciones
from ..media.probe import parece_video

CAMPOS = tuple(f.name for f in fields(Opciones))

PENDIENTE = "pendiente"
CONVIRTIENDO = "convirtiendo"
HECHO = "hecho"
FALLIDO = "fallido"

MARCAS = {PENDIENTE: "·", CONVIRTIENDO: "▶", HECHO: "✓", FALLIDO: "✗"}

# Los modos de audio no salen del preset de video cuando lo que se convierte es
# musica: ahi el modo es la unica decision de calidad que hay, y se dice.
PERFIL_MUSICA = Opciones(modo_audio=0)


@dataclass
class Fila:
    origen: Path
    opciones: Opciones
    propias: set = field(default_factory=set)
    nombre: str | None = None
    info: object = None
    estado: str = PENDIENTE
    detalle: str = ""
    avisos: list = field(default_factory=list)
    hechos: int = 0                 # frames convertidos
    total: int = 0                  # frames que se esperan

    @property
    def es_video(self) -> bool:
        """Si todavia no ha contestado ffprobe, se cree a la extension.

        Mientras se sondea la fila ya esta en la lista, y darla por musica
        hasta saberlo hacia que un video se ensenase como "musica" durante
        toda la lectura. `sondear` sigue teniendo la ultima palabra.
        """
        if self.info is None:
            return parece_video(self.origen)
        return bool(self.info.es_video)

    @property
    def parte(self) -> float:
        """Fraccion convertida, 0..1."""
        if self.estado == HECHO:
            return 1.0
        if self.estado != CONVIRTIENDO or not self.total:
            return 0.0
        return min(1.0, self.hechos / self.total)

    def poner(self, campo: str, valor) -> None:
        self.opciones = replace(self.opciones, **{campo: valor})
        self.propias.add(campo)

    def soltar(self, campo: str, perfil: Opciones) -> None:
        """Deja de decidir por su cuenta y vuelve al valor del lote."""
        self.propias.discard(campo)
        self.opciones = replace(self.opciones, **{campo: getattr(perfil, campo)})

    def seguir(self, perfil: Opciones) -> None:
        """Recoge del perfil todo lo que no haya sobrescrito."""
        cambios = {c: getattr(perfil, c) for c in CAMPOS
                   if c not in self.propias}
        self.opciones = replace(self.opciones, **cambios)

    def a_trabajo(self) -> Trabajo:
        return Trabajo(self.origen, self.opciones, self.nombre, self.info)

    def etiqueta(self) -> str:
        marcas = []
        if len(self.propias) == 1:
            marcas.append(_("1 ajuste propio"))
        elif self.propias:
            marcas.append(_("{n} ajustes propios", n=len(self.propias)))
        if self.avisos and modo_depuracion():
            marcas.append(_("aviso de cadencia"))
        if self.estado == CONVIRTIENDO and self.total:
            unidad = _("frames") if self.es_video else _("bloques")
            marcas.append(_("{hechos}/{total} {unidad} ({parte:.0f} %)",
                            hechos=self.hechos, total=self.total,
                            unidad=unidad, parte=self.parte * 100))
        elif self.detalle:
            # Vale tambien para el "leyendo..." de una fila recien anadida,
            # que todavia esta pendiente.
            marcas.append(self.detalle)
        elif self.estado != PENDIENTE:
            marcas.append(_(self.estado))
        return "  ·  ".join(marcas)


class Lote:
    def __init__(self, perfil_video: Opciones | None = None,
                 perfil_musica: Opciones | None = None):
        self.perfil_video = perfil_video or Opciones()
        self.perfil_musica = perfil_musica or PERFIL_MUSICA
        self.filas: list[Fila] = []

    def perfil_de(self, fila: Fila) -> Opciones:
        return self.perfil_video if fila.es_video else self.perfil_musica

    def perfil(self, clase: str) -> Opciones:
        return self.perfil_video if clase == "video" else self.perfil_musica

    def anadir(self, origen: Path) -> Fila | None:
        origen = Path(origen)
        if any(f.origen == origen for f in self.filas):
            return None
        fila = Fila(origen, self.perfil_video if parece_video(origen)
                    else self.perfil_musica)
        self.filas.append(fila)
        return fila

    def encuadrar(self, fila: Fila) -> None:
        """Al saber que clase de fichero es, recoge el perfil que le toca."""
        fila.seguir(self.perfil_de(fila))

    def quitar(self, filas) -> None:
        fuera = set(id(f) for f in filas)
        self.filas = [f for f in self.filas if id(f) not in fuera]

    def poner_en_perfil(self, campo: str, valor, clase: str) -> None:
        perfil = replace(self.perfil(clase), **{campo: valor})
        if clase == "video":
            self.perfil_video = perfil
        else:
            self.perfil_musica = perfil
        for fila in self.filas:
            if self.perfil_de(fila) is perfil:
                fila.seguir(perfil)
