# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado con PyInstaller: un solo directorio con dos ejecutables.

  gbamedia      de consola: con argumentos hace de CLI, sin ellos abre la
                ventana
  gbamedia-gui  sin consola, para el acceso directo del escritorio

ffmpeg y ffprobe viajan **dentro**, en `bin/`, y se localizan por ruta relativa
al ejecutable. Nunca por PATH: depender del ffmpeg del sistema es la forma
segura de que la aplicacion se comporte distinto en cada maquina.
"""
import os
from pathlib import Path

RAIZ = Path(os.environ.get("GBAMEDIA_RAIZ", ".")).resolve()
BINARIOS = []
for nombre in ("ffmpeg", "ffprobe"):
    for candidato in (RAIZ / "bin" / nombre, RAIZ / "bin" / f"{nombre}.exe"):
        if candidato.is_file():
            BINARIOS.append((str(candidato), "bin"))

# Lo que no se usa y abulta: Qt trae medio mundo dentro.
FUERA = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
    "PySide6.QtOpenGL", "PySide6.QtSql", "PySide6.QtTest",
    "tkinter", "unittest", "pydoc", "doctest", "pytest",
]


def sobra(destino):
    """Peso muerto que Qt trae y que aqui no se usa."""
    d = destino.replace(os.sep, "/")
    return ("/translations/" in d          # 6,7 MB de traducciones de Qt
            or "/qml/" in d
            or "/wayland-graphics-integration-server/" in d)


def podar(lista):
    return [x for x in lista if not sobra(x[0])]


def analisis(script):
    return Analysis(
        [str(RAIZ / "packaging" / script)],
        pathex=[str(RAIZ / "src")],
        binaries=BINARIOS,
        datas=[],
        hiddenimports=[],
        excludes=FUERA,
        noarchive=False,
    )


a_cli = analisis("cli.py")
a_cli.binaries = podar(a_cli.binaries)
a_cli.datas = podar(a_cli.datas)
exe_cli = EXE(
    PYZ(a_cli.pure, a_cli.zipped_data),
    a_cli.scripts, [],
    exclude_binaries=True,
    name="gbamedia",
    console=True,
    disable_windowed_traceback=False,
)

a_gui = analisis("gui.py")
a_gui.binaries = podar(a_gui.binaries)
a_gui.datas = podar(a_gui.datas)
exe_gui = EXE(
    PYZ(a_gui.pure, a_gui.zipped_data),
    a_gui.scripts, [],
    exclude_binaries=True,
    name="gbamedia-gui",
    console=False,
    disable_windowed_traceback=False,
)

COLLECT(
    exe_cli, a_cli.binaries, a_cli.datas,
    exe_gui, a_gui.binaries, a_gui.datas,
    # En Windows quitar simbolos rompe mas de lo que ahorra.
    strip=os.name != "nt",
    upx=False,
    name="gbamedia",
)
