"""Escritor del bitstream de video: 32 bits por palabra u32 LE, MSB primero.

Contrapartida exacta de `gbm_decode.LectorBits`. Los bits sobrantes de la
ultima palabra son relleno a cero y siempre son menos de 32.
"""
import struct


class EscritorBits:
    __slots__ = ("_palabras", "_r", "_n")

    def __init__(self):
        self._palabras: list[int] = []
        self._r = 0          # palabra en curso, alineada a la izquierda
        self._n = 0          # bits ya metidos en ella

    def bit(self, valor: int) -> None:
        self._r = (self._r << 1) | (valor & 1)
        self._n += 1
        if self._n == 32:
            self._palabras.append(self._r & 0xFFFFFFFF)
            self._r = 0
            self._n = 0

    def bits(self, *valores: int) -> None:
        for v in valores:
            self.bit(v)

    def __len__(self) -> int:
        """Bits escritos."""
        return len(self._palabras) * 32 + self._n

    @property
    def bytes_finales(self) -> int:
        """Tamano que ocupara el flujo, con el relleno de la ultima palabra."""
        return (len(self._palabras) + (1 if self._n else 0)) * 4

    def terminar(self) -> bytes:
        palabras = list(self._palabras)
        if self._n:
            palabras.append((self._r << (32 - self._n)) & 0xFFFFFFFF)
        return struct.pack(f"<{len(palabras)}I", *palabras)
