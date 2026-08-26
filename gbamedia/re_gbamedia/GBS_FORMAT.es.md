[English](GBS_FORMAT.md) · **Español**

# Formato .gbs (GBA Movie Player) — RESUELTO

Descifrado de `savemu.dll` ("GBA Media Music Encoder"). Implementación de
referencia: `gbs_decode.py` + `gbs_tables.py` (tablas extraídas del binario).

## Contenedor

Cabecera global de **0x200 bytes**:

    0x00  "GBAL"
    0x04  u32  tamano total del fichero
    0x08  "MUSI"
    0x0C  u32  cero
    0x10  u32  MusicMode  (0..4)
    0x14  ceros hasta 0x200

A partir de 0x200, bloques de tamaño fijo según el modo. Cada bloque es
**autónomo**: empieza con el predictor y el índice, así que no hay propagación
de error entre bloques y se puede buscar por posición.

## Los cinco modos

Todos parten de audio **44100 Hz, 16 bits, estéreo** (lo dice la ayuda del
propio conversor). La frecuencia final sale del diezmado.

| Modo | Bloque | Cabecera | Bits | Canales | Muestras/bloque | Diezmado | Hz | Ratio |
|---|---|---|---|---|---|---|---|---|
| 0 | 0x400 | 8 B | 4 | estéreo | 1017 x2 | /2 por selección | 22050 | 7,95:1 |
| 1 | 0x400 | 4 B | 3 | mono | 2721 | ninguno | 44100 | 10,63:1 |
| 2 | 0x200 | 4 B | 4 | mono | 1017 | /2 por selección | 22050 | 15,89:1 |
| 3 | 0x200 | 4 B | 2 | mono | 2033 | /2 por media | 22050 | 31,77:1 |
| 4 | 0x100 | 4 B | 2 | mono | 1009 | /4 por media | 11025 | 63,06:1 |

**El propio conversor confirma esta tabla**: el desplegable "Mode" del
Music Converter 1.30 ofrece exactamente `8:1 Stereo`, `11:1 Mono`, `16:1 Mono`,
`32:1 Mono` y `64:1 Mono`, que son los cinco ratios calculados aquí en el mismo
orden. Es confirmación independiente, y en particular del modo 2: **16:1, no
32:1** como decía una versión anterior de este documento.

Cada bloque consume una cantidad exacta de bytes de entrada: 0x1FC8, 0x2A84,
0x1FC8, 0x3F88 y 0x3F10 respectivamente. La primera muestra del bloque va en
la cabecera, las demás codificadas: `muestras = 1 + codificadas`.

**Ojo con el diezmado**: los modos 0 y 2 **seleccionan** una muestra de cada
dos, mientras que los modos 3 y 4 **promedian** (`FUN_100026e0`, media de
`n/2` muestras del mismo canal). No es lo mismo y un conversor que promedie
donde el original selecciona no producirá ficheros equivalentes.

## Cabecera de bloque

    u16  predictor + 0x8000       (el predictor vive en 0..65535)
    u16  indice del cuantizador

En el modo 0 se repite para el segundo canal: `predL, idxL, predR, idxR`.
En los modos 2, 3 y 4 el índice se **acota a 0xA0** al escribir la cabecera.

La muestra de salida es `predictor - 0x8000`.

## Empaquetado

- **Modo 0**: un byte por par estéreo, **nibble bajo = izquierdo**, alto = derecho.
- **Modo 1**: grupos de 8 códigos de 3 bits en **24 bits big endian** (3 bytes).
  El primer código va en los bits más bajos: `codigo[k] = (V >> 3*k) & 7`.
  340 grupos por bloque.
- **Modo 2**: un byte por dos muestras, nibble bajo primero.
- **Modos 3 y 4**: un byte por cuatro muestras, la primera en los bits 0-1.

## Cuantizadores

**4 bits** (`FUN_10002310`) y **3 bits** (`FUN_100024c0`) son IMA ADPCM
estándar sobre la tabla de 89 pasos, bit-idéntica a la de referencia:

    4 bits: diff = paso>>3; bit2->+paso; bit1->+paso/2; bit0->+paso/4; bit3 = signo
    3 bits: diff = paso>>2; bit1->+paso; bit0->+paso/2; bit2 = signo

    IDX4 = [-1,-1,-1,-1, 2, 4, 6, 8, -1,-1,-1,-1, 2, 4, 6, 8]
    IDX3 = [-1,-1, 2, 6, -1,-1, 2, 6]

El índice se acota a **[0, 88]** y el predictor a **[0, 0xFFFF]**.

**2 bits** (`FUN_10002730`) **no es IMA**. Usa una tabla de deltas propia de
89 filas de 4 entradas, `[+corto, +largo, -corto, -largo]`, con el código como
`signo*2 + magnitud`:

    predictor += DELTA2[indice + codigo]
    indice    += (codigo & 1) ? +4 : -4        acotado a [0, 0x160]

