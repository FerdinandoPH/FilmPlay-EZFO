/* Nucleo en C del codificador: lo mismo que hacen gbm_encode.py y
 * gbs_encode.py, pixel a pixel y muestra a muestra.
 *
 * El Python se queda como implementacion de referencia y como oraculo: las
 * pruebas exigen que las dos den el **mismo byte**, no solo un resultado
 * parecido. Todo es aritmetica entera, asi que la igualdad exacta es
 * alcanzable y cualquier diferencia es un error de una de las dos.
 *
 * Las tablas del cuantizador de audio no se copian aqui: las pasa el modulo
 * de Python al importar, para que no puedan divergir.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* ---------- tablas de audio, puestas desde Python ---------- */

static int STEP[89];
static int IDX4[16];
static int IDX3[8];
static int *DELTA2 = NULL;
static Py_ssize_t DELTA2_N = 0;

static int acota(int v, int lo, int hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

static PyObject *pon_tablas(PyObject *self, PyObject *args)
{
    PyObject *step, *idx4, *idx3, *delta2;
    if (!PyArg_ParseTuple(args, "OOOO", &step, &idx4, &idx3, &delta2))
        return NULL;
    if (PySequence_Size(step) != 89 || PySequence_Size(idx4) != 16
        || PySequence_Size(idx3) != 8) {
        PyErr_SetString(PyExc_ValueError, "tablas de audio con otro tamano");
        return NULL;
    }
    for (int i = 0; i < 89; i++)
        STEP[i] = (int)PyLong_AsLong(PySequence_Fast_GET_ITEM(
            PySequence_Fast(step, "step"), i));
    for (int i = 0; i < 16; i++)
        IDX4[i] = (int)PyLong_AsLong(PySequence_Fast_GET_ITEM(
            PySequence_Fast(idx4, "idx4"), i));
    for (int i = 0; i < 8; i++)
        IDX3[i] = (int)PyLong_AsLong(PySequence_Fast_GET_ITEM(
            PySequence_Fast(idx3, "idx3"), i));
    Py_ssize_t n = PySequence_Size(delta2);
    free(DELTA2);
    DELTA2 = malloc(sizeof(int) * (size_t)n);
    if (!DELTA2) return PyErr_NoMemory();
    PyObject *rapido = PySequence_Fast(delta2, "delta2");
    for (Py_ssize_t i = 0; i < n; i++)
        DELTA2[i] = (int)PyLong_AsLong(PySequence_Fast_GET_ITEM(rapido, i));
    Py_DECREF(rapido);
    DELTA2_N = n;
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

/* ---------- cuantizadores de audio ---------- */

static int enc4(int objetivo, int pred, int idx)
{
    int dif = objetivo - pred, codigo = 0;
    if (dif < 0) { codigo = 8; dif = -dif; }
    int paso = STEP[idx];
    if (dif >= paso) { codigo |= 4; dif -= paso; }
    if (dif >= (paso >> 1)) { codigo |= 2; dif -= paso >> 1; }
    if (dif >= (paso >> 2)) codigo |= 1;
    return codigo;
}

static int enc3(int objetivo, int pred, int idx)
{
    int dif = objetivo - pred, codigo = 0;
    if (dif < 0) { codigo = 4; dif = -dif; }
    int paso = STEP[idx];
    if (dif >= paso) { codigo |= 2; dif -= paso; }
    if (dif >= (paso >> 1)) codigo |= 1;
    return codigo;
}

static int enc2(int objetivo, int pred, int idx)
{
    int mejor = 0, mejor_error = -1;
    for (int codigo = 0; codigo < 4; codigo++) {
        int recon = acota(pred + DELTA2[idx + codigo], 0, 0xFFFF);
        int error = objetivo - recon;
        if (error < 0) error = -error;
        if (mejor_error < 0 || error < mejor_error) {
            mejor = codigo; mejor_error = error;
        }
    }
    return mejor;
}

static void dec4(int codigo, int *pred, int *idx)
{
    int s = STEP[*idx], dif = s >> 3;
    if (codigo & 4) dif += s;
    if (codigo & 2) dif += s >> 1;
    if (codigo & 1) dif += s >> 2;
    if (codigo & 8) dif = -dif;
    *pred = acota(*pred + dif, 0, 0xFFFF);
    *idx = acota(*idx + IDX4[codigo], 0, 88);
}

static void dec3(int codigo, int *pred, int *idx)
{
    int s = STEP[*idx], dif = s >> 2;
    if (codigo & 2) dif += s;
    if (codigo & 1) dif += s >> 1;
    if (codigo & 4) dif = -dif;
    *pred = acota(*pred + dif, 0, 0xFFFF);
    *idx = acota(*idx + IDX3[codigo], 0, 88);
}

static void dec2(int codigo, int *pred, int *idx)
{
    *pred = acota(*pred + DELTA2[*idx + codigo], 0, 0xFFFF);
    *idx = acota(*idx + ((codigo & 1) ? 4 : -4), 0, 0x160);
}

#define TOPE_INDICE_CABECERA 0xA0

/* muestras: int32 contiguo, (n,) mono o (n,2) del modo 0, ya con el sesgo.
 * Devuelve el cuerpo del fichero (sin la cabecera de 0x200).
 */
static PyObject *codifica_adpcm(PyObject *self, PyObject *args)
{
    Py_buffer buf;
    int numero, bloque, cabecera, por_bloque, bits;
    PyObject *aviso;
    int cada;
    if (!PyArg_ParseTuple(args, "y*iiiiiOi", &buf, &numero, &bloque, &cabecera,
                          &por_bloque, &bits, &aviso, &cada))
        return NULL;

    const int32_t *m = (const int32_t *)buf.buf;
    int canales = (numero == 0) ? 2 : 1;
    Py_ssize_t total = buf.len / (Py_ssize_t)(sizeof(int32_t) * canales);
    Py_ssize_t completos = total / por_bloque;
    if (completos * por_bloque != total) {
        PyBuffer_Release(&buf);
        PyErr_SetString(PyExc_ValueError,
                        "las muestras tienen que venir ya completadas");
        return NULL;
    }
    int codificadas = por_bloque - 1;
    int cuerpo = bloque - cabecera;

    PyObject *salida = PyBytes_FromStringAndSize(NULL,
                                                 (Py_ssize_t)bloque * completos);
    if (!salida) { PyBuffer_Release(&buf); return NULL; }
    uint8_t *fuera = (uint8_t *)PyBytes_AS_STRING(salida);
    memset(fuera, 0, (size_t)bloque * (size_t)completos);

    int pa = 0, ia = 0, pb = 0, ib = 0, pred = 0, idx = 0;
    uint8_t *codigos = malloc((size_t)codificadas + 8);
    if (!codigos) {
        Py_DECREF(salida); PyBuffer_Release(&buf); return PyErr_NoMemory();
    }

    for (Py_ssize_t b = 0; b < completos; b++) {
        uint8_t *dst = fuera + (size_t)b * bloque;
        const int32_t *trozo = m + (size_t)b * por_bloque * canales;
        if (numero == 0) {
            pa = trozo[0]; pb = trozo[1];
            dst[0] = pa & 0xFF; dst[1] = (pa >> 8) & 0xFF;
            dst[2] = ia & 0xFF; dst[3] = (ia >> 8) & 0xFF;
            dst[4] = pb & 0xFF; dst[5] = (pb >> 8) & 0xFF;
            dst[6] = ib & 0xFF; dst[7] = (ib >> 8) & 0xFF;
            for (int i = 1; i < por_bloque; i++) {
                int ca = enc4(trozo[i * 2], pa, ia);
                int cb = enc4(trozo[i * 2 + 1], pb, ib);
                dst[cabecera + i - 1] = (uint8_t)(ca | (cb << 4));
                dec4(ca, &pa, &ia);
                dec4(cb, &pb, &ib);
            }
        } else {
            pred = trozo[0];
            idx = idx > TOPE_INDICE_CABECERA ? TOPE_INDICE_CABECERA : idx;
            dst[0] = pred & 0xFF; dst[1] = (pred >> 8) & 0xFF;
            dst[2] = idx & 0xFF;  dst[3] = (idx >> 8) & 0xFF;
            for (int i = 1; i < por_bloque; i++) {
                int c;
                if (bits == 4)      { c = enc4(trozo[i], pred, idx); dec4(c, &pred, &idx); }
                else if (bits == 3) { c = enc3(trozo[i], pred, idx); dec3(c, &pred, &idx); }
                else                { c = enc2(trozo[i], pred, idx); dec2(c, &pred, &idx); }
                codigos[i - 1] = (uint8_t)c;
            }
            uint8_t *cu = dst + cabecera;
            if (bits == 4) {
                for (int i = 0; i < codificadas; i += 2)
                    cu[i / 2] = (uint8_t)(codigos[i] | (codigos[i + 1] << 4));
            } else if (bits == 3) {
                /* 8 codigos en 24 bits big endian, el primero en los bits bajos */
                for (int g = 0; g < codificadas / 8; g++) {
                    uint32_t v = 0;
                    for (int k = 0; k < 8; k++)
                        v |= (uint32_t)codigos[g * 8 + k] << (3 * k);
                    cu[g * 3] = (uint8_t)((v >> 16) & 0xFF);
                    cu[g * 3 + 1] = (uint8_t)((v >> 8) & 0xFF);
                    cu[g * 3 + 2] = (uint8_t)(v & 0xFF);
                }
            } else {
                for (int i = 0; i < codificadas; i += 4)
                    cu[i / 4] = (uint8_t)(codigos[i] | (codigos[i + 1] << 2)
                                          | (codigos[i + 2] << 4)
                                          | (codigos[i + 3] << 6));
            }
            (void)cuerpo;
        }
        if (aviso != Py_None && cada > 0 && (b % cada) == 0) {
            PyObject *r = PyObject_CallFunction(aviso, "nn", (Py_ssize_t)(b + 1),
                                                completos);
            if (!r) {
                free(codigos); Py_DECREF(salida); PyBuffer_Release(&buf);
                return NULL;
            }
            Py_DECREF(r);
        }
    }
    free(codigos);
    PyBuffer_Release(&buf);
    return salida;
}


/* ================= video ================= */

#define ANCHO 240
#define ALTO 160
#define PIXELES (ANCHO * ALTO)
#define BX (ANCHO / 8)
#define BY (ALTO / 8)
#define NB (BX * BY)
#define INVALIDO 255
#define CANDIDATOS 4
#define MARGEN (8 * ANCHO + 8)

/* Las 16 formas (w,h) con w=1<<lw, h=1<<lh. La (1,1) no es una forma del
 * arbol, pero es la base de la que salen todas las reducciones. */
static int TAM_SH[16], OFF_SH[16], TOTAL_SH;

static void prepara_formas(void)
{
    if (TOTAL_SH) return;
    int off = 0;
    for (int lw = 0; lw < 4; lw++)
        for (int lh = 0; lh < 4; lh++) {
            int sh = lw * 4 + lh;
            TAM_SH[sh] = PIXELES >> (lw + lh);
            OFF_SH[sh] = off;
            off += TAM_SH[sh];
        }
    TOTAL_SH = off;
}

static int banda(int w, int h)
{
    int area = w * h;
    if (area >= 64) return 0;
    if (area == 32) return 1;
    if (area == 16) return 2;
    if (area == 8) return 3;
    return 4;
}

/* --- escritor de bits: 32 bits por palabra, MSB primero --- */

typedef struct {
    uint32_t *palabras;
    size_t n, cap;
    uint32_t r;
    int bits;
} Bits;

static int bits_crece(Bits *b)
{
    size_t cap = b->cap ? b->cap * 2 : 1024;
    uint32_t *p = realloc(b->palabras, cap * sizeof(uint32_t));
    if (!p) return -1;
    b->palabras = p; b->cap = cap;
    return 0;
}

static int bit(Bits *b, int v)
{
    b->r = (b->r << 1) | (uint32_t)(v & 1);
    if (++b->bits == 32) {
        if (b->n == b->cap && bits_crece(b) < 0) return -1;
        b->palabras[b->n++] = b->r;
        b->r = 0; b->bits = 0;
    }
    return 0;
}

static size_t bits_bytes(const Bits *b)
{
    return (b->n + (b->bits ? 1 : 0)) * 4;
}

/* --- contexto del recorrido --- */

typedef struct {
    uint8_t *datos;
    size_t n, cap;
} Cola;

static int cola_pon(Cola *c, const uint8_t *d, size_t k)
{
    if (c->n + k > c->cap) {
        size_t cap = c->cap ? c->cap * 2 : 4096;
        while (cap < c->n + k) cap *= 2;
        uint8_t *p = realloc(c->datos, cap);
        if (!p) return -1;
        c->datos = p; c->cap = cap;
    }
    memcpy(c->datos + c->n, d, k);
    c->n += k;
    return 0;
}

typedef struct {
    const uint16_t *obj, *refv, *ref;
    const uint8_t *obr, *obg, *obb;
    const uint8_t *tmax_copia, *tmax_vector, *terr_solido, *tdisp;
    const uint16_t *tcolor;
    const uint8_t *idx_vector;
    int usa_vectores;
    int tol[5];
    uint16_t *recon;
    Bits bits;
    Cola colores, vectores;
    long hojas[5];
    int fallo;
} Ctx;

enum { H_COPIA, H_COPIA_VECTOR, H_SOLIDO, H_VECTOR_COLOR, H_DOS_COLORES };

static void pinta(Ctx *c, int y, int x, int w, int h, const uint16_t *fuente)
{
    for (int j = 0; j < h; j++)
        memcpy(c->recon + (size_t)(y + j) * ANCHO + x,
               fuente + (size_t)(y + j) * ANCHO + x, (size_t)w * 2);
}

static void rellena(Ctx *c, int y, int x, int w, int h, uint16_t color)
{
    for (int j = 0; j < h; j++) {
        uint16_t *fila = c->recon + (size_t)(y + j) * ANCHO + x;
        for (int i = 0; i < w; i++) fila[i] = color;
    }
}

static void pon_color(Ctx *c, unsigned color)
{
    uint8_t par[2] = { (uint8_t)(color & 0xFF), (uint8_t)((color >> 8) & 0xFF) };
    if (cola_pon(&c->colores, par, 2) < 0) c->fallo = 1;
}

static void pon_vector(Ctx *c, uint8_t v)
{
    if (cola_pon(&c->vectores, &v, 1) < 0) c->fallo = 1;
}

static int comp_err(const Ctx *c, uint16_t valor, size_t p)
{
    int e = (int)(valor & 31) - (int)c->obr[p];
    if (e < 0) e = -e;
    int g = (int)((valor >> 5) & 31) - (int)c->obg[p];
    if (g < 0) g = -g;
    if (g > e) e = g;
    int b = (int)((valor >> 10) & 31) - (int)c->obb[p];
    if (b < 0) b = -b;
    return b > e ? b : e;
}

static void nodo(Ctx *c, int y, int x, int lw, int lh)
{
    int w = 1 << lw, h = 1 << lh;
    int sh = lw * 4 + lh;
    int celdas = ANCHO >> lw;
    int celda = OFF_SH[sh] + (y >> lh) * celdas + (x >> lw);
    int limite = c->tol[banda(w, h)];
    int dos = (w * h) == 2;

    /* 1. copia directa: 2 bits */
    if (c->tmax_copia[celda] <= limite) {
        bit(&c->bits, 0); bit(&c->bits, 0);
        pinta(c, y, x, w, h, c->ref);
        c->hojas[H_COPIA]++;
        return;
    }

    /* 2. copia con vector: 2 bits + 1 byte */
    if (c->usa_vectores && c->tmax_vector[celda] <= limite) {
        bit(&c->bits, 0); bit(&c->bits, 1);
        pon_vector(c, c->idx_vector[(y >> 3) * BX + (x >> 3)]);
        pinta(c, y, x, w, h, c->refv);
        c->hojas[H_COPIA_VECTOR]++;
        return;
    }

    /* 3. relleno solido: 3 bits + 1 color */
    if (c->terr_solido[celda] <= limite) {
        bit(&c->bits, 1); bit(&c->bits, 1); bit(&c->bits, dos ? 0 : 1);
        uint16_t color = c->tcolor[celda];
        pon_color(c, color);
        rellena(c, y, x, w, h, color);
        c->hojas[H_SOLIDO]++;
        return;
    }

    /* 4. vector + suma de color. La ROM suma la palabra entera de 32 bits con
     * el color duplicado en las dos mitades, asi que el acarreo entre
     * componentes no se recorta: hay que aplicarlo y medir. */
    if (c->usa_vectores) {
        uint16_t d = (uint16_t)(c->obj[(size_t)y * ANCHO + x]
                                - c->refv[(size_t)y * ANCHO + x]);
        int err = 0;
        for (int j = 0; j < h && err <= limite; j++) {
            size_t base = (size_t)(y + j) * ANCHO + x;
            for (int i = 0; i < w; i++) {
                int e = comp_err(c, (uint16_t)(c->refv[base + i] + d), base + i);
                if (e > err) { err = e; if (err > limite) break; }
            }
        }
        if (err <= limite) {
            bit(&c->bits, 1);
            if (dos) { bit(&c->bits, 0); }
            else { bit(&c->bits, 1); bit(&c->bits, 0); }
            pon_vector(c, c->idx_vector[(y >> 3) * BX + (x >> 3)]);
            pon_color(c, d);
            for (int j = 0; j < h; j++) {
                size_t base = (size_t)(y + j) * ANCHO + x;
                for (int i = 0; i < w; i++)
                    c->recon[base + i] = (uint16_t)(c->refv[base + i] + d);
            }
            c->hojas[H_VECTOR_COLOR]++;
            return;
        }
    }

    /* 5. hoja de 2 px sin salida: un color propio por pixel (exacto) */
    if (dos) {
        bit(&c->bits, 1); bit(&c->bits, 1); bit(&c->bits, 1);
        size_t p0 = (size_t)y * ANCHO + x;
        size_t p1 = (h == 2) ? p0 + ANCHO : p0 + 1;
        pon_color(c, c->obj[p0]);
        pon_color(c, c->obj[p1]);
        c->recon[p0] = c->obj[p0];
        c->recon[p1] = c->obj[p1];
        c->hojas[H_DOS_COLORES]++;
        return;
    }

    /* 6. partir. El bit de direccion solo existe si ambas dimensiones son > 1 */
    int vertical;
    if (h == 1) vertical = 0;
    else if (w == 1) vertical = 1;
    else {
        int shv = lw * 4 + (lh - 1);          /* (w, h/2) */
        int shh = (lw - 1) * 4 + lh;          /* (w/2, h) */
        int cv = ANCHO >> lw, ch = ANCHO >> (lw - 1);
        int h2 = h / 2, w2 = w / 2;
        int coste_v = c->tdisp[OFF_SH[shv] + (y / h2) * cv + (x / w)]
                    + c->tdisp[OFF_SH[shv] + ((y + h2) / h2) * cv + (x / w)];
        int coste_h = c->tdisp[OFF_SH[shh] + (y / h) * ch + (x / w2)]
                    + c->tdisp[OFF_SH[shh] + (y / h) * ch + ((x + w2) / w2)];
        vertical = coste_v <= coste_h;
    }
    bit(&c->bits, 1); bit(&c->bits, 0);
    if (w > 1 && h > 1) bit(&c->bits, vertical ? 0 : 1);
    if (vertical) {
        nodo(c, y, x, lw, lh - 1);
        nodo(c, y + (h / 2), x, lw, lh - 1);
    } else {
        nodo(c, y, x, lw - 1, lh);
        nodo(c, y, x + (w / 2), lw - 1, lh);
    }
}

/* --- busqueda de movimiento --- */

typedef struct {
    const uint8_t *obr, *obg, *obb;
    const uint8_t *rfr, *rfg, *rfb;
} Planos;

static long long punto_bloque(const Planos *p, int base, int o, int *err_max)
{
    int mx = 0;
    long suma = 0;
    for (int j = 0; j < 8; j++) {
        int fila = base + j * ANCHO;
        for (int i = 0; i < 8; i++) {
            int q = fila + i + o;
            int e;
            if (q < 0 || q >= PIXELES) e = INVALIDO;
            else {
                int pix = fila + i;
                e = (int)p->rfr[q] - (int)p->obr[pix]; if (e < 0) e = -e;
                int g = (int)p->rfg[q] - (int)p->obg[pix]; if (g < 0) g = -g;
                if (g > e) e = g;
                int b = (int)p->rfb[q] - (int)p->obb[pix]; if (b < 0) b = -b;
                if (b > e) e = b;
            }
            if (e > mx) mx = e;
            suma += e;
        }
    }
    if (err_max) *err_max = mx;
    return ((long long)mx << 20) + suma;
}


static void reduce(uint8_t *t, int es_max)
{
    /* Cada forma sale de la anterior: (4,8) es el maximo por parejas de (2,8).
     * Dos pasadas sobre el frame en total, no quince. */
    for (int suma = 1; suma <= 6; suma++)
        for (int lw = 0; lw < 4; lw++) {
            int lh = suma - lw;
            if (lh < 0 || lh > 3) continue;
            int sh = lw * 4 + lh;
            int W = ANCHO >> lw, H = ALTO >> lh;
            uint8_t *dst = t + OFF_SH[sh];
            if (lw > 0) {
                const uint8_t *src = t + OFF_SH[(lw - 1) * 4 + lh];
                int PW = ANCHO >> (lw - 1);
                for (int iy = 0; iy < H; iy++)
                    for (int ix = 0; ix < W; ix++) {
                        uint8_t a = src[iy * PW + 2 * ix];
                        uint8_t b = src[iy * PW + 2 * ix + 1];
                        dst[iy * W + ix] = es_max ? (a > b ? a : b)
                                                  : (a < b ? a : b);
                    }
            } else {
                const uint8_t *src = t + OFF_SH[lw * 4 + (lh - 1)];
                for (int iy = 0; iy < H; iy++)
                    for (int ix = 0; ix < W; ix++) {
                        uint8_t a = src[(2 * iy) * W + ix];
                        uint8_t b = src[(2 * iy + 1) * W + ix];
                        dst[iy * W + ix] = es_max ? (a > b ? a : b)
                                                  : (a < b ? a : b);
                    }
            }
        }
}

static PyObject *codifica_frame(PyObject *self, PyObject *args)
{
    Py_buffer bobj, bref;
    int t0, t1, t2, t3, t4, usa_vectores, busqueda, pasadas, tope, frame_size,
        paso;
    if (!PyArg_ParseTuple(args, "y*y*iiiiiiiiiii", &bobj, &bref, &t0, &t1, &t2,
                          &t3, &t4, &usa_vectores, &busqueda, &pasadas, &tope,
                          &frame_size, &paso))
        return NULL;
    if (bobj.len != PIXELES * 2 || bref.len != PIXELES * 2) {
        PyBuffer_Release(&bobj); PyBuffer_Release(&bref);
        PyErr_SetString(PyExc_ValueError, "los frames son de 240x160 en BGR555");
        return NULL;
    }
    prepara_formas();

    const uint16_t *obj = (const uint16_t *)bobj.buf;
    const uint16_t *ref = (const uint16_t *)bref.buf;

    /* --- reservas --- */
    uint8_t *planos = malloc(6 * PIXELES);
    uint8_t *err_copia = malloc(PIXELES);
    uint8_t *err_mov = malloc(PIXELES);
    uint16_t *ref_mov = malloc(PIXELES * 2);
    uint16_t *recon = malloc(PIXELES * 2);
    uint8_t *tablas = malloc((size_t)TOTAL_SH * 10);
    uint16_t *tcolor = malloc((size_t)TOTAL_SH * 2);
    int16_t *luz_obj = malloc(PIXELES * sizeof(int16_t));
    int16_t *luz_pad = malloc((PIXELES + 2 * MARGEN) * sizeof(int16_t));
    int *mejores = malloc(NB * CANDIDATOS * sizeof(int));
    int *puntas = malloc(NB * CANDIDATOS * sizeof(int));
    int *cuantos = malloc(NB * sizeof(int));
    uint8_t *idx_vector = malloc(NB);
    if (!planos || !err_copia || !err_mov || !ref_mov || !recon || !tablas
        || !tcolor || !luz_obj || !luz_pad || !mejores || !puntas || !cuantos
        || !idx_vector) {
        free(planos); free(err_copia); free(err_mov); free(ref_mov);
        free(recon); free(tablas); free(tcolor); free(luz_obj); free(luz_pad);
        free(mejores); free(puntas); free(cuantos); free(idx_vector);
        PyBuffer_Release(&bobj); PyBuffer_Release(&bref);
        return PyErr_NoMemory();
    }
    uint8_t *obr = planos, *obg = planos + PIXELES, *obb = planos + 2 * PIXELES;
    uint8_t *rfr = planos + 3 * PIXELES, *rfg = planos + 4 * PIXELES,
            *rfb = planos + 5 * PIXELES;
    uint8_t *tminr = tablas, *tming = tablas + TOTAL_SH,
            *tminb = tablas + 2 * TOTAL_SH, *tmaxr = tablas + 3 * TOTAL_SH,
            *tmaxg = tablas + 4 * TOTAL_SH, *tmaxb = tablas + 5 * TOTAL_SH,
            *tmax_copia = tablas + 6 * TOTAL_SH,
            *tmax_vector = tablas + 7 * TOTAL_SH,
            *terr_solido = tablas + 8 * TOTAL_SH,
            *tdisp = tablas + 9 * TOTAL_SH;

    Ctx c;
    memset(&c, 0, sizeof(c));

    Py_BEGIN_ALLOW_THREADS

    for (int p = 0; p < PIXELES; p++) {
        uint16_t v = obj[p], r = ref[p];
        obr[p] = v & 31; obg[p] = (v >> 5) & 31; obb[p] = (v >> 10) & 31;
        rfr[p] = r & 31; rfg[p] = (r >> 5) & 31; rfb[p] = (r >> 10) & 31;
        int e = (int)rfr[p] - (int)obr[p]; if (e < 0) e = -e;
        int g = (int)rfg[p] - (int)obg[p]; if (g < 0) g = -g;
        if (g > e) e = g;
        int b = (int)rfb[p] - (int)obb[p]; if (b < 0) b = -b;
        err_copia[p] = (uint8_t)(b > e ? b : e);
    }

    /* --- busqueda de movimiento --- */
    memset(err_mov, INVALIDO, PIXELES);
    memcpy(ref_mov, ref, PIXELES * 2);
    memset(idx_vector, (8 << 4) | 8, NB);       /* vector nulo */

    int desp[256];
    for (int i = 0; i < 256; i++)
        desp[i] = (((i >> 4) - 8) * ANCHO) + ((i & 15) - 8);

    int activo[NB];
    int hay_activos = 0;
    if (usa_vectores) {
        int limite8 = t0;                       /* banda de los bloques 8x8 */
        for (int by = 0; by < BY; by++)
            for (int bx = 0; bx < BX; bx++) {
                int base = by * 8 * ANCHO + bx * 8, m = 0;
                for (int j = 0; j < 8; j++)
                    for (int i = 0; i < 8; i++) {
                        int e = err_copia[base + j * ANCHO + i];
                        if (e > m) m = e;
                    }
                activo[by * BX + bx] = m > limite8;
                if (m > limite8) hay_activos = 1;
            }
    } else {
        memset(activo, 0, sizeof(activo));
    }

    Planos pl = { obr, obg, obb, rfr, rfg, rfb };

    if (usa_vectores && hay_activos && busqueda == 0) {
        /* Criba con una sola magnitud por pixel y despues los finalistas con
         * la metrica buena. El gather es lo caro; esto se lo salta. */
        for (int p = 0; p < PIXELES; p++)
            luz_obj[p] = (int16_t)(obr[p] + 2 * obg[p] + obb[p]);
        for (int p = 0; p < PIXELES + 2 * MARGEN; p++) luz_pad[p] = 1000;
        for (int p = 0; p < PIXELES; p++)
            luz_pad[MARGEN + p] = (int16_t)(rfr[p] + 2 * rfg[p] + rfb[p]);
        memset(cuantos, 0, NB * sizeof(int));
        for (int i = 0; i < 256; i++) {
            const int16_t *desde = luz_pad + MARGEN + desp[i];
            for (int b = 0; b < NB; b++) {
                int peor = (cuantos[b] == CANDIDATOS)
                         ? puntas[b * CANDIDATOS + CANDIDATOS - 1] : 0x7FFFFFFF;
                int base = (b / BX) * 8 * ANCHO + (b % BX) * 8, m = 0;
                for (int j = 0; j < 8 && m < peor; j++) {
                    const int16_t *pr = desde + base + j * ANCHO;
                    const int16_t *po = luz_obj + base + j * ANCHO;
                    for (int k = 0; k < 8; k++) {
                        int d = pr[k] - po[k];
                        if (d < 0) d = -d;
                        if (d > m) { m = d; if (m >= peor) break; }
                    }
                }
                if (m >= peor) continue;
                /* insercion ordenada: en empate se queda el vector de indice
                 * menor, que es lo que hace el argsort estable del Python */
                int n = cuantos[b];
                int pos = n;
                while (pos > 0 && puntas[b * CANDIDATOS + pos - 1] > m) pos--;
                for (int k = (n < CANDIDATOS ? n : CANDIDATOS - 1); k > pos; k--) {
                    puntas[b * CANDIDATOS + k] = puntas[b * CANDIDATOS + k - 1];
                    mejores[b * CANDIDATOS + k] = mejores[b * CANDIDATOS + k - 1];
                }
                puntas[b * CANDIDATOS + pos] = m;
                mejores[b * CANDIDATOS + pos] = i;
                if (n < CANDIDATOS) cuantos[b] = n + 1;
            }
        }
        for (int b = 0; b < NB; b++) {
            if (!activo[b]) continue;
            int base = (b / BX) * 8 * ANCHO + (b % BX) * 8;
            long long mejor = (long long)1 << 62;
            int elegido = (8 << 4) | 8;
            for (int k = 0; k < cuantos[b]; k++) {
                int cand = mejores[b * CANDIDATOS + k];
                long long punto = punto_bloque(&pl, base, desp[cand], NULL);
                if (punto < mejor) { mejor = punto; elegido = cand; }
            }
            idx_vector[b] = (uint8_t)elegido;
        }
    } else if (usa_vectores && hay_activos) {
        for (int b = 0; b < NB; b++) {
            if (!activo[b]) continue;
            int base = (b / BX) * 8 * ANCHO + (b % BX) * 8;
            long long mejor = (long long)1 << 62;
            int elegido = (8 << 4) | 8;
            for (int i = 0; i < 256; i++) {
                long long punto = punto_bloque(&pl, base, desp[i], NULL);
                if (punto < mejor) { mejor = punto; elegido = i; }
            }
            idx_vector[b] = (uint8_t)elegido;
        }
    }

    if (usa_vectores) {
        for (int b = 0; b < NB; b++) {
            if (!activo[b]) continue;
            int base = (b / BX) * 8 * ANCHO + (b % BX) * 8;
            int o = desp[idx_vector[b]];
            for (int j = 0; j < 8; j++)
                for (int i = 0; i < 8; i++) {
                    int p = base + j * ANCHO + i, q = p + o;
                    if (q < 0 || q >= PIXELES) {
                        err_mov[p] = INVALIDO;
                    } else {
                        int e = (int)rfr[q] - (int)obr[p]; if (e < 0) e = -e;
                        int g = (int)rfg[q] - (int)obg[p]; if (g < 0) g = -g;
                        if (g > e) e = g;
                        int c = (int)rfb[q] - (int)obb[p]; if (c < 0) c = -c;
                        err_mov[p] = (uint8_t)(c > e ? c : e);
                        ref_mov[p] = ref[q];
                    }
                }
        }
    }

    /* --- tablas por forma --- */
    memcpy(tminr + OFF_SH[0], obr, PIXELES);
    memcpy(tming + OFF_SH[0], obg, PIXELES);
    memcpy(tminb + OFF_SH[0], obb, PIXELES);
    memcpy(tmaxr + OFF_SH[0], obr, PIXELES);
    memcpy(tmaxg + OFF_SH[0], obg, PIXELES);
    memcpy(tmaxb + OFF_SH[0], obb, PIXELES);
    memcpy(tmax_copia + OFF_SH[0], err_copia, PIXELES);
    memcpy(tmax_vector + OFF_SH[0], err_mov, PIXELES);
    reduce(tminr, 0); reduce(tming, 0); reduce(tminb, 0);
    reduce(tmaxr, 1); reduce(tmaxg, 1); reduce(tmaxb, 1);
    reduce(tmax_copia, 1); reduce(tmax_vector, 1);

    for (int lw = 0; lw < 4; lw++)
        for (int lh = 0; lh < 4; lh++) {
            if (lw == 0 && lh == 0) continue;
            int sh = lw * 4 + lh, off = OFF_SH[sh], n = TAM_SH[sh];
            for (int k = 0; k < n; k++) {
                int lo_r = tminr[off + k], hi_r = tmaxr[off + k];
                int lo_g = tming[off + k], hi_g = tmaxg[off + k];
                int lo_b = tminb[off + k], hi_b = tmaxb[off + k];
                int mr = (lo_r + hi_r) / 2, mg = (lo_g + hi_g) / 2,
                    mb = (lo_b + hi_b) / 2;
                int e = hi_r - mr;
                if (hi_g - mg > e) e = hi_g - mg;
                if (hi_b - mb > e) e = hi_b - mb;
                terr_solido[off + k] = (uint8_t)e;
                tcolor[off + k] = (uint16_t)(mr | (mg << 5) | (mb << 10));
                int d = hi_r - lo_r;
                if (hi_g - lo_g > d) d = hi_g - lo_g;
                if (hi_b - lo_b > d) d = hi_b - lo_b;
                tdisp[off + k] = (uint8_t)d;
            }
        }

    /* --- control de tamano --- */
    c.obj = obj; c.ref = ref; c.refv = ref_mov;
    c.obr = obr; c.obg = obg; c.obb = obb;
    c.tmax_copia = tmax_copia; c.tmax_vector = tmax_vector;
    c.terr_solido = terr_solido; c.tdisp = tdisp; c.tcolor = tcolor;
    c.idx_vector = idx_vector; c.usa_vectores = usa_vectores;
    c.recon = recon;
    int tol[5] = { t0, t1, t2, t3, t4 };
    int limite_pasadas = pasadas > 32 ? pasadas : 32;
    size_t tam = 0;

    for (int pasada = 0; pasada < limite_pasadas; pasada++) {
        c.bits.n = 0; c.bits.r = 0; c.bits.bits = 0;
        c.colores.n = 0; c.vectores.n = 0;
        memset(c.hojas, 0, sizeof(c.hojas));
        memcpy(c.tol, tol, sizeof(tol));
        for (int by = 0; by < BY; by++)
            for (int bx = 0; bx < BX; bx++)
                nodo(&c, by * 8, bx * 8, 3, 3);
        if (c.fallo) break;
        size_t flujo = bits_bytes(&c.bits);
        tam = 4 + flujo + c.colores.n + c.vectores.n;
        int cabe = flujo <= 0xFFFF && c.colores.n <= 0xFFFF && tam <= 0xFFFF;
        int agotado = pasada >= pasadas - 1;
        if (tam <= (size_t)frame_size && cabe) break;
        if (agotado && tam <= (size_t)tope && cabe) break;
        int minimo = tol[0];
        for (int k = 1; k < 5; k++) if (tol[k] < minimo) minimo = tol[k];
        if (minimo >= 31) break;
        for (int k = 0; k < 5; k++)
            tol[k] = tol[k] + paso > 31 ? 31 : tol[k] + paso;
    }

    Py_END_ALLOW_THREADS

    PyObject *salida = NULL;
    if (c.fallo) {
        PyErr_NoMemory();
    } else {
        size_t flujo = bits_bytes(&c.bits);
        PyObject *payload = PyBytes_FromStringAndSize(
            NULL, (Py_ssize_t)(4 + flujo + c.colores.n + c.vectores.n));
        if (payload) {
            uint8_t *d = (uint8_t *)PyBytes_AS_STRING(payload);
            d[0] = flujo & 0xFF; d[1] = (flujo >> 8) & 0xFF;
            d[2] = c.colores.n & 0xFF; d[3] = (c.colores.n >> 8) & 0xFF;
            /* la ultima palabra va alineada a la izquierda con relleno a cero */
            for (size_t k = 0; k < c.bits.n; k++) {
                uint32_t w = c.bits.palabras[k];
                d[4 + k * 4] = w & 0xFF; d[5 + k * 4] = (w >> 8) & 0xFF;
                d[6 + k * 4] = (w >> 16) & 0xFF; d[7 + k * 4] = (w >> 24) & 0xFF;
            }
            if (c.bits.bits) {
                uint32_t w = c.bits.r << (32 - c.bits.bits);
                size_t k = c.bits.n;
                d[4 + k * 4] = w & 0xFF; d[5 + k * 4] = (w >> 8) & 0xFF;
                d[6 + k * 4] = (w >> 16) & 0xFF; d[7 + k * 4] = (w >> 24) & 0xFF;
            }
            memcpy(d + 4 + flujo, c.colores.datos, c.colores.n);
            memcpy(d + 4 + flujo + c.colores.n, c.vectores.datos, c.vectores.n);

            PyObject *rec = PyBytes_FromStringAndSize((const char *)recon,
                                                      PIXELES * 2);
            PyObject *hojas = PyDict_New();
            static const char *nombres[5] = { "copia", "copia_vector",
                                              "solido", "vector_color",
                                              "dos_colores" };
            if (rec && hojas) {
                for (int k = 0; k < 5; k++) {
                    if (!c.hojas[k]) continue;
                    PyObject *v = PyLong_FromLong(c.hojas[k]);
                    PyDict_SetItemString(hojas, nombres[k], v);
                    Py_DECREF(v);
                }
                salida = PyTuple_Pack(3, payload, rec, hojas);
            }
            Py_XDECREF(rec); Py_XDECREF(hojas);
        }
        Py_XDECREF(payload);
    }

    free(c.bits.palabras); free(c.colores.datos); free(c.vectores.datos);
    free(planos); free(err_copia); free(err_mov); free(ref_mov); free(recon);
    free(tablas); free(tcolor); free(luz_obj); free(luz_pad); free(mejores);
    free(puntas); free(cuantos); free(idx_vector);
    PyBuffer_Release(&bobj); PyBuffer_Release(&bref);
    return salida;
}



/* ---------- decodificador, para verificar lo que se produce ---------- */

#define PASO (ANCHO * 2)

typedef struct {
    const uint8_t *bits; size_t nbits, pb;
    uint32_t r; int quedan;
    const uint8_t *col; size_t ncol, ci;
    const uint8_t *mv; size_t nmv, mi;
    uint8_t *actual; const uint8_t *anterior;
    long hojas[5];
    int error;              /* 1 bits, 2 colores, 3 vectores */
} Dec;

static int lee_bit(Dec *d)
{
    if (d->quedan == 0) {
        if (d->pb + 4 > d->nbits) { d->error = 1; return 0; }
        d->r = (uint32_t)d->bits[d->pb] | ((uint32_t)d->bits[d->pb + 1] << 8)
             | ((uint32_t)d->bits[d->pb + 2] << 16)
             | ((uint32_t)d->bits[d->pb + 3] << 24);
        d->pb += 4; d->quedan = 32;
    }
    int c = (d->r >> 31) & 1;
    d->r <<= 1;
    d->quedan--;
    return c;
}

static unsigned lee_color(Dec *d)
{
    if (d->ci + 2 > d->ncol) { d->error = 2; return 0; }
    unsigned c = (unsigned)d->col[d->ci] | ((unsigned)d->col[d->ci + 1] << 8);
    d->ci += 2;
    return c;
}

static int lee_vector(Dec *d)
{
    if (d->mi >= d->nmv) { d->error = 3; return 0; }
    int i = d->mv[d->mi++];
    return (((i >> 4) - 8) * PASO) + (((i & 15) - 8) * 2);
}

static void copia_dec(Dec *d, int destino, int origen, int w, int h, int delta,
                      int con_delta)
{
    for (int y = 0; y < h; y++) {
        int s = origen + y * PASO, o = destino + y * PASO;
        if (s < 0 || s + w * 2 > PIXELES * 2 || o < 0 || o + w * 2 > PIXELES * 2)
            continue;                       /* la ROM leeria basura; aqui nada */
        if (!con_delta) {
            memcpy(d->actual + o, d->anterior + s, (size_t)w * 2);
        } else {
            for (int x = 0; x < w * 2; x += 2) {
                unsigned v = (unsigned)d->anterior[s + x]
                           | ((unsigned)d->anterior[s + x + 1] << 8);
                unsigned r = (v + (unsigned)delta) & 0xFFFF;
                d->actual[o + x] = r & 0xFF;
                d->actual[o + x + 1] = (r >> 8) & 0xFF;
            }
        }
    }
}

static void rellena_dec(Dec *d, int destino, int w, int h, unsigned color)
{
    for (int y = 0; y < h; y++) {
        int o = destino + y * PASO;
        for (int x = 0; x < w * 2; x += 2) {
            d->actual[o + x] = color & 0xFF;
            d->actual[o + x + 1] = (color >> 8) & 0xFF;
        }
    }
}

static void nodo_dec(Dec *d, int off, int w, int h)
{
    if (d->error) return;
    if (lee_bit(d) == 0) {
        if (lee_bit(d) == 0) {
            d->hojas[H_COPIA]++;
            copia_dec(d, off, off, w, h, 0, 0);
        } else {
            d->hojas[H_COPIA_VECTOR]++;
            copia_dec(d, off, off + lee_vector(d), w, h, 0, 0);
        }
        return;
    }
    if (lee_bit(d) == 0) {
        if (w * h == 2) {
            d->hojas[H_VECTOR_COLOR]++;
            int o = lee_vector(d);
            copia_dec(d, off, off + o, w, h, (int)lee_color(d), 1);
            return;
        }
        int vertical;
        if (h == 1) vertical = 0;
        else if (w == 1) vertical = 1;
        else vertical = lee_bit(d) == 0;
        if (vertical) {
            nodo_dec(d, off, w, h / 2);
            nodo_dec(d, off + (h / 2) * PASO, w, h / 2);
        } else {
            nodo_dec(d, off, w / 2, h);
            nodo_dec(d, off + (w / 2) * 2, w / 2, h);
        }
        return;
    }
    if (lee_bit(d) == 0) {
        if (w * h == 2) {
            d->hojas[H_SOLIDO]++;
            rellena_dec(d, off, w, h, lee_color(d));
        } else {
            d->hojas[H_VECTOR_COLOR]++;
            int o = lee_vector(d);
            copia_dec(d, off, off + o, w, h, (int)lee_color(d), 1);
        }
        return;
    }
    if (w * h == 2) {
        d->hojas[H_DOS_COLORES]++;
        unsigned c1 = lee_color(d), c2 = lee_color(d);
        d->actual[off] = c1 & 0xFF; d->actual[off + 1] = (c1 >> 8) & 0xFF;
        int o2 = off + ((w == 2) ? 2 : PASO);
        d->actual[o2] = c2 & 0xFF; d->actual[o2 + 1] = (c2 >> 8) & 0xFF;
    } else {
        d->hojas[H_SOLIDO]++;
        rellena_dec(d, off, w, h, lee_color(d));
    }
}

static PyObject *decodifica_frame(PyObject *self, PyObject *args)
{
    Py_buffer bpay, bact, bant;
    if (!PyArg_ParseTuple(args, "y*w*y*", &bpay, &bact, &bant))
        return NULL;
    if (bact.len != PIXELES * 2 || bant.len != PIXELES * 2) {
        PyBuffer_Release(&bpay); PyBuffer_Release(&bact); PyBuffer_Release(&bant);
        PyErr_SetString(PyExc_ValueError, "el framebuffer es de 240x160x2");
        return NULL;
    }
    const uint8_t *pay = (const uint8_t *)bpay.buf;
    if (bpay.len < 4) {
        PyBuffer_Release(&bpay); PyBuffer_Release(&bact); PyBuffer_Release(&bant);
        PyErr_SetString(PyExc_ValueError, "payload menor que su cabecera");
        return NULL;
    }
    size_t nb = (size_t)pay[0] | ((size_t)pay[1] << 8);
    size_t nc = (size_t)pay[2] | ((size_t)pay[3] << 8);
    if (4 + nb + nc > (size_t)bpay.len) {
        PyBuffer_Release(&bpay); PyBuffer_Release(&bact); PyBuffer_Release(&bant);
        PyErr_SetString(PyExc_ValueError, "los flujos no caben en el payload");
        return NULL;
    }
    Dec d;
    memset(&d, 0, sizeof(d));
    d.bits = pay + 4; d.nbits = nb;
    d.col = pay + 4 + nb; d.ncol = nc;
    d.mv = pay + 4 + nb + nc; d.nmv = (size_t)bpay.len - 4 - nb - nc;
    d.actual = (uint8_t *)bact.buf;
    d.anterior = (const uint8_t *)bant.buf;

    Py_BEGIN_ALLOW_THREADS
    for (int by = 0; by < BY; by++)
        for (int bx = 0; bx < BX; bx++)
            nodo_dec(&d, (by * 8 * ANCHO + bx * 8) * 2, 8, 8);
    Py_END_ALLOW_THREADS

    PyObject *salida = NULL;
    if (d.error == 1) PyErr_SetString(PyExc_EOFError, "bitstream agotado");
    else if (d.error == 2) PyErr_SetString(PyExc_IndexError,
                                           "flujo de colores agotado");
    else if (d.error == 3) PyErr_SetString(PyExc_IndexError,
                                           "flujo de vectores agotado");
    else {
        PyObject *hojas = PyDict_New();
        static const char *nombres[5] = { "copia", "copia_vector", "solido",
                                          "vector_color", "dos_colores" };
        if (hojas) {
            for (int k = 0; k < 5; k++) {
                if (!d.hojas[k]) continue;
                PyObject *v = PyLong_FromLong(d.hojas[k]);
                PyDict_SetItemString(hojas, nombres[k], v);
                Py_DECREF(v);
            }
            size_t sobran = (d.nbits - d.pb) * 8 + (size_t)d.quedan;
            salida = Py_BuildValue("nnnnnnN", (Py_ssize_t)nb, (Py_ssize_t)nc,
                                   (Py_ssize_t)d.nmv, (Py_ssize_t)sobran,
                                   (Py_ssize_t)(d.ci / 2), (Py_ssize_t)d.mi,
                                   hojas);
        }
    }
    PyBuffer_Release(&bpay); PyBuffer_Release(&bact); PyBuffer_Release(&bant);
    return salida;
}

static PyMethodDef metodos[] = {
    {"pon_tablas", pon_tablas, METH_VARARGS,
     "Carga las tablas del cuantizador de audio desde Python."},
    {"codifica_adpcm", codifica_adpcm, METH_VARARGS,
     "Cuerpo de un .gbs a partir de las muestras ya diezmadas."},
    {"codifica_frame", codifica_frame, METH_VARARGS,
     "Un frame .gbm: busqueda, arbol y control de tamano."},
    {"decodifica_frame", decodifica_frame, METH_VARARGS,
     "Decodifica un frame .gbm sobre un framebuffer de 240x160."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef modulo = {
    PyModuleDef_HEAD_INIT, "gbamedia.core._fast",
    "Nucleo en C del codificador.", -1, metodos, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit__fast(void)
{
    return PyModule_Create(&modulo);
}
