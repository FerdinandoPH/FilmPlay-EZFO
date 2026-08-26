"""Cabeceras y troceado de los contenedores .gbm y .gbs.

Los dos formatos comparten la misma cabecera de 0x200 bytes y solo cambian los
dos magicos:

    0x00  magico       "GBAM" (video) o "GBAL" (audio)
    0x04  u32          tamano total del fichero
    0x08  submagico    "MOVI" o "MUSI"
    0x0C  u32          cero
    0x10  u32          Mode / MusicMode
    0x14  ceros hasta 0x200
"""
import struct
from dataclasses import dataclass

TAM_CABECERA = 0x200

MAGICO_VIDEO = (b"GBAM", b"MOVI")
MAGICO_AUDIO = (b"GBAL", b"MUSI")

# El campo Mode de la cabecera de video vale 4 en los siete ficheros originales
# disponibles, en los tres presets. Lo escribe el EXE, no la DLL, y su
# significado sigue sin conocerse (ver GBM_FORMAT.md).
MODO_VIDEO = 4


class FormatoInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Cabecera:
    magico: bytes
    submagico: bytes
    tamano: int
    modo: int

    @property
    def es_video(self) -> bool:
        return (self.magico, self.submagico) == MAGICO_VIDEO

    @property
    def es_audio(self) -> bool:
        return (self.magico, self.submagico) == MAGICO_AUDIO


def leer_cabecera(datos: bytes) -> Cabecera:
    if len(datos) < TAM_CABECERA:
        raise FormatoInvalido("el fichero no llega ni a la cabecera de 0x200")
    magico = bytes(datos[0:4])
    submagico = bytes(datos[8:12])
    tamano, = struct.unpack_from("<I", datos, 4)
    modo, = struct.unpack_from("<I", datos, 0x10)
    cab = Cabecera(magico, submagico, tamano, modo)
    if not (cab.es_video or cab.es_audio):
        raise FormatoInvalido(
            f"magicos desconocidos: {magico!r}/{submagico!r}")
    return cab


def escribir_cabecera(magico: bytes, submagico: bytes, tamano: int,
                      modo: int) -> bytes:
    """Devuelve los 0x200 bytes de cabecera, con relleno a cero."""
    cab = bytearray(TAM_CABECERA)
    cab[0:4] = magico
    struct.pack_into("<I", cab, 4, tamano)
    cab[8:12] = submagico
    struct.pack_into("<I", cab, 0x10, modo)
    return bytes(cab)


def trocear_frames(datos: bytes):
    """Itera los payloads de un .gbm: u16 de longitud + payload, hasta el final.

    Los frames teselan exactamente el fichero. Una longitud de cero se toma
    como fin, igual que hace el decodificador de referencia.
    """
    p = TAM_CABECERA
    while p + 2 <= len(datos):
        n, = struct.unpack_from("<H", datos, p)
        if n == 0:
            break
        fin = p + 2 + n
        if fin > len(datos):
            raise FormatoInvalido(
                f"frame truncado en {p:#x}: dice {n} bytes y solo quedan "
                f"{len(datos) - p - 2}")
        yield datos[p + 2:fin]
        p = fin
