[English](GBM_FORMAT.md) · **Español**

# Formato .gbm (GBA Movie Player) — RESUELTO

Descifrado a partir del **decodificador de la ROM** `FilmPlay.gba`
(`0x08120000`–`0x08122e9c`), mucho más legible que el codificador
`Gbamvico.dll`, y **validado sobre 2715 frames** de tres videos reales
generados con el conversor original.

Implementación de referencia: `gbm_decode.py` (decodifica y vuelca PNG).

## Contenedor

Cabecera global de **0x200 bytes**:

    0x00  "GBAM"          (el magic del audio es "GBAL"; no se comparten)
    0x04  u32  tamano total del fichero
    0x08  "MOVI"
    0x0C  u32  cero
    0x10  u32  Mode
    0x14  ceros hasta 0x200

No lleva dimensiones, fps ni número de frames: el reproductor asume
**240x160 a 10 fps**. Los fps quedan confirmados al cuadrar la duración del
`.gbs` con el número de frames del `.gbm` en los tres videos (63,05/63,00 s,
107,70/108,00 s y 100,45/100,50 s).

A partir de 0x200, secuencia de frames de longitud variable que **tesela
exactamente** hasta el último byte del fichero:

    u16  longitud del payload
    u8   payload[longitud]

Un video es un par de ficheros: `Mnnnnn.gbm` + `Mnnnnn.gbs` (audio, ver
`GBS_FORMAT.es.md`).

## Payload de un frame

    off 0            u16  tam_bitstream (bytes, multiplo de 4)
    off 2            u16  tam_colores   (bytes, multiplo de 2)
    off 4            u32  bitstream[]
    ...              u16  colores[]      BGR555 nativo de GBA
    ...              u8   vectores[]     indices a la tabla de movimiento

- **bitstream**: se lee **MSB primero, 32 bits por palabra u32** little endian.
  Los bits sobrantes de la última palabra son relleno (siempre < 32).
- **colores**: `((b>>3)*32 + (g>>3))*32 + (r>>3)`, es decir azul en los bits
  10-14, verde en 5-9 y rojo en 0-4. Bit 15 siempre a cero. Van listos para
  copiarse al framebuffer sin conversión.
- **vectores**: un byte por bloque con movimiento, índice en una tabla de 256
  desplazamientos. En calidad alta va vacío, pero **en calidad baja se usa
  intensivamente** (701810 bytes en `M00006.gbm`) y se consume exacto.

## El codec: árbol binario de partición sobre bloques de 8x8

El frame se recorre en **orden raster de bloques de 8x8**: 30 columnas x 20
filas = **600 bloques**. Cada bloque es la raíz de un árbol binario que se
parte hasta llegar a una hoja. Las formas posibles son todas las `w x h` con
`w, h` en {1, 2, 4, 8}: 15 en total, y la ROM tiene **una función por forma**:

| Forma | Función | Forma | Función | Forma | Función |
|---|---|---|---|---|---|
| 8x8 | (0x081205a0, inicio perdido) | 8x4 | `0x08121494` | 4x8 | `0x08120f5c` |
| 8x2 | `0x08120940` | 4x4 | `0x08120c28` | 2x8 | `0x08120628` |
| 8x1 | `0x08122600` | 4x2 | `0x081221c4` | 2x4 | `0x08121fdc` |
| 1x8 | `0x0812239c` | 4x1 | `0x08121c98` | 2x2 | `0x081219d4` |
| 1x4 | `0x08121b24` | 2x1 | `0x08121ee0` | 1x2 | `0x08121de8` |

### Código de bits de un nodo (bloques de más de 2 píxeles)

    0 0            copiar del frame anterior, misma posicion
    0 1            copiar del frame anterior con vector (consume 1 byte)
    1 0 [dir]      partir en dos mitades
    1 1 0          copiar con vector y sumar un color (consume 1 byte + 1 color)
    1 1 1          relleno solido con un color (consume 1 color)

El bit `dir` **solo existe si ambas dimensiones son mayores que 1**:
`0` = partición vertical (mitad superior y mitad inferior), `1` = partición
horizontal (mitad izquierda y mitad derecha). Una fila (`h == 1`) solo se puede
partir horizontalmente y una columna (`w == 1`) solo verticalmente, y en esos
casos el bit no se emite. Este detalle es imprescindible: sin él, el bitstream
se desincroniza al segundo bloque.

### Hojas de 2 píxeles (2x1 y 1x2)

