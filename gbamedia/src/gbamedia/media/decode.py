"""Entrada moderna: de mp4/mkv/mp3/lo que sea a lo que comen los codecs.

Video  -> frames RGB888 de 240x160 a 10 fps
Audio  -> PCM de 16 bits, 44100 Hz, estereo, que es de donde parte el .gbs

El ajuste de tempo se aplica **a los dos flujos a la vez**: retocar solo el
video para arreglar la cadencia meteria justo el desfase que se pretende
quitar.
"""
from dataclasses import dataclass, field

import numpy as np

from . import ffmpeg, fit
from .probe import FPS_DESTINO, FRECUENCIA, Info

ANCHO, ALTO = fit.ANCHO, fit.ALTO
BYTES_FRAME = ANCHO * ALTO * 3


@dataclass(frozen=True)
class Opciones:
    ajuste: str = fit.BARRAS
    color_barras: str = "black"
    imagen: fit.Imagen = field(default_factory=fit.Imagen)
    mezclar_frames: bool = False
    tempo: float = 1.0          # >1 acelera; 1.0 = no tocar
    desde: float | None = None
    duracion: float | None = None

    @property
    def retoca_tempo(self) -> bool:
        return abs(self.tempo - 1.0) > 1e-9


def _recorte(opciones: Opciones) -> list[str]:
    argumentos = []
    if opciones.desde is not None:
        argumentos += ["-ss", f"{opciones.desde:.6f}"]
    if opciones.duracion is not None:
        argumentos += ["-t", f"{opciones.duracion:.6f}"]
    return argumentos


def cadena_video(opciones: Opciones) -> str:
    partes = []
    if opciones.retoca_tempo:
        partes.append(f"setpts=PTS/{opciones.tempo:.9f}")
    if opciones.mezclar_frames:
        # Mezcla en vez de descartar: no arregla el aliasing del ciclo, pero
        # disimula los tirones de una cadencia que no divide.
        partes.append(f"minterpolate=fps={FPS_DESTINO}:mi_mode=blend")
    else:
        partes.append(f"fps={FPS_DESTINO}")
    partes.append(fit.filtro_escalado(opciones.ajuste, opciones.color_barras))
    imagen = fit.filtro_imagen(opciones.imagen)
    if imagen:
        partes.append(imagen)
    return ",".join(partes)


def cadena_audio(opciones: Opciones) -> str:
    partes = []
    if opciones.retoca_tempo:
        # atempo solo acepta 0.5..2 por paso; fuera de ahi se encadena.
        resto = opciones.tempo
        while resto > 2.0:
            partes.append("atempo=2.0")
            resto /= 2.0
        while resto < 0.5:
            partes.append("atempo=0.5")
            resto /= 0.5
        partes.append(f"atempo={resto:.9f}")
    partes.append(f"aresample={FRECUENCIA}")
    partes.append("aformat=sample_fmts=s16:channel_layouts=stereo")
    return ",".join(partes)


def frames(info: Info, opciones: Opciones = Opciones()):
    """Itera frames (160,240,3) uint8 listos para el codificador."""
    argumentos = (_recorte(opciones)
                  + ["-i", str(info.ruta), "-an",
                     "-vf", cadena_video(opciones),
                     "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
    proceso = ffmpeg.abrir(argumentos)
    agotado = False
    try:
        while True:
            crudo = proceso.stdout.read(BYTES_FRAME)
            if len(crudo) < BYTES_FRAME:
                agotado = True
                break
            yield np.frombuffer(crudo, dtype=np.uint8).reshape(ALTO, ANCHO, 3)
    finally:
        error = b""
        if agotado:
            error = proceso.stderr.read()
        else:
            # Se abandono la lectura a medias: ffmpeg se queja de tuberia rota
            # y esa queja no es un fallo de conversion.
            if proceso.poll() is None:
                proceso.terminate()
        proceso.stdout.close()
        proceso.stderr.close()
        proceso.wait()
        if agotado and proceso.returncode != 0:
            raise ffmpeg.ErrorFfmpeg(error.decode("utf-8", "replace").strip())


def audio(info: Info, opciones: Opciones = Opciones()) -> np.ndarray:
    """PCM (n,2) int16 a 44100 Hz. Si no hay pista de audio, devuelve silencio.

    El silencio no es un caso raro: un video mudo tambien necesita su `.gbs`
    companero, porque el reproductor espera el par.
    """
    if not info.tiene_audio:
        return np.zeros((0, 2), dtype=np.int16)
    argumentos = (_recorte(opciones)
                  + ["-i", str(info.ruta), "-vn",
                     "-af", cadena_audio(opciones),
                     "-f", "s16le", "-"])
    crudo = ffmpeg.ejecutar(argumentos)
    muestras = np.frombuffer(crudo, dtype="<i2")
    return muestras[:len(muestras) // 2 * 2].reshape(-1, 2)


def ajustar_duracion(pcm: np.ndarray, segundos: float) -> np.ndarray:
    """Recorta o rellena con silencio hasta la duracion exacta pedida.

    El `.gbs` companero de un video tiene que durar `frames/10` segundos
    clavados: los dos flujos se consumen a su ritmo nominal y nadie los
    resincroniza.
    """
    objetivo = int(round(segundos * FRECUENCIA))
    if len(pcm) == objetivo:
        return pcm
    if len(pcm) > objetivo:
        return pcm[:objetivo]
    relleno = np.zeros((objetivo - len(pcm), 2), dtype=np.int16)
    return np.concatenate([pcm, relleno])
