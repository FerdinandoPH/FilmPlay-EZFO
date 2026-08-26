"""Localiza los ficheros originales que sirven de referencia dorada.

Son los .gbm y .gbs generados con el conversor original en la maquina virtual
de Windows XP. No se copian al repositorio: se apunta a ellos con
GBAMEDIA_ORIGINALES, y si no estan las pruebas se saltan en vez de fallar.
"""
import os
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
def re_gbamedia() -> Path:
    """Los ficheros de re_gbamedia/, dentro del propio paquete."""
    return Path(__file__).resolve().parents[1] / "re_gbamedia"


@pytest.fixture(scope="session")
def fuentes() -> Path:
    """Los mp4 de los que salieron los .gbm originales."""
    raiz = Path(os.environ.get("GBAMEDIA_FUENTES",
                               _DEFECTO.parents[1] / "videos"))
    if not raiz.is_dir():
        pytest.skip(f"no estan los videos de origen en {raiz}")
    return raiz
