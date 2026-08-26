"""Localizacion y llamada a ffmpeg/ffprobe.

En el paquete distribuido los dos binarios viajan **dentro** y se buscan por
ruta relativa al ejecutable, nunca por PATH: depender del ffmpeg del sistema es
la forma segura de que la aplicacion se comporte distinto en cada maquina.
Durante el desarrollo se admite ademas `GBAMEDIA_FFMPEG` y, como ultimo
recurso, el del sistema.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


class FaltaFfmpeg(RuntimeError):
    pass


class ErrorFfmpeg(RuntimeError):
    pass


def _candidatos(nombre: str):
    ejecutable = nombre + (".exe" if os.name == "nt" else "")

    entorno = os.environ.get("GBAMEDIA_FFMPEG")
    if entorno:
        yield Path(entorno) / ejecutable
        yield Path(entorno)

    if getattr(sys, "frozen", False):
        # En un paquete de un directorio, _MEIPASS es `_internal/`, no la
        # carpeta del ejecutable: hay que mirar las dos.
        yield Path(sys.executable).resolve().parent / "bin" / ejecutable
        yield Path(sys._MEIPASS) / "bin" / ejecutable
    else:
        raiz = Path(__file__).resolve().parents[3]
        yield raiz / "bin" / ejecutable
        yield raiz.parent / "tools" / ejecutable

    del_sistema = shutil.which(nombre)
    if del_sistema:
        yield Path(del_sistema)


def ruta(nombre: str = "ffmpeg") -> Path:
    for c in _candidatos(nombre):
        if c.is_file() and os.access(c, os.X_OK):
            return c
    raise FaltaFfmpeg(
        f"no se encuentra {nombre}: ponlo en bin/ junto al ejecutable o "
        f"apunta GBAMEDIA_FFMPEG a su carpeta")


def disponible() -> bool:
    try:
        ruta("ffmpeg")
        ruta("ffprobe")
        return True
    except FaltaFfmpeg:
        return False


# En Windows, cada proceso hijo de una aplicacion sin consola abre una ventana
# negra que parpadea: una por fichero al sondear, y otra por conversion. Ademas
# de feo, crear la consola cuesta tiempo.
SIN_CONSOLA = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})


def sondear_crudo(fichero) -> dict:
    orden = [str(ruta("ffprobe")), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(fichero)]
    p = subprocess.run(orden, capture_output=True, **SIN_CONSOLA)
    if p.returncode != 0:
        raise ErrorFfmpeg(p.stderr.decode("utf-8", "replace").strip())
    return json.loads(p.stdout)


def abrir(argumentos: list[str]) -> subprocess.Popen:
    """Lanza ffmpeg con la salida cruda por stdout."""
    orden = [str(ruta("ffmpeg")), "-v", "error", "-nostdin"] + argumentos
    return subprocess.Popen(orden, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **SIN_CONSOLA)


def ejecutar(argumentos: list[str]) -> bytes:
    p = abrir(argumentos)
    salida, error = p.communicate()
    if p.returncode != 0:
        raise ErrorFfmpeg(error.decode("utf-8", "replace").strip())
    return salida
