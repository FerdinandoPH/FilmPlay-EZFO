"""Ajustes que no son de conversion sino de que ensena la aplicacion.

El modo de depuracion se activa dejando un fichero **DEBUG_ON** junto al
ejecutable. Es a proposito lo mas tonto posible: sin menus escondidos ni
configuracion que recordar, se crea el fichero y se vuelve a abrir.

Lo que esconde son los avisos de cadencia y sus controles. La medida de la
cadencia se equivoca en material real -llego a proponer acelerar un 700 %- y
un aviso equivocado manda a estropear un video que estaba bien, asi que por
defecto no se ensena.
"""
import os
import sys
from pathlib import Path

MARCA = "DEBUG_ON"


def carpeta_del_ejecutable() -> Path:
    """Donde se busca DEBUG_ON: al lado del ejecutable.

    Con el paquete de PyInstaller es la carpeta del `.exe`; en desarrollo, la
    raiz del proyecto. Misma logica que la de `media/ffmpeg.py`.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def modo_depuracion() -> bool:
    """No se cachea: basta crear el fichero y reabrir la aplicacion."""
    if os.environ.get("GBAMEDIA_DEBUG"):
        return True
    return (carpeta_del_ejecutable() / MARCA).exists()