Ya no hay partición, así que el último nivel cambia de significado:

    0 0            copiar del frame anterior
    0 1            copiar con vector
    1 0            copiar con vector y sumar un color
    1 1 0          los dos pixeles con el mismo color
    1 1 1          un color propio para cada pixel (consume 2 colores)

### Suma de color

La ROM empaqueta el color en las dos mitades de una palabra
(`orr r8, r8, r8, lsl #16`) y suma de 32 en 32 bits, de modo que el acarreo
entre componentes **no se recorta**. Un codificador nuevo debe reproducir esa
aritmética exacta si usa este modo.

### Tabla de vectores (confirmada)

`r7` apunta a 256 desplazamientos en bytes que se suman al puntero del frame
anterior. El contenido no se puede leer (queda en la zona perdida de la ROM),
pero se ha deducido y confirmado con `M00006.gbm`:

    dx = (indice & 15) - 8          rango [-8, +7]
    dy = (indice >> 4) - 8          rango [-8, +7]
    desplazamiento = dy * 480 + dx * 2      (bytes)

Dos pruebas independientes:

1. **Histograma de índices**: pico agudo en `0x88` (6,27%, más de 4 veces el
   siguiente), que es exactamente `dx=0, dy=0`. Los siguientes son sus vecinos
   inmediatos `0x87`, `0x89`, `0x98`, `0x78`. La distribución es una estrella
   2D centrada en el "sin movimiento", como corresponde a vectores reales.
2. **Discontinuidad en los bordes de bloque** sobre frames decodificados,
   comparando candidatas. Una tabla equivocada desplaza bloques y sale peor
   que no aplicar movimiento:

   | Tabla | Exceso de discontinuidad |
   |---|---|
   | dx = nibble bajo, dy = alto | **+0,37** |
   | nibbles intercambiados | +4,61 |
   | origen en 7 | +3,46 |
   | ignorar los vectores (control) | +1,91 |

## Cola de los frames 20 a 27

El codificador añade **0x1002 bytes** al payload de los frames 20 a 27: 4096
bytes de una tabla interna (`DAT_100152d8`, 8 bloques de 4 KB = 32 KB) con XOR
de cada u16 contra un `rand()` sembrado con el tamaño del frame, más la propia
clave al final.

**Es inerte para la reproducción.** Cae justo donde iría el flujo de vectores,
que no se usa, y el decodificador nunca lo lee: los flujos de bits y colores se
consumen exactamente hasta el final en los ocho frames. Un conversor nuevo
puede omitirlo.

## Efecto de las opciones del conversor

Las claves de `[SaveMovie]` en `GBAMedia.ini` y sus valores por defecto son
`FullOut`, `ChangeScale`, `ImageV=20`, `ImageH=30`, `FrameSize=8192`,
`Scale=1`, `Mode=0`, `S=2`, `Enhance=10`, `Brightness`, `Contrast=75`.
**Ninguna cambia la sintaxis del formato.**

- **`ImageH` / `ImageV`** (en bloques de 8; se multiplican por 8 y se acotan a
  [8,240] y [8,160]) solo se referencian, fuera del lector del INI, en
  `0x10003630` y `0x10003646`: el **escalador** de entrada, junto a
  `ChangeScale`. No aparecen en el codec. Controlan a qué tamaño se escala la
  imagen dentro del búfer, no la rejilla de bloques, que es **siempre 30x20**.
  Coherente con que el tamaño de muestra de salida se fija incondicionalmente
  a `0x12C00` = 240*160*2 y con que la cabecera no tiene dónde guardar unas
  dimensiones.
- **`Scale`** es el selector de calidad. Se referencia en el codec
  (`0x100052dc`, `0x10005632`, `0x1000589a`, `0x1000599e`), pero solo afecta a
  los **umbrales de decisión**, al número de pasadas de recuantización y al
  tope duro por frame. Las cuatro ramas llaman al mismo compresor con los
  mismos argumentos y acaban en el mismo serializador.

  | `Scale` | Pasadas | Tope duro |
  |---|---|---|
  | 0 | 10 | 0x4000 |
  | 1 | 6 | **0x8000** |
  | 2 | 8 | 0x4000 |
  | 3-5 | 6 | 0x4000 |

  La interfaz del Movie Converter 1.30 no expone `Scale` directamente: ofrece
  tres presets, que además fijan el modo de audio del `.gbs` compañero:

  | Preset | Audio del `.gbs` | Ejemplo |
  |---|---|---|
  | High Quality Mode | `MusicMode` 0 (8:1 estéreo) | `M00001`, `M00004`, `M00005` |
  | Standard Mode | `MusicMode` 2 (16:1 mono) | `M00008` |
  | High Compression Mode | `MusicMode` 4 (64:1 mono) | `M00006` |

  Hay además una casilla "Manual Setting" que da acceso a los parámetros
  sueltos, y un límite de tamaño de salida (256 MB por defecto) para trocear.

