"""Codificador del formato .gbm.

Reconstruye la logica del codificador original (`Gbamvico.dll`) tal como se
dedujo en GBM_FORMAT.md: un arbol binario de particion sobre bloques de 8x8
en el que una hoja se acepta si **ninguna diferencia supera la tolerancia** de
su banda de tamano, y el frame se reintenta subiendo la tolerancia hasta caber
en `FrameSize`.

La igualdad byte a byte con el original no es alcanzable (sus heuristicas
exactas no se conocen del todo), asi que el criterio es otro: que el fichero
producido lo lea el decodificador de la ROM consumiendo los flujos exactos y
que la calidad no sea peor que la del original.

Nota sobre los vectores: el desplazamiento es un offset **lineal** en el
framebuffer (`dy*480 + dx*2` bytes), no un recorte bidimensional. Cerca de los
bordes eso lee la fila de al lado, que es justo lo que hace la ROM; lo que no
se permite nunca es salir del buffer.

Nota sobre la velocidad: todo lo que el recorrido del arbol necesita saber
depende del frame, no de la tolerancia, asi que se precalcula **una vez por
frame y vectorizado** en `Analisis` (las quince formas de golpe con `reshape`)
y el nodo solo hace lecturas escalares. El bucle de control de tamano repite
unicamente el recorrido.
"""
from dataclasses import dataclass, field

import numpy as np

from .bitwriter import EscritorBits
from .containers import MAGICO_VIDEO, MODO_VIDEO, escribir_cabecera
from .mvtable import ALTO, ANCHO
from .fast import nucleo
from . import mvtable

PIXELES = ANCHO * ALTO
BLOQUES_X = ANCHO // 8
BLOQUES_Y = ALTO // 8
BLOQUES = BLOQUES_Y * BLOQUES_X

# Todas las formas del arbol, de mayor a menor
FORMAS = [(w, h) for w in (8, 4, 2, 1) for h in (8, 4, 2, 1)
          if not (w == 1 and h == 1)]

ERROR_INVALIDO = 255      # marca de pixel fuera del buffer en la busqueda

# Desplazamiento lineal en pixeles de cada uno de los 256 vectores
DESPLAZAMIENTOS = np.array(
    [mvtable.componentes(i)[1] * ANCHO + mvtable.componentes(i)[0]
     for i in range(256)], dtype=np.int32)
VECTOR_NULO = mvtable.indice(0, 0)

BUSQUEDAS = ("rapida", "exhaustiva")
CANDIDATOS = 4            # finalistas de la criba que se miden exactos


# --- presets ------------------------------------------------------------

@dataclass(frozen=True)
class Calidad:
    nombre: str
    # Una tolerancia por banda de tamano de bloque: >=64, 32, 16, 8, <=4 px
    tolerancias: tuple[int, int, int, int, int]
    vectores: bool
    pasadas: int
    tope: int              # tope duro de bytes por frame
    frame_size: int        # objetivo de bytes por frame
    modo_audio: int        # el .gbs companero, como en el conversor original
    # El original sube la tolerancia de 24 en 24 sobre componentes de 8 bits;
    # aqui se trabaja en las 5 de BGR555, asi que el paso equivalente es 3.
    # Se deja en 1 porque un salto de 3 en 32 niveles ya se ve.
    paso: int = 1
    busqueda: str = "rapida"


CALIDADES = {
    "alta": Calidad("alta", (0, 0, 0, 0, 0), False, 6, 0x8000, 8192, 0),
    "estandar": Calidad("estandar", (1, 1, 2, 2, 3), True, 8, 0x4000, 8192, 2),
    "compresion": Calidad("compresion", (2, 3, 4, 5, 6), True, 10, 0x4000,
                          4096, 4),
}


def banda(w: int, h: int) -> int:
    area = w * h
    if area >= 64:
        return 0
    if area == 32:
        return 1
    if area == 16:
        return 2
    if area == 8:
        return 3
    return 4


# --- color --------------------------------------------------------------

