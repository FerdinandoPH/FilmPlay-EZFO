"""Cadencia: los dos problemas de reproducir a 10 fps, que no son el mismo.

1. **fps no divisibles**: si los fps de origen no son multiplo de 10, la
   reduccion tira frames de forma desigual y el movimiento da tirones. Se
   arregla mezclando frames en vez de descartarlos.
2. **Ciclo del movimiento que no divide 10 Hz**: a 10 fps solo se pueden
   colocar eventos cada 100 ms. Una animacion a 140 BPM tiene tiempos de
   428,57 ms, asi que los pasos caen en 0, 400, 900, 1300 ms y el error va
   rotando con un patron de 3 s que el ojo lee como "va por detras de la
   musica". Se arregla **retocando el tempo**, no mezclando frames.

El segundo es el que desajustaba furret walk (INFORME_VIABILIDAD.md §34) y el
que no se ve venir sin medirlo.
"""
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from ..i18n import _

FPS_DESTINO = 10

FPS = "fps"
CICLO = "ciclo"

# Un video aguanta un retoque de tempo pequeno sin que se note en la voz ni en
# la musica. Fuera de esta horquilla el arreglo no es un arreglo: si la medida
# dice que hay que acelerar un 700 % es que se ha ido a un armonico, y aplicarlo
# destroza un video que probablemente estaba bien.
FACTOR_MINIMO = 0.8
FACTOR_MAXIMO = 1.25


@dataclass(frozen=True)
class Aviso:
    """Un problema de cadencia y **como se arregla**.

    `arreglo` son los campos de `Opciones` que lo corrigen, para que la
    interfaz pueda ofrecer un boton y la linea de ordenes una bandera. Dejar
    solo el texto obligaba a copiar a mano un factor de seis decimales de un
    aviso a otro campo, que es justo lo que no se debe pedir a nadie.
    """
    codigo: str
    titulo: str
    mensaje: str
    sugerencia: str = ""
    arreglo: dict | None = None


def bpm_validos(minimo: float = 40.0, maximo: float = 300.0) -> list[float]:
    """BPM cuyo tiempo dura un multiplo exacto de 100 ms.

    El tiempo dura 60000/BPM ms, asi que la condicion es BPM = 600/k.
    """
    fuera = []
    k = 1
    while 600 / k >= minimo:
        if 600 / k <= maximo:
            fuera.append(600 / k)
        k += 1
    return sorted(fuera)


def bpm_mas_cercano(bpm: float) -> float:
    return min(bpm_validos(), key=lambda v: abs(v - bpm))


def factor_tempo(origen: float, destino: float) -> float:
    if origen <= 0:
        raise ValueError("BPM de origen invalido")
    return destino / origen


def frames_por_ciclo(bpm: float) -> float:
    return FPS_DESTINO * 60.0 / bpm if bpm else 0.0


def aviso_fps(fps: Fraction) -> Aviso | None:
    if not fps:
        return None
    if float(fps) < FPS_DESTINO:
        return Aviso(
            FPS, _("El original tiene menos frames de los que caben"),
            _("Va a {fps:.3f} fps y la consola reproduce a {destino}, así que "
              "algunos frames se verán repetidos. No hay nada que arreglar: "
              "no se puede inventar movimiento que no está.",
              fps=float(fps), destino=FPS_DESTINO))
    if Fraction(fps) % FPS_DESTINO:
        return Aviso(
            FPS, _("El movimiento va a dar tirones"),
            _("El original va a {fps:.3f} fps, que no es múltiplo de "
              "{destino}: al quedarse con uno de cada tantos, unos frames "
              "duran más que otros y el movimiento sale a saltos.",
              fps=float(fps), destino=FPS_DESTINO),
            _("Mezclar cada frame con los que se descartan, que reparte el "
              "movimiento en vez de tirarlo."),
            {"mezclar_frames": True})
    return None


