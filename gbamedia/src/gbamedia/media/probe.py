"""Lo que hay dentro de un fichero de entrada, y que hacer con el."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from . import ffmpeg

EXTENSIONES_VIDEO = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpg",
                     ".mpeg", ".wmv", ".flv", ".ogv"}
EXTENSIONES_AUDIO = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus",
                     ".wma", ".aiff", ".aif"}
EXTENSIONES = EXTENSIONES_VIDEO | EXTENSIONES_AUDIO

FPS_DESTINO = 10          # el reproductor asume 10 fps, no es negociable
FRECUENCIA = 44100        # el .gbs parte siempre de 44100/16/estereo


@dataclass(frozen=True)
class Info:
    ruta: Path
    duracion: float
    tiene_video: bool
    tiene_audio: bool
    ancho: int = 0
    alto: int = 0
    fps: Fraction = Fraction(0)
    codec_video: str = ""
    codec_audio: str = ""
    frecuencia: int = 0
    canales: int = 0

    @property
    def es_video(self) -> bool:
        """Un video se convierte a par .gbm + .gbs; lo demas, a .gbs suelto."""
        return self.tiene_video

    @property
    def frames_destino(self) -> int:
        return int(round(self.duracion * FPS_DESTINO))

    @property
    def aspecto(self) -> float:
        return self.ancho / self.alto if self.alto else 0.0


def parece_video(ruta) -> bool:
    """Adivina por la extension, sin abrir el fichero.

    Vale para decidir que valores por defecto le tocan a un fichero antes de
    sondearlo; la palabra definitiva la tiene `sondear`, que mira los streams
    de verdad (un .mp4 sin imagen es musica y un .mp3 con caratula no lo es).
    """
    return Path(ruta).suffix.lower() in EXTENSIONES_VIDEO


def _fraccion(texto: str) -> Fraction:
    try:
        return Fraction(texto)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def sondear(fichero) -> Info:
    fichero = Path(fichero)
    crudo = ffmpeg.sondear_crudo(fichero)
    video = next((s for s in crudo["streams"]
                  if s.get("codec_type") == "video"), None)
    audio = next((s for s in crudo["streams"]
                  if s.get("codec_type") == "audio"), None)

    # Las caratulas empotradas en un mp3 son un stream de video de un frame:
    # no convierten el fichero en un video.
    if video is not None and video.get("disposition", {}).get(
            "attached_pic") == 1:
        video = None

    duracion = float(crudo.get("format", {}).get("duration") or 0.0)
    if not duracion:
        for s in (video, audio):
            if s and s.get("duration"):
                duracion = max(duracion, float(s["duration"]))

    return Info(
        ruta=fichero,
        duracion=duracion,
        tiene_video=video is not None,
        tiene_audio=audio is not None,
        ancho=int(video["width"]) if video else 0,
        alto=int(video["height"]) if video else 0,
        fps=_fraccion(video.get("avg_frame_rate", "0")) if video else Fraction(0),
        codec_video=video.get("codec_name", "") if video else "",
        codec_audio=audio.get("codec_name", "") if audio else "",
        frecuencia=int(audio.get("sample_rate", 0)) if audio else 0,
        canales=int(audio.get("channels", 0)) if audio else 0,
    )