### Qué hacen de verdad los cinco parámetros de calidad

Son **tolerancias de diferencia**, una por banda de tamaño de bloque, y se
consultan en `FUN_100051d7` (y sus gemelas en `0x100055b4` y `0x10005916`):
según el nivel se elige `ca27e8`, `ca27ec`, `ca27f0`, `ca27f4` o `ca27f8`, y el
bloque se acepta si las diferencias por encima del umbral son nulas. Además
`Scale == 1` toma una rama **estrictamente más exigente**: exige que dos
contadores sean cero, mientras el resto de calidades solo exige uno.

Comparando `M00004` (alta) y `M00008` (estándar), que son **el mismo video**
de 630 frames:

| | Alta | Estándar |
|---|---|---|
| Hojas totales | 1014570 | 707105 |
| Hojas por bloque de 8x8 | 2,68 | 1,87 |
| Copia con vector de movimiento | **0 %** | **24,2 %** |
| Bloques 8x8 que no se parten | 29,5 % | 43,1 % |
| Hojas de 1 o 2 píxeles | 39,3 % | 9,6 % |
| Payload medio | 1583 B | 1181 B |
| PSNR frente al AVI original | 32,3 dB | 31,8 dB |

Las dos diferencias de fondo son que **la calidad alta no usa compensación de
movimiento en absoluto** y que subdivide hasta parejas de píxeles, mientras que
la estándar acepta copias con vector en un cuarto de sus hojas y deja el 43 %
de los bloques enteros. La causa es la misma: con tolerancia cero y el test
estricto, una copia desplazada casi nunca se acepta y el codificador cae a
colores explicitos.

En rendimiento la ventaja es escasa: **un 34 % más de bytes por 0,4 dB**. La
medida es sobre el patrón de sincronía, que es gráfico sintético; en video real
la diferencia podría ser mayor.

**Para el conversor**: la búsqueda de vectores solo hace falta si se quiere
imitar la calidad estándar o baja. Un codificador que apunte a calidad alta
puede prescindir de ella por completo.

  El efecto práctico es el tamaño: el payload medio pasa de 12786 B por frame
  en calidad alta a **2463 B** en calidad baja, y la calidad baja compensa
  usando vectores de movimiento, que la alta no usa.
- **`Brightness`, `Contrast`, `Enhance`** son preproceso de píxel.
- El campo `Mode` de la cabecera vale **4 en los seis ficheros**, tanto en
  calidad alta como baja. Lo escribe el EXE, no la DLL. Un conversor nuevo
  emite 4.
- El estéreo/mono solo afecta al `.gbs`, que es un fichero aparte.

## Sin reinicio periódico de la referencia

El bucle por frame del codificador pone su referencia a negro cada 600 frames
en vez de actualizarla. Eso **no** exige tratamiento en el decodificador: se
autocorrige, porque contra una referencia negra el codificador acaba emitiendo
colores explicitos en todas partes. Verificado decodificando `M00001` entero;
el frame 1000 sale sin deriva alguna.

## Validación

`gbm_decode.py` sobre los siete `.gbm` disponibles, que cubren los tres presets
del conversor:

| Fichero | Frames | Preset | Usa vectores | Payload medio |
|---|---|---|---|---|
| `M00000` / `M00001` / `M00003` | 1080 | alta | no | 12784 B |
| `M00004` | 630 | alta | no | 1583 B |
| `M00005` | 1005 | alta | no | 8891 B |
| `M00006` | 1005 | compresión | 1004 frames | 2463 B |
| `M00008` | 630 | estándar | 627 frames | 1181 B |

**6510 frames en total.** En todos ellos:

- El flujo de colores se consume **hasta el último byte exacto**.
- Los bits sobrantes son siempre menos de 32 (relleno de la última palabra).
- Los frames teselan exactamente hasta el final del fichero y el campo de
  tamaño de la cabecera cuadra con el tamaño real en los siete.
- El flujo de vectores se consume entero salvo la cola de 4098 bytes de los
  frames 20 a 27.
- Las imágenes son correctas, incluido texto pequeño legible en el patrón de
  sincronía de `M00004` y `M00008`.

### Tres frames con un byte de vector sin leer

