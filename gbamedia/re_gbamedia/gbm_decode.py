#!/usr/bin/env python3
"""Decodificador de referencia del formato .gbm (GBA Movie Player).

Transcrito del decodificador de la ROM FilmPlay.gba (0x08120000-0x08122e9c).
El codec es un arbol binario de particion sobre bloques de 8x8 pixeles.
"""
import struct, sys

W, H = 240, 160
STRIDE = W * 2          # bytes por fila
HDR = 0x200

# Formas: (ancho, alto). Particion vertical -> mitad superior/inferior,
# particion horizontal -> mitad izquierda/derecha.
def half_v(w, h): return (w, h // 2)
def half_h(w, h): return (w // 2, h)


class Bits:
    """Lector de bits: 32 bits por palabra de 32, MSB primero."""
    def __init__(self, data):
        self.d = data
        self.p = 0
        self.r = 0
        self.n = 0            # bits que quedan en el registro

    def bit(self):
        if self.n == 0:
            if self.p + 4 > len(self.d):
                raise EOFError('bitstream agotado')
            self.r = struct.unpack_from('<I', self.d, self.p)[0]
            self.p += 4
            self.n = 32
        c = (self.r >> 31) & 1
        self.r = (self.r << 1) & 0xFFFFFFFF
        self.n -= 1
        return c


class Frame:
    def __init__(self, payload, mvtab):
        nb, nc = struct.unpack_from('<HH', payload, 0)
        self.nb, self.nc = nb, nc
        self.bits = Bits(payload[4:4 + nb])
        self.col = payload[4 + nb: 4 + nb + nc]
        self.mv = payload[4 + nb + nc:]
        self.ci = 0
        self.mi = 0
        self.mvtab = mvtab

    def color(self):
        c = struct.unpack_from('<H', self.col, self.ci)[0]
        self.ci += 2
        return c

    def motion(self):
        v = self.mvtab[self.mv[self.mi]]
        self.mi += 1
        return v


def blit(dst, src, doff, soff, w, h, delta=None):
    """Copia un bloque w*h de src a dst. delta suma un color a cada pixel."""
    for y in range(h):
        s = soff + y * STRIDE
        o = doff + y * STRIDE
        for x in range(w):
            v = struct.unpack_from('<H', src, s + x * 2)[0]
            if delta is not None:
                v = (v + delta) & 0xFFFF
            struct.pack_into('<H', dst, o + x * 2, v)


def fill(dst, doff, w, h, c):
    for y in range(h):
        o = doff + y * STRIDE
        for x in range(w):
            struct.pack_into('<H', dst, o + x * 2, c)


def block(f, cur, prev, off, w, h):
    """Un nodo del arbol. off = desplazamiento en bytes dentro del framebuffer."""
    if f.bits.bit() == 0:
        if f.bits.bit() == 0:
            blit(cur, prev, off, off, w, h)                  # copia directa
        else:
            blit(cur, prev, off, off + f.motion(), w, h)     # copia con vector
        return

    if f.bits.bit() == 0:
        if w * h == 2:
            # hoja de 2 px: aqui el bit significa "delta con vector"
            blit(cur, prev, off, off + f.motion(), w, h, f.color())
            return
        # el bit de direccion solo existe si ambas dimensiones son > 1;
        # una fila o una columna solo se puede partir de una manera
        if h == 1:
            vertical = False
        elif w == 1:
            vertical = True
        else:
            vertical = f.bits.bit() == 0
        if vertical:
            w2, h2 = half_v(w, h)
            block(f, cur, prev, off, w2, h2)
            block(f, cur, prev, off + h2 * STRIDE, w2, h2)
        else:
            w2, h2 = half_h(w, h)
            block(f, cur, prev, off, w2, h2)
            block(f, cur, prev, off + w2 * 2, w2, h2)
        return

    if f.bits.bit() == 0:
        if w * h == 2:
            fill(cur, off, w, h, f.color())                  # relleno solido
        else:
            blit(cur, prev, off, off + f.motion(), w, h, f.color())
        return

    if w * h == 2:
        # dos pixeles con color propio cada uno
        struct.pack_into('<H', cur, off, f.color())
        struct.pack_into('<H', cur, off + (2 if w == 2 else STRIDE), f.color())
    else:
        fill(cur, off, w, h, f.color())


def make_mvtab():
    """256 entradas: desplazamientos (dx,dy) en [-8,7]."""
    return [(((i >> 4) - 8) * STRIDE + ((i & 15) - 8) * 2) for i in range(256)]


def frames(data):
    p = HDR
    while p + 2 <= len(data):
        n = struct.unpack_from('<H', data, p)[0]
        if n == 0:
            break
        yield data[p + 2: p + 2 + n]
        p += 2 + n


def main(path, count=1):
    data = open(path, 'rb').read()
    assert data[0:4] == b'GBAM' and data[8:12] == b'MOVI', 'no es un .gbm'
    mvtab = make_mvtab()
    cur = bytearray(W * H * 2)
    prev = bytearray(W * H * 2)
    for n, payload in enumerate(frames(data)):
        if n >= count:
            break
        f = Frame(payload, mvtab)
        try:
            for by in range(H // 8):
                for bx in range(W // 8):
                    block(f, cur, prev, (by * 8 * W + bx * 8) * 2, 8, 8)
        except (EOFError, IndexError, struct.error) as e:
            print('frame %d: fallo %s (bits %d/%d, col %d/%d, mv %d/%d)'
                  % (n, e, f.bits.p, f.nb, f.ci, f.nc, f.mi, len(f.mv)))
            return
        sobra_bits = (f.nb - f.bits.p) * 8 + f.bits.n
        print('frame %d: bits sobran %3d  colores %d/%d  vectores %d/%d'
              % (n, sobra_bits, f.ci, f.nc, f.mi, len(f.mv)))
        cur, prev = prev, cur
    return prev


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1)


def to_png(fb, path):
    """Vuelca el framebuffer BGR555 como PNG sin dependencias externas."""
    import zlib
    rows = bytearray()
    for y in range(H):
        rows.append(0)
        for x in range(W):
            v = struct.unpack_from('<H', fb, (y * W + x) * 2)[0]
            r = (v & 31) << 3
            g = ((v >> 5) & 31) << 3
            b = ((v >> 10) & 31) << 3
            rows += bytes((r | r >> 5, g | g >> 5, b | b >> 5))

    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(rows), 9))
           + chunk(b'IEND', b''))
    open(path, 'wb').write(png)