class Energia:
    """Acumula la energia de diferencia entre frames sin guardarlos.

    Un video de 1080 frames son 124 MB en RGB; para medir la cadencia solo hace
    falta un numero por frame, asi que se acumula al vuelo mientras se codifica.
    """

    def __init__(self, fps: int = FPS_DESTINO):
        self.fps = fps
        self.valores: list[float] = []
        self._anterior = None

    def anadir(self, frame) -> None:
        actual = np.asarray(frame, dtype=np.float32)
        if actual.ndim == 3:
            actual = actual.mean(axis=2)
        if self._anterior is not None:
            self.valores.append(float(np.abs(actual - self._anterior).mean()))
        self._anterior = actual

    # Con menos material que esto la medida no vale: el pico mas alto del
    # espectro deja de ser el fundamental y sale el doble, el triple o
    # cualquier cosa. Medido sobre furret walk y el patron de sincronia, por
    # debajo de 30 s las cuatro fuentes dan cifras absurdas y por encima de 40
    # todas dan la buena.
    SEGUNDOS_MINIMOS = 30.0

    @property
    def segundos(self) -> float:
        return len(self.valores) / self.fps

    @property
    def fiable(self) -> bool:
        # En frames y no en segundos, para que pedir justo el minimo no se
        # quede fuera por el valor que se pierde al hacer diferencias.
        return len(self.valores) + 1 >= self.SEGUNDOS_MINIMOS * self.fps

    def frecuencia(self) -> float:
        """Frecuencia del ciclo del movimiento, en Hz. 0 si no es fiable.

        Devolver 0 en vez de una cifra dudosa es deliberado: un aviso de
        cadencia equivocado manda a retocar el tempo de un video que estaba
        bien, y eso es peor que no avisar.
        """
        if not self.fiable:
            return 0.0
        x = np.array(self.valores)
        x -= x.mean()
        espectro = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        frecuencias = np.fft.rfftfreq(len(x), d=1.0 / self.fps)
        # El primer bin es la deriva; no interesa
        k = int(np.argmax(espectro[1:])) + 1
        return float(frecuencias[k])


def frecuencia_dominante(frames, fps: int = FPS_DESTINO) -> float:
    """Frecuencia del movimiento, en Hz, midiendo la energia de diferencia.

    `frames` es una secuencia de imagenes (H,W,3) o (H,W). Es la medida que
    delato el aliasing de furret walk: 2,333 Hz, o sea 140 BPM, que a 10 fps da
    4,29 frames por ciclo en vez de un numero entero.
    """
    acumulador = Energia(fps)
    for f in frames:
        acumulador.anadir(f)
    return acumulador.frecuencia()


def bpm_medido(frecuencia: float, margen: float = 0.006) -> float:
    """BPM a partir de la frecuencia, redondeado al entero si esta cerca.

    La medida tiene el ruido del tamano de la ventana: furret walk sale a
    2,331 Hz cuando de verdad va a 2,3333. Los tempos musicales casi siempre
    son enteros, y redondear deja el factor de ajuste en el numero limpio
    (1,071429 para 140->150) en vez de arrastrar el error de la medida.
    """
    bpm = frecuencia * 60.0
    entero = round(bpm)
    if entero and abs(bpm - entero) / entero <= margen:
        return float(entero)
    return bpm


def aviso_ciclo(frecuencia: float, tolerancia: float = 0.08) -> Aviso | None:
    """Avisa si el ciclo del movimiento no cae en la rejilla de 10 Hz."""
    if frecuencia <= 0:
        return None
    bpm = bpm_medido(frecuencia)
    por_ciclo = frames_por_ciclo(bpm)
    if abs(por_ciclo - round(por_ciclo)) <= tolerancia:
        return None
    destino = bpm_mas_cercano(bpm)
    factor = factor_tempo(bpm, destino)
    if not FACTOR_MINIMO <= factor <= FACTOR_MAXIMO:
        # Medida poco creible: mejor callar que mandar a estropear el video.
        return None
    return Aviso(
        CICLO, _("La animación se irá desfasando de la música"),
        _("El movimiento se repite {bpm:.1f} veces por minuto, o sea cada "
          "{ciclo:.2f} frames. Como la consola solo puede enseñar frames "
          "enteros, cada ciclo cae un poco más tarde que el anterior y en "
          "unos segundos se ve que la imagen va por detrás del sonido.",
          bpm=bpm, ciclo=por_ciclo),
        _("Acelerar imagen y sonido un {porciento:+.1f} % para dejar el "
          "movimiento en {destino:.1f} por minuto, que sale exacto a "
          "{frames:.0f} frames por ciclo.",
          porciento=(factor - 1) * 100, destino=destino,
          frames=frames_por_ciclo(destino)),
        {"tempo": round(factor, 6)})