def a_bgr555(rgb: np.ndarray) -> np.ndarray:
    """(H,W,3) uint8 en 0..255 -> (H,W) uint16 BGR555."""
    r = (rgb[..., 0] >> 3).astype(np.uint16)
    g = (rgb[..., 1] >> 3).astype(np.uint16)
    b = (rgb[..., 2] >> 3).astype(np.uint16)
    return (b << 10) | (g << 5) | r


def componentes(v: np.ndarray) -> np.ndarray:
    """(H,W) uint16 BGR555 -> (H,W,3) int16 con cada componente en 0..31."""
    return np.stack([v & 31, (v >> 5) & 31, (v >> 10) & 31],
                    axis=-1).astype(np.int16)


def a_rgb888(v: np.ndarray) -> np.ndarray:
    c = componentes(v).astype(np.uint8)
    x = (c << 3) | (c >> 2)
    return x


def _error_contra(bgr: np.ndarray, obj_c: np.ndarray) -> np.ndarray:
    """Maximo por componente de |bgr - obj|, sin montar el stack de `componentes`."""
    e = np.abs((bgr & 31).astype(np.int16) - obj_c[..., 0])
    np.maximum(e, np.abs(((bgr >> 5) & 31).astype(np.int16) - obj_c[..., 1]),
               out=e)
    np.maximum(e, np.abs(((bgr >> 10) & 31).astype(np.int16) - obj_c[..., 2]),
               out=e)
    return e


# --- reducciones por forma ---------------------------------------------

ORDEN = sorted(FORMAS, key=lambda f: (f[0] * f[1], f))


