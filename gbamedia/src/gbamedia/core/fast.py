"""Carga del nucleo en C, si esta.

La extension es opcional: sin ella todo funciona igual con la implementacion
de Python, que es la de referencia. `GBAMEDIA_PURO=1` la desactiva aunque este
compilada, que es como se comparan las dos en las pruebas.
"""
import os

from .gbs_tables import DELTA2, IDX3, IDX4, STEP

try:
    from . import _fast as nucleo
except ImportError:                     # sin compilador, o rueda sin construir
    nucleo = None

if nucleo is not None:
    # Las tablas se cargan desde aqui para que la version de C y la de Python
    # no puedan divergir.
    nucleo.pon_tablas(STEP, IDX4, IDX3, DELTA2)

if os.environ.get("GBAMEDIA_PURO"):
    nucleo = None


def hay_c() -> bool:
    return nucleo is not None
