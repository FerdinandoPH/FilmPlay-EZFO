"""Como meter una imagen de cualquier forma en los 240x160 de la GBA.

El conversor original tenia `ImageH`/`ImageV`/`ChangeScale`, que solo
alimentaban su escalador. Aqui se sustituyen por tres politicas explicitas, que
es lo que de verdad quiere decidir quien convierte.
"""
from dataclasses import dataclass

ANCHO = 240
ALTO = 160

BARRAS = "barras"        # no deforma; sobra fondo arriba/abajo o a los lados
RECORTE = "recorte"      # llena la pantalla; se pierde lo que sale del marco
ESTIRADO = "estirado"    # llena la pantalla deformando

AJUSTES = (BARRAS, RECORTE, ESTIRADO)


@dataclass(frozen=True)
class Imagen:
    """Preproceso de pixel, el equivalente de Brightness/Contrast/Enhance."""
    brillo: int = 0        # -100..100, 0 = sin tocar
    contraste: int = 100   # 0..200, 100 = sin tocar
    realce: int = 0        # 0..100, 0 = sin tocar

    @property
    def neutro(self) -> bool:
        return (self.brillo, self.contraste, self.realce) == (0, 100, 0)


def filtro_escalado(ajuste: str = BARRAS, color: str = "black") -> str:
    if ajuste == ESTIRADO:
        return f"scale={ANCHO}:{ALTO}"
    if ajuste == RECORTE:
        return (f"scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
                f"crop={ANCHO}:{ALTO}")
    if ajuste == BARRAS:
        return (f"scale={ANCHO}:{ALTO}:force_original_aspect_ratio=decrease,"
                f"pad={ANCHO}:{ALTO}:(ow-iw)/2:(oh-ih)/2:color={color}")
    raise ValueError(f"ajuste desconocido: {ajuste!r}")


def filtro_imagen(imagen: Imagen) -> str:
    """Cadena de filtros del preproceso, o cadena vacia si no toca nada."""
    partes = []
    if imagen.brillo or imagen.contraste != 100:
        partes.append(f"eq=brightness={imagen.brillo / 100:.4f}"
                      f":contrast={imagen.contraste / 100:.4f}")
    if imagen.realce:
        # unsharp con radio pequeno: a 240x160 uno grande emborrona mas que
        # realza
        partes.append(f"unsharp=3:3:{imagen.realce / 50:.4f}")
    return ",".join(partes)