def _padre(w: int, h: int) -> tuple[int, int]:
    """De que forma sale esta, partiendo por la mitad la dimension mayor."""
    return (w // 2, h) if w > 1 else (w, h // 2)


def _escalar(tabla: dict, func) -> dict:
    """Aplica `func` (max o min) a cada forma partiendo de la anterior.

    Las quince formas salen unas de otras: (4,8) es el maximo por parejas de
    (2,8). Encadenarlas cuesta dos pasadas sobre el frame en total en vez de
    quince, que era lo que costaba reducir cada forma desde los pixeles.
    """
    for w, h in ORDEN:
        p = tabla[_padre(w, h)]
        alto, ancho = p.shape[0], p.shape[1]
        resto = p.shape[2:]
        if _padre(w, h)[0] != w:        # dos columnas en una
            tabla[(w, h)] = func(p.reshape(alto, ancho // 2, 2, *resto), axis=2)
        else:                           # dos filas en una
            tabla[(w, h)] = func(p.reshape(alto // 2, 2, ancho, *resto), axis=1)
    return {f: tabla[f] for f in FORMAS}


def _max_por_forma(mapa: np.ndarray) -> dict:
    """Maximo de `mapa` (H,W) sobre cada rectangulo alineado de cada forma.

    Todos los rectangulos del arbol estan alineados a su propio tamano, porque
    salen de partir por la mitad un bloque de 8x8 alineado.
    """
    return _escalar({(1, 1): mapa}, np.max)


def _min_max_por_forma(canales: np.ndarray) -> tuple[dict, dict]:
    """Minimo y maximo por componente sobre cada rectangulo de cada forma."""
    return (_escalar({(1, 1): canales}, np.min),
            _escalar({(1, 1): canales}, np.max))


def _listas(tablas: dict) -> dict:
    """Pasa las tablas por forma a listas anidadas.

    El nodo hace millones de lecturas escalares al ano: sacar un entero de una
    lista de Python cuesta una fraccion de lo que cuesta sacarlo de un array de
    numpy, y el `tolist` se paga una sola vez por frame.
    """
    return {f: t.tolist() for f, t in tablas.items()}


# --- busqueda de movimiento --------------------------------------------

def _rejilla_de_bloques(donde: np.ndarray) -> np.ndarray:
    """Indices planos de los 64 pixeles de cada bloque, en filas de 64."""
    by, bx = np.divmod(donde, BLOQUES_X)
    base = (by * 8 * ANCHO + bx * 8)[:, None]
    dentro = (np.arange(8)[:, None] * ANCHO + np.arange(8)[None, :]).ravel()
    return (base + dentro[None, :]).astype(np.int32)


def _medir(pix, ref_c, obj_bloque, indices):
    """Error exacto (maximo por componente) de un vector por bloque."""
    origen = pix + DESPLAZAMIENTOS[indices][:, None]
    fuera = (origen < 0) | (origen >= PIXELES)
    err = np.abs(ref_c[np.clip(origen, 0, PIXELES - 1)]
                 - obj_bloque).max(axis=2)
    if fuera.any():
        err[fuera] = ERROR_INVALIDO
    return err


def _resultado(idx_bloque, err_bloque, pix, donde, referencia):
    """Empaqueta la salida comun de las dos busquedas."""
    ref_plano = referencia.ravel()
    ref_mov = ref_plano.copy()
    err = np.full(PIXELES, ERROR_INVALIDO, dtype=np.int16)
    if donde.size:
        origen = pix + DESPLAZAMIENTOS[idx_bloque[donde]][:, None]
        seguro = np.clip(origen, 0, PIXELES - 1)
        ref_mov[pix.ravel()] = ref_plano[seguro.ravel()]
        err[pix.ravel()] = err_bloque.ravel()
    return (idx_bloque.reshape(BLOQUES_Y, BLOQUES_X),
            ref_mov.reshape(ALTO, ANCHO), err.reshape(ALTO, ANCHO))


def buscar_vectores(objetivo, referencia, activos=None):
    """Mejor vector por bloque de 8x8, por busqueda exhaustiva de los 256.

    Es la referencia contra la que se valida la busqueda rapida. `activos`
    marca los bloques que hace falta mirar: si la copia directa ya cae dentro
    de la tolerancia, el nodo de 8x8 se resuelve como copia y no se llega a
    bajar del bloque, asi que buscarle vector es trabajo tirado.

    Se trabaja sobre el buffer aplanado porque el desplazamiento de la ROM es
    lineal: cerca de los bordes un vector lee la fila de al lado. Lo unico que
    se descarta es salir del buffer.

    Devuelve (indices (20,30) uint8, referencia movida (H,W) uint16,
    error movido (H,W) int16).
    """
    obj_c = componentes(objetivo).reshape(PIXELES, 3)
    ref_c = componentes(referencia).reshape(PIXELES, 3)
    idx_bloque = np.full(BLOQUES, VECTOR_NULO, dtype=np.uint8)

    if activos is None:
        activos = np.ones((BLOQUES_Y, BLOQUES_X), dtype=bool)
    donde = np.flatnonzero(activos.ravel())
    if donde.size == 0:
        return _resultado(idx_bloque, None, None, donde, referencia)

    pix = _rejilla_de_bloques(donde)
    obj_bloque = obj_c[pix]                              # (nb, 64, 3)
    mejor = np.full(donde.size, 1 << 62, dtype=np.int64)
    mejor_i = np.full(donde.size, VECTOR_NULO, dtype=np.uint8)

    for i in range(256):
        err = _medir(pix, ref_c, obj_bloque,
                     np.full(donde.size, i, dtype=np.uint8))
        # El maximo decide; la suma desempata entre vectores igual de buenos.
        punto = (err.max(axis=1).astype(np.int64) << 20) + err.sum(axis=1)
        mejora = punto < mejor
        mejor = np.where(mejora, punto, mejor)
        mejor_i[mejora] = i

    idx_bloque[donde] = mejor_i
    err = _medir(pix, ref_c, obj_bloque, mejor_i).astype(np.int16)
    return _resultado(idx_bloque, err, pix, donde, referencia)


def _criba(objetivo, referencia):
    """Puntua los 256 vectores por bloque con una metrica barata.

    El gather de la busqueda exhaustiva es lo que la hace lenta, y no mejora
    ni agrupando los vectores ni recorriendo el frame entero. Lo que si sale
    a cuenta es cribar con una sola magnitud por pixel (`r + 2g + b`, que cabe
    de sobra en int16) sobre un buffer con relleno, de modo que desplazar el
    vector sea una rebanada contigua en vez de un gather, y dejar la metrica
    buena para los finalistas.

    Devuelve (CANDIDATOS, BLOQUES) con los indices de vector finalistas.
    """
    obj_c = componentes(objetivo).reshape(PIXELES, 3).astype(np.int16)
    ref_c = componentes(referencia).reshape(PIXELES, 3).astype(np.int16)
    luz_obj = obj_c[:, 0] + 2 * obj_c[:, 1] + obj_c[:, 2]
    luz_ref = ref_c[:, 0] + 2 * ref_c[:, 1] + ref_c[:, 2]

    # Relleno por los dos lados para poder desplazar sin salirse. El relleno
    # es un valor imposible, asi que un vector que se sale nunca gana.
    margen = 8 * ANCHO + 8
    con_borde = np.full(PIXELES + 2 * margen, 1000, dtype=np.int16)
    con_borde[margen:margen + PIXELES] = luz_ref

    puntos = np.empty((256, BLOQUES), dtype=np.int16)
    hueco = np.empty(PIXELES, dtype=np.int16)
    for i, o in enumerate(DESPLAZAMIENTOS):
        np.subtract(con_borde[margen + o:margen + o + PIXELES], luz_obj,
                    out=hueco)
        np.abs(hueco, out=hueco)
        puntos[i] = hueco.reshape(BLOQUES_Y, 8, BLOQUES_X, 8).max(
            axis=(1, 3)).ravel()
    # Orden estable: en empate gana el vector de indice menor. Importa porque
    # el nucleo en C tiene que elegir los mismos finalistas para dar el mismo
    # fichero, y `argpartition` no promete nada sobre los empates.
    return np.argsort(puntos, axis=0, kind="stable")[:CANDIDATOS]


def buscar_vectores_rapido(objetivo, referencia, activos=None):
    """Criba barata sobre los 256 y metrica exacta sobre los finalistas."""
    obj_c = componentes(objetivo).reshape(PIXELES, 3)
    ref_c = componentes(referencia).reshape(PIXELES, 3)
    idx_bloque = np.full(BLOQUES, VECTOR_NULO, dtype=np.uint8)

    if activos is None:
        activos = np.ones((BLOQUES_Y, BLOQUES_X), dtype=bool)
    donde = np.flatnonzero(activos.ravel())
    if donde.size == 0:
        return _resultado(idx_bloque, None, None, donde, referencia)

    finalistas = _criba(objetivo, referencia)
    pix = _rejilla_de_bloques(donde)
    obj_bloque = obj_c[pix]
    mejor = np.full(donde.size, 1 << 62, dtype=np.int64)
    mejor_i = np.full(donde.size, VECTOR_NULO, dtype=np.uint8)

    for k in range(CANDIDATOS):
        cand = finalistas[k, donde].astype(np.uint8)
        err = _medir(pix, ref_c, obj_bloque, cand)
        punto = (err.max(axis=1).astype(np.int64) << 20) + err.sum(axis=1)
        mejora = punto < mejor
        mejor = np.where(mejora, punto, mejor)
        mejor_i[mejora] = cand[mejora]

    idx_bloque[donde] = mejor_i
    err = _medir(pix, ref_c, obj_bloque, mejor_i).astype(np.int16)
    return _resultado(idx_bloque, err, pix, donde, referencia)


def buscar(objetivo, referencia, activos=None, modo: str = "rapida"):
    if modo not in BUSQUEDAS:
        raise ValueError(f"busqueda desconocida: {modo!r}")
    if modo == "exhaustiva":
        return buscar_vectores(objetivo, referencia, activos)
    return buscar_vectores_rapido(objetivo, referencia, activos)


# --- analisis de un frame ----------------------------------------------

class Analisis:
    """Lo que el arbol necesita saber del frame, precalculado por forma.

    Nada de esto depende de la tolerancia, asi que se calcula una sola vez
    aunque el control de tamano tenga que repetir el recorrido varias veces.
    """

    __slots__ = ("objetivo", "referencia", "usa_vectores", "idx_vector",
                 "ref_vector", "recon_delta", "max_copia", "max_vector",
                 "err_solido", "color_solido", "err_delta", "delta",
                 "dispersion")

    def __init__(self, objetivo, referencia, usa_vectores, movimiento):
        self.objetivo = objetivo
        self.referencia = referencia
        self.usa_vectores = usa_vectores
        self.idx_vector, self.ref_vector, err_mov = movimiento

        obj_c = componentes(objetivo)
        self.max_copia = _listas(_max_por_forma(
            _error_contra(referencia, obj_c)))
        self.max_vector = _listas(_max_por_forma(err_mov))

        mins, maxs = _min_max_por_forma(obj_c)
        err_solido, color_solido, dispersion = {}, {}, {}
        for forma in FORMAS:
            lo, hi = mins[forma], maxs[forma]
            medio = (lo.astype(np.int32) + hi) // 2
            err_solido[forma] = (hi - medio).max(axis=-1)
            color_solido[forma] = (medio[..., 0] | (medio[..., 1] << 5)
                                   | (medio[..., 2] << 10))
            dispersion[forma] = (hi - lo).max(axis=-1)
        self.err_solido = _listas(err_solido)
        self.color_solido = _listas(color_solido)
        self.dispersion = _listas(dispersion)

        # Candidato "vector + suma de color". La ROM empaqueta el color en las
        # dos mitades de una palabra y suma de 32 en 32 bits, asi que el
        # acarreo entre componentes no se recorta: la unica forma honesta de
        # valorarlo es aplicarlo y medir, solo que a frame completo.
        self.delta, self.recon_delta, err_delta = {}, {}, {}
        if usa_vectores:
            ref = self.ref_vector
            for w, h in FORMAS:
                d = ((objetivo[0::h, 0::w].astype(np.int32)
                      - ref[0::h, 0::w]) & 0xFFFF).astype(np.uint16)
                extendido = np.repeat(np.repeat(d, h, axis=0), w, axis=1)
                recon = (ref.astype(np.uint32)
                         + extendido).astype(np.uint16)
                e = _error_contra(recon, obj_c)
                err_delta[(w, h)] = e.reshape(ALTO // h, h, ANCHO // w,
                                              w).max(axis=(1, 3))
                self.delta[(w, h)] = d.tolist()
                self.recon_delta[(w, h)] = recon
            self.err_delta = _listas(err_delta)
        else:
            self.err_delta = {}


@dataclass
class Salida:
    """Lo que produce un recorrido del arbol con una tolerancia dada."""
    reconstruido: np.ndarray
    escritor: EscritorBits = field(default_factory=EscritorBits)
    colores: bytearray = field(default_factory=bytearray)
    vectores: bytearray = field(default_factory=bytearray)
    hojas: dict = field(default_factory=dict)

    def bits(self, *v: int) -> None:
        self.escritor.bits(*v)

    def bit(self, v: int) -> None:
        self.escritor.bit(v)

    def color(self, c: int) -> None:
        self.colores += int(c).to_bytes(2, "little")

    def vector(self, i: int) -> None:
        self.vectores.append(int(i))

    def anota(self, tipo: str) -> None:
        self.hojas[tipo] = self.hojas.get(tipo, 0) + 1


def _nodo(an: Analisis, sal: Salida, tol: tuple,
          y: int, x: int, w: int, h: int) -> None:
    forma = (w, h)
    limite = tol[banda(w, h)]
    dos = w * h == 2
    iy, ix = y // h, x // w
    ys, xs = slice(y, y + h), slice(x, x + w)

    # 1. copia directa: 2 bits
    if an.max_copia[forma][iy][ix] <= limite:
        sal.bits(0, 0)
        sal.reconstruido[ys, xs] = an.referencia[ys, xs]
        sal.anota("copia")
        return

    # 2. copia con vector: 2 bits + 1 byte
    if an.usa_vectores and an.max_vector[forma][iy][ix] <= limite:
        sal.bits(0, 1)
        sal.vector(an.idx_vector[y // 8, x // 8])
        sal.reconstruido[ys, xs] = an.ref_vector[ys, xs]
        sal.anota("copia_vector")
        return

    # 3. relleno solido: 3 bits + 1 color
    if an.err_solido[forma][iy][ix] <= limite:
        if dos:
            sal.bits(1, 1, 0)
        else:
            sal.bits(1, 1, 1)
        color = an.color_solido[forma][iy][ix]
        sal.color(color)
        sal.reconstruido[ys, xs] = color
        sal.anota("solido")
        return

    # 4. vector + suma de color: 3 bits (2 en las hojas de 2 px) + byte + color
    if an.usa_vectores and an.err_delta[forma][iy][ix] <= limite:
        if dos:
            sal.bits(1, 0)
        else:
            sal.bits(1, 1, 0)
        sal.vector(an.idx_vector[y // 8, x // 8])
        sal.color(an.delta[forma][iy][ix])
        sal.reconstruido[ys, xs] = an.recon_delta[forma][ys, xs]
        sal.anota("vector_color")
        return

    # 5. hoja de 2 px sin salida: un color propio para cada pixel (exacto)
    if dos:
        sal.bits(1, 1, 1)
        obj = an.objetivo[ys, xs].ravel()
        sal.color(int(obj[0]))
        sal.color(int(obj[1]))
        sal.reconstruido[ys, xs] = an.objetivo[ys, xs]
        sal.anota("dos_colores")
        return

    # 6. partir. El bit de direccion solo existe si ambas dimensiones son > 1.
    if h == 1:
        vertical = False
    elif w == 1:
        vertical = True
    else:
        vertical = _mejor_direccion(an, y, x, w, h)
    sal.bits(1, 0)
    if w > 1 and h > 1:
        sal.bit(0 if vertical else 1)
    if vertical:
        h2 = h // 2
        _nodo(an, sal, tol, y, x, w, h2)
        _nodo(an, sal, tol, y + h2, x, w, h2)
    else:
        w2 = w // 2
        _nodo(an, sal, tol, y, x, w2, h)
        _nodo(an, sal, tol, y, x + w2, w2, h)


def _mejor_direccion(an: Analisis, y, x, w, h) -> bool:
    """True = partir en horizontal (arriba/abajo).

    Se elige la particion cuyas dos mitades son mas homogeneas, que es la que
    tiene mas posibilidades de resolverse con hojas baratas.
    """
    w2, h2 = w // 2, h // 2
    vert = an.dispersion[(w, h2)]
    horiz = an.dispersion[(w2, h)]
    coste_v = vert[y // h2][x // w] + vert[(y + h2) // h2][x // w]
    coste_h = horiz[y // h][x // w2] + horiz[y // h][(x + w2) // w2]
    return coste_v <= coste_h


# --- codificacion de un frame ------------------------------------------

def _recorrer(an: Analisis, tol: tuple) -> Salida:
    sal = Salida(reconstruido=np.empty_like(an.objetivo))
    for by in range(BLOQUES_Y):
        for bx in range(BLOQUES_X):
            _nodo(an, sal, tol, by * 8, bx * 8, 8, 8)
    return sal


class SalidaC:
    """Lo poco que se necesita saber de un frame codificado en C."""

    __slots__ = ("hojas",)

    def __init__(self, hojas):
        self.hojas = hojas


def codificar_frame(objetivo: np.ndarray, referencia: np.ndarray,
                    calidad: Calidad, tolerancias=None):
    """Un frame. Devuelve (payload, reconstruido, salida)."""
    tol = list(calidad.tolerancias if tolerancias is None else tolerancias)

    if nucleo is not None:
        payload, recon, hojas = nucleo.codifica_frame(
            np.ascontiguousarray(objetivo, dtype=np.uint16),
            np.ascontiguousarray(referencia, dtype=np.uint16),
            tol[0], tol[1], tol[2], tol[3], tol[4],
            1 if calidad.vectores else 0,
            0 if calidad.busqueda == "rapida" else 1,
            calidad.pasadas, calidad.tope, calidad.frame_size, calidad.paso)
        return (payload,
                np.frombuffer(recon, dtype=np.uint16).reshape(ALTO, ANCHO),
                SalidaC(hojas))

    # La busqueda de vectores se hace UNA vez por frame, no una por pasada:
    # no depende de la tolerancia salvo por el conjunto de bloques activos, y
    # ese solo se encoge segun la tolerancia sube, asi que lo calculado con la
    # tolerancia inicial vale para todas las pasadas.
    if calidad.vectores:
        err_copia = _error_contra(referencia, componentes(objetivo))
        activos = err_copia.reshape(BLOQUES_Y, 8, BLOQUES_X, 8).max(
            axis=(1, 3)) > tol[banda(8, 8)]
        movimiento = buscar(objetivo, referencia, activos, calidad.busqueda)
    else:
        movimiento = (np.zeros((BLOQUES_Y, BLOQUES_X), dtype=np.uint8),
                      referencia,
                      np.full((ALTO, ANCHO), ERROR_INVALIDO, dtype=np.int16))

    an = Analisis(objetivo, referencia, calidad.vectores, movimiento)
    limite = max(calidad.pasadas, 32)
    for pasada in range(limite):
        sal = _recorrer(an, tuple(tol))
        tam = _tamano(sal)
        agotado = pasada >= calidad.pasadas - 1
        if tam <= calidad.frame_size and _cabe(sal):
            break
        # Pasadas normales: apuntar a FrameSize. Agotadas esas, solo se sigue
        # subiendo si el frame ni siquiera cabe en el tope duro.
        if agotado and tam <= calidad.tope and _cabe(sal):
            break
        if min(tol) >= 31:      # el error maximo posible en 5 bits
            break
        tol = [min(t + calidad.paso, 31) for t in tol]
    return _ensamblar(sal), sal.reconstruido, sal


def _tamano(sal: Salida) -> int:
    return (4 + sal.escritor.bytes_finales + len(sal.colores)
            + len(sal.vectores))


def _cabe(sal: Salida) -> bool:
    """Los tres campos de tamano son u16, y la longitud del frame tambien.

    Un frame de ruido puro no cabe: cada pareja de pixeles necesitaria dos
    colores propios, 76800 bytes solo de color. El control de tamano sube la
    tolerancia hasta que cabe, que es lo mismo que hace con FrameSize.
    """
    return (sal.escritor.bytes_finales <= 0xFFFF
            and len(sal.colores) <= 0xFFFF
            and _tamano(sal) <= 0xFFFF)


def _ensamblar(sal: Salida) -> bytes:
    flujo = sal.escritor.terminar()
    cab = len(flujo).to_bytes(2, "little") + len(sal.colores).to_bytes(2, "little")
    return cab + flujo + bytes(sal.colores) + bytes(sal.vectores)


class CodificadorVideo:
    """Codifica frame a frame manteniendo la referencia reconstruida.

    La referencia tiene que ser lo que reconstruye el decodificador, no el
    original, o el error se acumula. El codificador original pone su referencia
    a negro cada 600 frames; no hace falta imitarlo, porque contra una
    referencia negra se acaba emitiendo color explicito en todas partes y el
    resultado es el mismo con mas bytes. Eso mismo es lo que permite trocear un
    video y codificar los trozos en paralelo (ver jobs/parallel.py).
    """

    def __init__(self, calidad: Calidad | str = "alta"):
        self.calidad = (CALIDADES[calidad] if isinstance(calidad, str)
                        else calidad)
        self.referencia = np.zeros((ALTO, ANCHO), dtype=np.uint16)
        self.frames = 0
        self.estadisticas: list = []

    def frame(self, imagen: np.ndarray) -> bytes:
        """`imagen` puede ser (H,W,3) RGB888 o (H,W) uint16 ya en BGR555."""
        objetivo = imagen if imagen.ndim == 2 else a_bgr555(imagen)
        if objetivo.shape != (ALTO, ANCHO):
            raise ValueError(f"se esperaba {ALTO}x{ANCHO}, no {objetivo.shape}")
        payload, reconstruido, sal = codificar_frame(
            objetivo.astype(np.uint16), self.referencia, self.calidad)
        if len(payload) > 0xFFFF:
            raise ValueError(f"payload de {len(payload)} B: no cabe en el u16")
        self.referencia = reconstruido
        self.frames += 1
        self.estadisticas.append(sal.hojas)
        return payload


def envolver(payloads: list[bytes]) -> bytes:
    """Payloads -> fichero .gbm completo."""
    cuerpo = bytearray()
    for p in payloads:
        cuerpo += len(p).to_bytes(2, "little") + p
    tamano = 0x200 + len(cuerpo)
    return escribir_cabecera(*MAGICO_VIDEO, tamano, MODO_VIDEO) + bytes(cuerpo)


def codificar(imagenes, calidad: Calidad | str = "alta") -> bytes:
    cod = CodificadorVideo(calidad)
    return envolver([cod.frame(img) for img in imagenes])
