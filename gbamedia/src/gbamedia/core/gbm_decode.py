"""Decodificador del formato .gbm, transcrito del decodificador de la ROM
FilmPlay.gba (0x08120000-0x08122e9c).

El codec es un arbol binario de particion sobre bloques de 8x8. El recorrido
del arbol esta separado del pintado mediante un "sumidero" (`Sumidero`), de
modo que se puede validar un fichero entero sin pagar el coste de mover
pixeles, o volcar imagenes cuando hace falta.

Validado sobre los 6510 frames de los siete .gbm originales (GBM_FORMAT.md).
"""
import struct
from dataclasses import dataclass, field

from .containers import (TAM_CABECERA, MAGICO_VIDEO, FormatoInvalido,
                         leer_cabecera, trocear_frames)
from .mvtable import ANCHO, ALTO, PASO, TABLA
from .fast import nucleo

BLOQUES_X = ANCHO // 8      # 30
BLOQUES_Y = ALTO // 8       # 20
NUM_BLOQUES = BLOQUES_X * BLOQUES_Y

# Tipos de hoja, para estadisticas y para el codificador
COPIA = "copia"
COPIA_VECTOR = "copia_vector"
VECTOR_COLOR = "vector_color"
SOLIDO = "solido"
DOS_COLORES = "dos_colores"


class LectorBits:
    """32 bits por palabra u32 little endian, MSB primero.

    Los bits sobrantes de la ultima palabra son relleno y siempre son < 32.
    """

    __slots__ = ("d", "p", "r", "n")

    def __init__(self, datos: bytes):
        self.d = datos
        self.p = 0
        self.r = 0
        self.n = 0

    def bit(self) -> int:
        if self.n == 0:
            if self.p + 4 > len(self.d):
                raise EOFError("bitstream agotado")
            self.r, = struct.unpack_from("<I", self.d, self.p)
            self.p += 4
            self.n = 32
        c = (self.r >> 31) & 1
        self.r = (self.r << 1) & 0xFFFFFFFF
        self.n -= 1
        return c

    @property
    def sobran(self) -> int:
        """Bits sin leer: los de la palabra en curso mas los no cargados."""
        return (len(self.d) - self.p) * 8 + self.n


class Sumidero:
    """Recibe las hojas del arbol. La version base no hace nada."""

    def copiar(self, destino: int, origen: int, w: int, h: int,
               delta: int | None = None) -> None:
        pass

    def rellenar(self, destino: int, w: int, h: int, color: int) -> None:
        pass

    def pareja(self, destino: int, w: int, h: int, c1: int, c2: int) -> None:
        pass

    def frame_terminado(self) -> None:
        pass


class SumideroBuffer(Sumidero):
    """Pinta sobre un framebuffer BGR555 de 240x160."""

    def __init__(self):
        self.actual = bytearray(ANCHO * ALTO * 2)
        self.anterior = bytearray(ANCHO * ALTO * 2)

    def copiar(self, destino, origen, w, h, delta=None):
        # Un vector que se sale del buffer no se da en ficheros reales (la ROM
        # leeria basura y el codificador no los emite); aqui las reglas de
        # rebanado de Python hacen lo que hagan y el nucleo en C se salta la
        # fila. Solo se distinguen con un fichero corrupto.
        act, ant = self.actual, self.anterior
        for y in range(h):
            s = origen + y * PASO
            o = destino + y * PASO
            if delta is None:
                act[o:o + w * 2] = ant[s:s + w * 2]
            else:
                for x in range(0, w * 2, 2):
                    v, = struct.unpack_from("<H", ant, s + x)
                    # La ROM empaqueta el color en las dos mitades de una
                    # palabra y suma de 32 en 32 bits, de modo que el acarreo
                    # entre componentes no se recorta.
                    struct.pack_into("<H", act, o + x, (v + delta) & 0xFFFF)

    def rellenar(self, destino, w, h, color):
        fila = struct.pack("<H", color) * w
        for y in range(h):
            o = destino + y * PASO
            self.actual[o:o + w * 2] = fila

    def pareja(self, destino, w, h, c1, c2):
        struct.pack_into("<H", self.actual, destino, c1)
        struct.pack_into("<H", self.actual, destino + (2 if w == 2 else PASO), c2)

    def frame_terminado(self):
        self.actual, self.anterior = self.anterior, self.actual

    @property
    def frame(self) -> bytes:
        """El ultimo frame completo (tras frame_terminado)."""
        return bytes(self.anterior)


@dataclass
class EstadisticasFrame:
    indice: int
    tam_bitstream: int
    tam_colores: int
    tam_vectores: int
    bits_sobrantes: int = 0
    colores_usados: int = 0
    vectores_usados: int = 0
    hojas: dict = field(default_factory=dict)

    @property
    def colores_exactos(self) -> bool:
        return self.colores_usados * 2 == self.tam_colores

    @property
    def total_hojas(self) -> int:
        return sum(self.hojas.values())


