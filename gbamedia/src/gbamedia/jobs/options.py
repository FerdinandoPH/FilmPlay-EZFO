"""Las opciones efectivas de una conversion, y como se serializan.

Tres capas, de menor a mayor prioridad:

    valores por defecto  <  perfil del lote  <  sobrescritura por fichero

Todo lo que decide el resultado vive aqui, de modo que un trabajo preparado en
la interfaz se pueda relanzar desde la terminal y al reves.
"""
import json
from dataclasses import asdict, dataclass, field, fields, replace

from ..core.gbm_encode import BUSQUEDAS, CALIDADES
from ..core.gbs_decode import MODOS
from ..media import fit
from ..media.probe import parece_video

PRESETS = tuple(CALIDADES)
ETIQUETAS_AUDIO = {m.etiqueta: n for n, m in MODOS.items()}


@dataclass(frozen=True)
class Opciones:
    # --- video
    preset: str = "alta"
    frame_size: int | None = None          # None = el del preset
    tolerancias: tuple | None = None       # None = las del preset
    sin_vectores: bool = False
    busqueda: str = "rapida"                # como se buscan los vectores
    ajuste: str = fit.BARRAS
    color_barras: str = "black"
    brillo: int = 0
    contraste: int = 100
    realce: int = 0
    # --- audio
    modo_audio: int | None = None          # None = el que fija el preset
    canal: int = 0                         # 0 izquierdo, 1 derecho
    volumen: int = 0                       # 0..3 = x1, x2, x4, x8
    # --- cadencia
    tempo: float = 1.0
    mezclar_frames: bool = False
    # --- recorte
    desde: float | None = None
    duracion: float | None = None
    # --- salida
    nombre: str | None = None              # None = el del fichero de origen
    numerar: bool = False                  # True = Mnnnnn, como el original
    rellenar_cluster: int = 0              # bytes de cluster, 0 = no rellenar

    def __post_init__(self):
        if self.preset not in CALIDADES:
            raise ValueError(f"preset desconocido: {self.preset!r}")
        if self.busqueda not in BUSQUEDAS:
            raise ValueError(f"busqueda desconocida: {self.busqueda!r}")
        if self.ajuste not in fit.AJUSTES:
            raise ValueError(f"ajuste desconocido: {self.ajuste!r}")
        if self.modo_audio is not None and self.modo_audio not in MODOS:
            raise ValueError(f"modo de audio desconocido: {self.modo_audio}")
        if self.canal not in (0, 1):
            raise ValueError("canal: 0 (izquierdo) o 1 (derecho)")
        if not 0 <= self.volumen <= 3:
            raise ValueError("volumen: 0..3")

    # --- derivados

    @property
    def calidad(self):
        c = CALIDADES[self.preset]
        cambios = {"busqueda": self.busqueda}
        if self.frame_size is not None:
            cambios["frame_size"] = self.frame_size
        if self.tolerancias is not None:
            cambios["tolerancias"] = tuple(self.tolerancias)
        if self.sin_vectores:
            cambios["vectores"] = False
        return replace(c, **cambios)

    @property
    def modo(self):
        numero = (self.modo_audio if self.modo_audio is not None
                  else CALIDADES[self.preset].modo_audio)
        return MODOS[numero]

    @property
    def opciones_media(self):
        from ..media.decode import Opciones as OpcionesMedia
        return OpcionesMedia(
            ajuste=self.ajuste, color_barras=self.color_barras,
            imagen=fit.Imagen(self.brillo, self.contraste, self.realce),
            mezclar_frames=self.mezclar_frames, tempo=self.tempo,
            desde=self.desde, duracion=self.duracion)

    # --- capas

    def con(self, **cambios) -> "Opciones":
        """Sobrescritura: solo lo que se pasa, lo demas se mantiene."""
        limpios = {k: v for k, v in cambios.items() if v is not None}
        return replace(self, **limpios) if limpios else self

    def a_json(self) -> dict:
        return {k: v for k, v in asdict(self).items()
                if v != getattr(Opciones(), k)}

    @classmethod
    def desde_json(cls, datos: dict) -> "Opciones":
        validos = {f.name for f in fields(cls)}
        sobra = set(datos) - validos
        if sobra:
            raise ValueError(f"opciones desconocidas: {sorted(sobra)}")
        if "tolerancias" in datos and datos["tolerancias"] is not None:
            datos = dict(datos, tolerancias=tuple(datos["tolerancias"]))
        return cls(**datos)


@dataclass(frozen=True)
class Perfiles:
    """Los valores por defecto, que son dos: los del video y los de la musica.

    Casi nada de lo que decide un video le importa a un mp3, y al reves el modo
    de audio es lo unico que decide la calidad de la musica. Tenerlos separados
    es lo que permite que la ventana ensene de cada clase solo lo suyo.
    """
    video: Opciones = field(default_factory=Opciones)
    musica: Opciones | None = None       # None = los mismos que el video

    def __post_init__(self):
        if self.musica is None:
            object.__setattr__(self, "musica", self.video)

    def para(self, ruta) -> Opciones:
        return self.video if parece_video(ruta) else self.musica

    def a_json(self) -> dict:
        datos = {"perfil_video": self.video.a_json()}
        if self.musica != self.video:
            datos["perfil_musica"] = self.musica.a_json()
        return datos


def cargar_perfil(ruta) -> Opciones:
    with open(ruta, encoding="utf-8") as f:
        return Opciones.desde_json(json.load(f))


def guardar_perfil(opciones: Opciones, ruta) -> None:
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(opciones.a_json(), f, indent=2, ensure_ascii=False)
        f.write("\n")
