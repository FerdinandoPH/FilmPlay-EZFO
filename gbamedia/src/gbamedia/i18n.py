"""Traduccion de la interfaz y de la linea de ordenes.

Los **msgid son las cadenas en espanol**, que es el idioma en el que esta
escrito el proyecto entero: asi no hay que reescribir lo que ya funciona y el
catalogo ingles es lo unico que se mantiene aparte. El catalogo es un modulo de
Python y no un fichero de datos, para que PyInstaller lo empaquete solo.

    from ..i18n import _
    _("Convertir todo")
    _("Fichero {n} de {total}", n=2, total=7)

Sin traduccion, `_` devuelve el msgid tal cual, asi que una cadena sin traducir
sale en espanol y nunca en blanco.
"""
import locale
import os

ESPANOL = "es"
INGLES = "en"
IDIOMAS = (ESPANOL, INGLES)

NOMBRES = {ESPANOL: "Español", INGLES: "English"}

_actual = ESPANOL
_catalogo: dict[str, str] = {}


def _cargar(idioma: str) -> dict:
    if idioma == INGLES:
        from .languages.en import CATALOGO
        return CATALOGO
    return {}


def usar(idioma: str) -> str:
    """Fija el idioma. Devuelve el que ha quedado puesto."""
    global _actual, _catalogo
    idioma = (idioma or "").lower()[:2]
    if idioma not in IDIOMAS:
        idioma = ESPANOL
    _actual, _catalogo = idioma, _cargar(idioma)
    return _actual


def idioma() -> str:
    return _actual


def del_sistema() -> str:
    """El idioma que toca si nadie ha dicho nada.

    Espanol para quien tenga el sistema en espanol; para el resto, ingles: es
    lo unico que se puede suponer que se entiende mas alla.
    """
    forzado = os.environ.get("GBAMEDIA_IDIOMA")
    if forzado:
        return forzado[:2].lower()
    try:
        etiqueta = locale.getlocale()[0] or ""
    except ValueError:                      # locale rara del sistema
        etiqueta = ""
    if not etiqueta:
        etiqueta = os.environ.get("LANG", "")
    return ESPANOL if etiqueta.lower().startswith("es") else INGLES


def _(texto: str, **campos) -> str:
    """El texto en el idioma en curso, con sus huecos rellenos."""
    traducido = _catalogo.get(texto, texto)
    return traducido.format(**campos) if campos else traducido


usar(del_sistema())