class Frame:
    """Los tres flujos del payload de un frame."""

    __slots__ = ("nb", "nc", "bits", "col", "mv", "ci", "mi", "hojas")

    def __init__(self, payload: bytes):
        if len(payload) < 4:
            raise FormatoInvalido("payload de frame menor que su cabecera")
        self.nb, self.nc = struct.unpack_from("<HH", payload, 0)
        fin_bits = 4 + self.nb
        fin_col = fin_bits + self.nc
        if fin_col > len(payload):
            raise FormatoInvalido("los flujos no caben en el payload")
        self.bits = LectorBits(payload[4:fin_bits])
        self.col = payload[fin_bits:fin_col]
        self.mv = payload[fin_col:]
        self.ci = 0
        self.mi = 0
        self.hojas: dict[str, int] = {}

    def color(self) -> int:
        c, = struct.unpack_from("<H", self.col, self.ci)
        self.ci += 2
        return c

    def vector(self) -> int:
        v = TABLA[self.mv[self.mi]]
        self.mi += 1
        return v

    def anota(self, tipo: str) -> None:
        self.hojas[tipo] = self.hojas.get(tipo, 0) + 1


def _nodo(f: Frame, s: Sumidero, off: int, w: int, h: int) -> None:
    """Un nodo del arbol. off = desplazamiento en bytes en el framebuffer."""
    if f.bits.bit() == 0:
        if f.bits.bit() == 0:
            f.anota(COPIA)
            s.copiar(off, off, w, h)
        else:
            f.anota(COPIA_VECTOR)
            s.copiar(off, off + f.vector(), w, h)
        return

    if f.bits.bit() == 0:
        if w * h == 2:
            # hoja de 2 px: aqui el bit significa "vector + suma de color"
            f.anota(VECTOR_COLOR)
            s.copiar(off, off + f.vector(), w, h, f.color())
            return
        # El bit de direccion solo existe si ambas dimensiones son > 1: una
        # fila o una columna solo se puede partir de una manera. Sin esto el
        # bitstream se desincroniza al segundo bloque.
        if h == 1:
            vertical = False
        elif w == 1:
            vertical = True
        else:
            vertical = f.bits.bit() == 0
        if vertical:
            h2 = h // 2
            _nodo(f, s, off, w, h2)
            _nodo(f, s, off + h2 * PASO, w, h2)
        else:
            w2 = w // 2
            _nodo(f, s, off, w2, h)
            _nodo(f, s, off + w2 * 2, w2, h)
        return

    if f.bits.bit() == 0:
        if w * h == 2:
            f.anota(SOLIDO)
            s.rellenar(off, w, h, f.color())
        else:
            f.anota(VECTOR_COLOR)
            s.copiar(off, off + f.vector(), w, h, f.color())
        return

    if w * h == 2:
        f.anota(DOS_COLORES)
        s.pareja(off, w, h, f.color(), f.color())
    else:
        f.anota(SOLIDO)
        s.rellenar(off, w, h, f.color())


def decodificar_frame(payload: bytes, sumidero: Sumidero,
                      indice: int = 0) -> EstadisticasFrame:
    if nucleo is not None and type(sumidero) is SumideroBuffer:
        # El nucleo en C pinta y cuenta a la vez; el sumidero de aqui solo
        # aporta el par de buffers y el intercambio.
        nb, nc, nmv, sobran, colores, vectores, hojas = nucleo.decodifica_frame(
            payload, sumidero.actual, sumidero.anterior)
        sumidero.frame_terminado()
        return EstadisticasFrame(
            indice=indice, tam_bitstream=nb, tam_colores=nc, tam_vectores=nmv,
            bits_sobrantes=sobran, colores_usados=colores,
            vectores_usados=vectores, hojas=hojas)

    f = Frame(payload)
    for by in range(BLOQUES_Y):
        for bx in range(BLOQUES_X):
            _nodo(f, sumidero, (by * 8 * ANCHO + bx * 8) * 2, 8, 8)
    sumidero.frame_terminado()
    return EstadisticasFrame(
        indice=indice, tam_bitstream=f.nb, tam_colores=f.nc,
        tam_vectores=len(f.mv), bits_sobrantes=f.bits.sobran,
        colores_usados=f.ci // 2, vectores_usados=f.mi, hojas=f.hojas)


def decodificar(datos: bytes, sumidero: Sumidero | None = None,
                limite: int | None = None):
    """Itera (EstadisticasFrame) sobre un .gbm entero.

    Si no se pasa sumidero se usa el vacio: valida la sintaxis y el consumo de
    los flujos sin mover un solo pixel.
    """
    cab = leer_cabecera(datos)
    if not cab.es_video:
        raise FormatoInvalido("no es un .gbm")
    if sumidero is None:
        # Con el nucleo en C pintar sale gratis, asi que se usa el sumidero de
        # verdad: valida lo mismo y ademas deja el frame a mano.
        sumidero = SumideroBuffer() if nucleo is not None else Sumidero()
    for n, payload in enumerate(trocear_frames(datos)):
        if limite is not None and n >= limite:
            return
        yield decodificar_frame(payload, sumidero, n)
