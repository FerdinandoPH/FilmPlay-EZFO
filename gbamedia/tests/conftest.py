"""Localiza los ficheros originales que sirven de referencia dorada.

Son los .gbm y .gbs generados con el conversor original en la maquina virtual
de Windows XP. No se copian al repositorio: se apunta a ellos con
GBAMEDIA_ORIGINALES, y si no estan las pruebas se saltan en vez de fallar.
"""
import os
import subprocess
from pathlib import Path

import pytest

# Las pruebas comparan contra los msgid, que son las cadenas en espanol: sin
# esto, en una maquina con locale en ingles (como los runners de CI) sale
# ingles y las que comparan texto fallan sin que el codigo este mal.
os.environ.setdefault("GBAMEDIA_IDIOMA", "es")

_DEFECTO = Path(__file__).resolve().parents[2] / "ezfode_sd" / "MEDIA"


def _raiz() -> Path:
    return Path(os.environ.get("GBAMEDIA_ORIGINALES", _DEFECTO))


@pytest.fixture(scope="session")
def originales() -> Path:
    raiz = _raiz()
    if not (raiz / "videos").is_dir():
        pytest.skip(f"no estan los ficheros originales en {raiz}")
    return raiz


@pytest.fixture(scope="session")
def videos(originales) -> Path:
    return originales / "videos"


@pytest.fixture(scope="session")
def hay_ffmpeg():
    from gbamedia.media import ffmpeg
    if not ffmpeg.disponible():
        pytest.skip("no hay ffmpeg/ffprobe localizables")
    return True


@pytest.fixture(scope="session")
def wav_prueba(hay_ffmpeg, tmp_path_factory) -> Path:
    """Un .wav suelto, para las pruebas de convertir musica.

    Se sintetiza con ffmpeg en vez de traer un fichero al repositorio: lo que
    prueban es que un audio cualquiera se convierte, no un audio concreto, y
    asi no hace falta material con dueno ni que nadie se traiga nada aparte.
    """
    from gbamedia.media import ffmpeg

    destino = tmp_path_factory.mktemp("audio") / "prueba.wav"
    subprocess.run(
        [str(ffmpeg.ruta("ffmpeg")), "-v", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=6:sample_rate=22050",
         "-ac", "2", "-c:a", "pcm_s16le", str(destino)],
        check=True, capture_output=True)
    return destino


@pytest.fixture(scope="session")
def fuentes() -> Path:
    """Los mp4 de los que salieron los .gbm originales."""
    raiz = Path(os.environ.get("GBAMEDIA_FUENTES",
                               _DEFECTO.parents[1] / "videos"))
    if not raiz.is_dir():
        pytest.skip(f"no estan los videos de origen en {raiz}")
    return raiz
