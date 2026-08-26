"""Compilacion de la extension en C.

Es **opcional**: si no hay compilador, el paquete se instala igual y el
codificador usa la implementacion de Python, que hace lo mismo mas despacio.
La variable GBAMEDIA_PURO=1 la desactiva aunque este compilada.
"""
import os

from setuptools import Extension, setup

# MSVC no entiende -O3 (y ya compila con /O2 por defecto); avisa y sigue, pero
# el aviso confunde a quien construye el paquete de Windows.
OPCIONES = [] if os.name == "nt" else ["-O3"]

setup(ext_modules=[
    Extension(
        "gbamedia.core._fast",
        sources=["src/gbamedia/core/_fast.c"],
        extra_compile_args=OPCIONES,
        optional=True,
    ),
])
