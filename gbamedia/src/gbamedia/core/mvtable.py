"""Tabla de vectores de movimiento del decodificador de video.

La tabla vive en la zona perdida de la ROM y no se puede leer; se dedujo y se
confirmo con M00006.gbm por histograma de indices y por discontinuidad en los
bordes de bloque (ver GBM_FORMAT.md).

    dx = (indice & 15) - 8          rango [-8, +7]
    dy = (indice >> 4) - 8          rango [-8, +7]
"""

ANCHO = 240
ALTO = 160
PASO = ANCHO * 2          # bytes por fila del framebuffer


def desplazamiento(indice: int) -> int:
    """Desplazamiento en bytes que suma el indice al puntero de referencia."""
    dx = (indice & 15) - 8
    dy = (indice >> 4) - 8
    return dy * PASO + dx * 2


def componentes(indice: int) -> tuple[int, int]:
    return (indice & 15) - 8, (indice >> 4) - 8


def indice(dx: int, dy: int) -> int:
    if not (-8 <= dx <= 7 and -8 <= dy <= 7):
        raise ValueError(f"vector fuera de rango: ({dx}, {dy})")
    return ((dy + 8) << 4) | (dx + 8)


TABLA = [desplazamiento(i) for i in range(256)]
