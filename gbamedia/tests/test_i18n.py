"""Que no se quede media aplicacion sin traducir.

La prueba que de verdad protege es la de cobertura: saca del codigo **todas**
las llamadas a `_()` con una cadena literal y exige que esten en el catalogo.
Sin ella, anadir un boton nuevo deja media ventana en espanol sin que nadie se
entere hasta que la ve un usuario ingles.
"""
import ast
from pathlib import Path

import pytest

from gbamedia import i18n
from gbamedia.languages.en import CATALOGO

RAIZ = Path(i18n.__file__).parent

# Cadenas que se traducen con una variable (`_(titulo)`, `_(self.estado)`) y
# que por tanto no salen del analisis del codigo.
DINAMICAS = {
    "Imagen", "Calidad", "Audio", "Cadencia", "Velocidad", "Recorte y salida",
    "Alta", "Estandar", "Compresion",
    "hecho", "fallido", "convirtiendo", "pendiente",
    "video", "musica",
}


def _msgids() -> dict:
    """Los literales de todas las llamadas a `_()` del paquete."""
    fuera = {}
    for fichero in sorted(RAIZ.rglob("*.py")):
        if fichero.parent.name == "languages":
            continue
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        for nodo in ast.walk(arbol):
            if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                    and nodo.func.id == "_" and nodo.args
                    and isinstance(nodo.args[0], ast.Constant)
                    and isinstance(nodo.args[0].value, str)):
                fuera.setdefault(nodo.args[0].value, fichero.name)
    return fuera


def test_todas_las_cadenas_estan_en_el_catalogo():
    faltan = {m: f for m, f in _msgids().items() if m not in CATALOGO}
    assert not faltan, "sin traducir: " + repr(sorted(faltan))


def test_las_cadenas_dinamicas_tambien():
    faltan = [m for m in DINAMICAS if m not in CATALOGO]
    assert not faltan, f"sin traducir: {faltan}"


def test_los_huecos_cuadran():
    """Una traduccion con otros huecos revienta al formatear, y encima solo en
    el idioma que casi nadie prueba."""
    import re
    hueco = re.compile(r"\{(\w+)")
    for msgid, traduccion in CATALOGO.items():
        assert set(hueco.findall(msgid)) == set(hueco.findall(traduccion)), \
            f"huecos distintos en {msgid!r}"


def test_el_catalogo_no_tiene_sobras():
    """Una entrada que ya no usa nadie es ruido que se copia al siguiente
    idioma."""
    usadas = set(_msgids()) | DINAMICAS
    sobran = sorted(set(CATALOGO) - usadas)
    assert not sobran, f"sobran del catalogo: {sobran}"


@pytest.fixture
def espanol():
    anterior = i18n.idioma()
    yield
    i18n.usar(anterior)


def test_cambiar_de_idioma(espanol):
    i18n.usar("es")
    assert i18n._("Convertir todo") == "Convertir todo"
    i18n.usar("en")
    assert i18n._("Convertir todo") == "Convert all"
    assert i18n._("{n} ficheros", n=3) == "3 files"
    i18n.usar("fr")
    assert i18n.idioma() == "es", "lo que no se conoce cae en espanol"


def test_una_cadena_sin_traducir_sale_en_espanol(espanol):
    i18n.usar("en")
    assert i18n._("esto no esta en el catalogo") == "esto no esta en el catalogo"
