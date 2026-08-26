"""Nombres de la salida.

FilmPlay **no exige** el `Mnnnnn` del conversor original: su listado filtra por
extension (tabla `GBM/GBS/WAV/TXT` en `0x080C11F4`, INFORME_VIABILIDAD.md
§13.3) y lista cualquier nombre. Comprobado en mGBA: `CORTO.GBM` y
`FURRET~1.GBM` aparecen junto a `M00000.GBM` y se reproducen igual, con su
`.gbs` companero.

Lo que si impone la ROM es el **8.3**: lee entradas de directorio cortas, asi
que un nombre largo se ve en la consola como `FURRET~1.GBM`, que no dice nada.
Por eso el nombre por defecto es el del fichero de origen recortado a 8.3: lo
que se elige aqui es exactamente lo que se lee en la GBA.

El `Mnnnnn` sigue disponible (`numerar`), porque quien ya tiene la tarjeta
montada asi no quiere que le cambien los nombres.
"""
import re
from pathlib import Path
from threading import Lock

PATRON = re.compile(r"^M(\d{5})\.(gbm|gbs)$", re.IGNORECASE)
PLANTILLA = "M{:05d}"

# Lo que admite un nombre 8.3 sin necesitar entrada larga. Se excluyen a
# proposito el espacio y `~`: el espacio se lee mal en el listado y la
# virgulilla es lo que usa FAT para inventar alias.
VALIDOS = re.compile(r"[^A-Za-z0-9_$%'\-@!(){}^#&]")
TOPE = 8


class Numerador:
    """Reparte numeros libres de una carpeta, sin repetir.

    El numero se **reserva al encolar**, no al escribir, para que dos trabajos
    en paralelo no peleen por el mismo.
    """

    def __init__(self, carpeta):
        self.carpeta = Path(carpeta)
        self._usados = self._existentes()
        self._candado = Lock()

    def _existentes(self) -> set[int]:
        if not self.carpeta.is_dir():
            return set()
        return {int(m.group(1)) for f in self.carpeta.iterdir()
                if (m := PATRON.match(f.name))}

    def reservar(self, numero: int | None = None) -> str:
        with self._candado:
            if numero is None:
                numero = 0
                while numero in self._usados:
                    numero += 1
            elif numero in self._usados:
                raise ValueError(f"M{numero:05d} ya existe en {self.carpeta}")
            if not 0 <= numero <= 99999:
                raise ValueError("el numero no cabe en cinco cifras")
            self._usados.add(numero)
            return PLANTILLA.format(numero)


def sanear(nombre: str, defecto: str = "media") -> str:
    """Nombre de origen -> base 8.3 valida, en minusculas.

    En el disco se deja en minusculas porque es mas legible; en la GBA se vera
    en mayusculas de todos modos, que es como FAT guarda las entradas cortas.
    """
    base = VALIDOS.sub("", Path(nombre).stem)[:TOPE].strip("-_")
    return (base or defecto).lower()


def nombre_de_salida(origen, usados=()) -> str:
    """Nombre para un origen, sin pisar a otro trabajo del mismo lote.

    Que **si** pise lo que hubiera en la carpeta de antes es deliberado:
    convertir dos veces el mismo fichero tiene que reemplazar su salida, no
    dejar un `nombre (2)` al lado. Los choques que se resuelven aqui son entre
    origenes distintos que se recortan al mismo nombre.
    """
    base = sanear(origen)
    if base not in usados:
        return base
    for n in range(2, 1000):
        sufijo = str(n)
        candidato = base[:TOPE - len(sufijo)] + sufijo
        if candidato not in usados:
            return candidato
    raise ValueError(f"demasiados ficheros se llaman como {base!r}")