Es decir el índice avanza de 4 en 4 (una fila) y el número de filas, 89,
coincide con el de la tabla IMA. Las filas altas de la tabla desbordan el
int16 y hay que reproducirlas tal cual. Está en `gbs_tables.py`.

## Opciones del INI

`[SaveMusic]`: `MusicMode` (0..4), `Channel` (0 = izquierdo, 1 = derecho) y
`Volume` (0..3). Se corresponden uno a uno con la interfaz:

| Control | Valores | Clave |
|---|---|---|
| Mode | 8:1 Stereo / 11:1 Mono / 16:1 Mono / 32:1 Mono / 64:1 Mono | `MusicMode` 0..4 |
| Channel | Left / Right | `Channel` 0/1 |
| Volume | Normal / Twice / Four Times / Eight Times | `Volume` 0..3 = x1, x2, x4, x8 |

`Channel` desplaza el puntero de entrada un `short` (`FUN_10002560`), de modo
que la media se hace **siempre sobre muestras del mismo canal**, no sobre una
mezcla. Solo aplica a los modos mono, como avisa la propia ayuda del programa.
`Volume` multiplica con saturación en `FUN_10002840`.

Las tres son opciones **de codificación**: no cambian el formato y el
decodificador no necesita conocerlas.

## Validación

**Los cinco modos están validados sobre ficheros reales**, todos generados a
partir del mismo `furretwalk.wav` (Channel Left, Volume Normal), lo que permite
compararlos entre sí.

Las cinco duraciones coinciden, lo que ya valida tamaños de bloque, cuentas de
muestras y frecuencias: si alguno de esos números estuviera mal, la duración
saldría desviada por un factor entero.

| Fichero | Modo | Hz | Muestras | Duración | Correlación con el modo 0 | RMS |
|---|---|---|---|---|---|---|
| `furretwalk.gbs` | 0 | 22050 est. | 2373678 | 107,65 s | (referencia) | 5256 |
| `furretwalk_mono11.gbs` | 1 | 44100 | 4748145 | 107,67 s | 0,9988 | 5251 |
| `furretwalk_mono16.gbs` | 2 | 22050 | 2373678 | 107,65 s | **1,0000** | 5256 |
| `furretwalk_mono32.gbs` | 3 | 22050 | 2372511 | 107,60 s | 0,9901 | 5069 |
| `furretwalk_mono64_l.gbs` | 4 | 11025 | 1186584 | 107,63 s | 0,9759 | 5667 |

### El modo 2 es bit-idéntico al canal izquierdo del modo 0

No se parece: **es exactamente el mismo**. De las 2373678 muestras, **cero
difieren**. Tiene sentido, porque el modo 2 usa el mismo cuantizador IMA de
4 bits y el mismo diezmado por selección que cada canal del modo 0.

Es la validación más fuerte disponible, y confirma de golpe cuatro cosas: el
cuantizador de 4 bits, el diezmado por selección (elige las mismas muestras),
el convenio del predictor con sesgo +0x8000, y **que en el modo 0 el nibble
bajo es el canal izquierdo** — que hasta ahora solo se sabía por el código.

### Resto de modos

- **Modo 1** (3 bits, empaquetado de 8 códigos en 24 bits big endian): 0,9988.
  Era el único camino del formato que no se había ejecutado nunca, porque es el
  único que usa el cuantizador de 3 bits. Queda validado.
- **Modos 3 y 4** (2 bits, tabla de deltas propia): 0,9901 y 0,9759. La pérdida
  es simplemente el ruido de cuantización a 32:1 y 64:1.
- **Opción `Channel`** con `furretwalk_mono64_l.gbs` y `_r.gbs`: mismo tamaño,
  misma estructura, difieren a partir del byte 13149. La fuente es casi mono
  (|L-R| medio 2,0 sobre RMS 6162), así que la prueba confirma que la opción
  actúa y no altera el formato, pero no distingue qué canal es cuál. Eso lo
  resuelve el modo 2, arriba.

### El codificador nuevo reproduce los seis ficheros byte a byte

No hacía falta el WAV original que se le dio al conversor. El cuantizador es
determinista y su salida es alcanzable, así que basta con decodificar un `.gbs`
original y construir con él una entrada de 44100 Hz que el diezmado del modo
devuelva intacta: repetir cada muestra `diezmado` veces, cosa que **deshacen por
igual la selección y la media**. Codificar esa entrada tiene que devolver el
fichero de partida.

Devuelve **exactamente** el fichero de partida, en los seis y enteros, cabecera
incluida. Eso valida de una vez el diezmado, la cabecera de bloque, el recorte
del índice a 0xA0, los tres cuantizadores y los tres empaquetados. Está en
`gbamedia/tests/test_gbs_codificador.py`.