`M00004` (358 y 558) y `M00006` (625) dejan **1 byte** sin consumir en el flujo
de vectores. No es un fallo del decodificador: `M00004` **no usa vectores en
ningún frame**, y aun así dos de los suyos traen un byte suelto ahí. Es un byte
que el codificador escribe y que nadie referencia. Los colores se consumen
exactos en los tres y las imágenes salen bien.

## Zona perdida de la ROM

`0x08104000`–`0x08120000` está a ceros y `0x08120000`–~`0x081204xx` a 0xFF en
las tres copias de la ROM disponibles. Ahí caen el bucle por frame (que fija
punteros y orden de recorrido), la rutina de recarga de bits `0x0811fc80`, el
inicio de la función 8x8 y la tabla de vectores. Todo ello se ha reconstruido
por analogía con las 14 formas que sí están completas y se ha **confirmado
empíricamente** contra los ficheros reales.

## Lo que necesita un conversor nuevo

1. Escalar a 240x160 y cuantizar a BGR555.
2. Por frame, recorrer 600 bloques de 8x8 y decidir el árbol de partición
   (el original usa un umbral de diferencia y reintenta el frame subiéndolo
   de 24 en 24 hasta que cabe en `FrameSize`, acotado a [0x400, 0x8000]).
3. Emitir bitstream (32 bits por palabra, MSB primero), colores y, si se
   quiere igualar la calidad baja, vectores de movimiento con la tabla de
   arriba. Los vectores son opcionales: un codificador que no los use produce
   ficheros válidos, solo más grandes.
4. Cabecera de 0x200, frames con prefijo `u16`, y el `.gbs` a 10 fps de video.

## El codificador nuevo

`gbamedia/src/gbamedia/core/gbm_encode.py`. Sigue la semántica deducida aquí:
tolerancia de diferencia por banda de tamaño, hoja aceptada si ninguna
diferencia la supera, y reintento del frame subiendo la tolerancia hasta caber
en `FrameSize`. Tres diferencias deliberadas con el original:

1. **La tolerancia se mide en las 5 componentes de BGR555**, no en 8 bits, así
   que el paso de reintento es 1 y no 24. Un salto de 24 sobre 32 niveles sería
   pasar de sin pérdida a cualquier cosa en una sola pasada.
2. **La búsqueda de vectores se hace una vez por frame**, no una por pasada: no
   depende de la tolerancia salvo por el conjunto de bloques activos, y ese solo
   se encoge según la tolerancia sube. Y solo se buscan vectores para los
   bloques cuya copia directa **no** cae ya dentro de la tolerancia, porque en
   los demás el nodo de 8x8 se resuelve como copia y no se llega a bajar.
   Las dos cosas juntas bajaron la suite de pruebas de 168 s a 16 s.
3. **La cola inerte de los frames 20 a 27 no se emite.**

El candidato "vector + suma de color" se valora **aplicándolo y midiendo**, con
la aritmética empaquetada de la ROM (`(ref + delta) & 0xFFFF`), en vez de
razonar por componentes. Es la única forma honesta de tratar un acarreo que no
se recorta.

### Medido sobre el patrón de sincronía

Mismo material y misma referencia para los cuatro, 120 frames:

| | PSNR | Payload medio |
|---|---|---|
| `M00004` (original, alta) | 28,77 dB | 1693 B |
| **nuestro, alta** | **sin pérdida** | **1011 B** |
| `M00008` (original, estándar) | 28,63 dB | 1339 B |
| **nuestro, estándar** | **38,37 dB** | **880 B** |

La calidad alta sale **matemáticamente sin pérdida** en BGR555: con tolerancia
cero toda hoja tiene que ser exacta, y la hoja de 2 píxeles con dos colores
propios siempre lo es. Y aun así ocupa un 40 % menos que el original.

Velocidad: 86 ms por frame en calidad alta y 299 ms en estándar, o sea unos 90 s
y 5 min para un video de 1080 frames.

### Ida y vuelta exacta

Lo que garantiza que no haya deriva no es el PSNR sino esto: se decodifica cada
fichero producido con el decodificador de referencia y se comprueba que
reconstruye **exactamente** lo que el codificador creía estar dejando, además de
consumir los tres flujos hasta el último byte. Comprobado sobre material real y
sobre ruido puro, en los tres presets.

El ruido puro es el caso límite del formato: cada pareja de píxeles pediría dos
colores propios, 76 800 bytes solo de color, y los campos de tamaño son u16. El
control de tamaño sube la tolerancia hasta que cabe, igual que hace con
`FrameSize`.
