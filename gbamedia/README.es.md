[English](README.md) · **Español**

# gbamedia

Conversor de video y música a los formatos `.gbm` y `.gbs` de GBA Movie Player,
para tarjetas EZ Flash Omega/DE. Una sola aplicación: decide qué hacer según el
fichero de entrada.

Los formatos, sacados por ingeniería inversa, están en
[`re_gbamedia/GBM_FORMAT.es.md`](re_gbamedia/GBM_FORMAT.es.md) y
[`GBS_FORMAT.es.md`](re_gbamedia/GBS_FORMAT.es.md); ahí está el porqué de casi
todo lo que hace este código.

## Desarrollo

Todo dentro del `venv` del proyecto, nada global:

    make venv        # crea .venv, instala en modo editable y compila el C
    make c           # recompila la extension despues de tocar el .c
    make test        # suite rapida
    make puro        # la misma suite sin el nucleo en C
    make lento       # recorre los ficheros originales enteros

La extensión en C es **opcional**: si no hay compilador el paquete se instala
igual y todo funciona con el núcleo de Python, más despacio. `GBAMEDIA_PURO=1`
la desactiva aunque esté compilada, que es como se comparan las dos.

## Uso

    gbamedia video.mp4 cancion.mp3 -v /sd/MEDIA/videos -m /sd/MEDIA
    gbamedia --solo-analizar video.mp4      # avisos de cadencia, sin convertir
    gbamedia video.mp4 --bpm 140:150        # arregla el resbalon de la animacion
    gbamedia carpeta/ --preset compresion --verificar
    gbamedia video.mp4 --arreglar-cadencia  # aplica lo que propone el aviso
    gbamedia video.mp4 --trabajos 4         # cuantos trabajadores usar

Sin argumentos abre la ventana; con ellos hace de conversor de terminal. Un
video da un par `.gbm` + `.gbs`; cualquier otra cosa, un `.gbs` suelto.
`gbamedia --help` lista todo.

### Cómo se llama lo que sale

Con el nombre del fichero de origen, recortado a 8.3:
`furret walk (full version)_360p.mp4` -> `furretwa.gbm` + `furretwa.gbs`.

El `Mnnnnn` del conversor original **no es obligatorio**: el listado de
FilmPlay filtra por extensión (tabla `GBM/GBS/WAV/TXT` en `0x080C11F4`,
validado en el emulador) y admite cualquier nombre; comprobado en mGBA con
`CORTO.GBM` y `FURRET~1.GBM` junto a los `M0000n`, todos listados y
reproducibles. El **modo de audio** tampoco está atado al preset de video como
en el conversor original: viaja en la cabecera del `.gbs` y el reproductor lo
respeta, comprobado con las dos combinaciones que ningún fichero original usó
(compresión + 8:1 estéreo, y alta + 11:1 mono). Lo que sí impone la ROM es el **8.3**: lee entradas de
directorio cortas, así que un nombre largo se ve en la consola como
`FURRET~1.GBM`. Por eso se recorta aquí: lo que se elige es lo que se lee en la
GBA.

Convertir dos veces el mismo fichero **reemplaza** su salida en vez de dejar
otra al lado. Dos orígenes distintos que se recorten al mismo nombre se
resuelven con un sufijo (`furretwa`, `furretw2`). Con `--numerar` se vuelve a
la numeración `Mnnnnn`, y `--nombre` fija uno concreto.

### Velocidad

El codec vive en una extensión en C (`src/gbamedia/core/_fast.c`): el árbol
de partición, la búsqueda de vectores, el ADPCM y el decodificador de
verificación. El equivalente en Python se queda como **implementación de
referencia** -es la que se lee para entender el formato- y las pruebas exigen
que las dos den el **mismo byte**, no un resultado parecido.

Además, un video se corta en trozos de 25 frames que se reparten entre todos
los núcleos. El formato no tiene keyframes -el decodificador solo aplica
diferencias- así que un trozo que arranca contra un framebuffer negro se
describe entero y sale un fichero igual de válido; el conversor original hacía
lo mismo cada 600 frames por su cuenta. Cuesta un 1-2 % de bytes y no se nota
en la calidad (31,90 dB con y sin trocear, sobre 30 s de video real).

Medido en esta máquina (16 núcleos) con un video de 107 s:

| | por frame, un núcleo | el video entero |
|---|---|---|
| numpy, sin repartir | 515 ms | 9 min 14 s |
| numpy repartido | 515 ms | 38 s |
| C, un solo hilo | 7,2 ms | 9,8 s |
| **C repartido** | **7,2 ms** | **3,8 s**, con `--verificar` incluido |

O sea 28 veces más rápido que ver el video. El audio va a unas 900 veces
tiempo real y el decodificador de verificación, 100 veces más rápido que el de
Python.

`--trabajos N` limita los trabajadores y `--trozo N` el tamaño del trozo (`0`
no trocea). Con el núcleo en C se reparte entre **hilos** -el C suelta el GIL,
y así los frames no hay que copiarlos a ningún sitio-; sin él hacen falta
procesos. La música no se trocea, porque el ADPCM es secuencial de cabo a
rabo, pero varias canciones se convierten a la vez.

### Lotes

Las opciones van en tres capas, de menor a mayor prioridad:

    valores por defecto  <  perfil del lote  <  sobrescritura por fichero

Y los valores por defecto son dos juegos, uno para video y otro para música:
casi nada de lo que decide un video le importa a un mp3. Un manifiesto de lote
es un JSON con todo ello:

```json
{
  "perfil_video": { "preset": "estandar" },
  "perfil_musica": { "modo_audio": 0 },
  "salida": { "video": "/sd/MEDIA/videos", "musica": "/sd/MEDIA" },
  "ficheros": [
    "intro.mp4",
    { "origen": "baile.mp4", "opciones": { "tempo": 1.071429 } },
    { "origen": "tema.mp3", "opciones": { "modo_audio": 1 }, "nombre": "tema" }
  ]
}
```

    gbamedia --lote lote.json
    gbamedia carpeta/ -p estandar --guardar-lote lote.json   # lo escribe

Es el mismo formato que usa la ventana, así que un lote preparado a mano se
abre en la interfaz y al revés. Las rutas se leen relativas al manifiesto. Un
`"perfil"` a secas (el formato viejo) vale para las dos clases.

### Idiomas

Español e inglés. Por defecto, el del sistema: español si el sistema está en
español, inglés en cualquier otro caso. Se cambia con el menú **Idioma** de la
ventana -que recuerda la elección- o con `--idioma es|en` en la terminal; la
variable `GBAMEDIA_IDIOMA` manda sobre las dos.

Las cadenas originales son las españolas del código y el catálogo inglés está
en `src/gbamedia/languages/en.py`. `tests/test_i18n.py` saca del código todas las
llamadas a `_()` y falla si alguna no está traducida, que es lo que evita que
se quede media ventana en español.

### Modo simple y DEBUG_ON

Los avisos de cadencia (fps y BPM) y sus controles -mezclar frames, factor de
tempo- **no se enseñan** salvo que exista un fichero llamado `DEBUG_ON` junto
al ejecutable. La heurística de cadencia puede errar con material real y
proponer una corrección disparatada, y un aviso equivocado manda a estropear
un video que estaba bien. Las opciones siguen funcionando en la terminal
aunque no se anuncien en `--help`.

### La ventana

    make gui

En Linux, Qt 6.5+ carga su plugin de X11 con `dlopen` y necesita una librería
del sistema que muchas distribuciones mínimas (WSL incluida) no traen:

    sudo apt install libxcb-cursor0

Sin ella la ventana no abre y Qt dice "no Qt platform plugin could be
initialized". La línea de órdenes funciona igual sin instalar nada.

Lista de ficheros a la izquierda, parámetros del seleccionado a la derecha. Sin
selección se editan los **valores por defecto**, que tienen una pestaña para
video y otra para música y enseñan solo los grupos que le importan a cada clase.
Con varios ficheros seleccionados se editan todos a la vez y los campos que no
coinciden se marcan con "(varios)". Cada control tiene un boton ↺ para volver
al valor del lote.

La primera fila de la lista son los **valores por defecto**, con sus dos
pestañas; seleccionar ficheros enseña los suyos.

Se convierte con **Convertir todo** o con **Convertir selección**, y el menú
del boton derecho sobre la lista ofrece además volver a convertir uno ya hecho
-que reemplaza su salida-, analizar su cadencia sin convertirlo, y abrir la
carpeta de destino. La carpeta se pregunta la primera vez que hace falta -no hay destino por
defecto invisible, que era lo que hacía imposible encontrar lo convertido- con
un diálogo que según una casilla pide una ruta o dos, y otra para poner los
videos en una subcarpeta `videos/`. Ninguna de las dos cosas es obligatoria: la
ROM lista por extensión y el árbol le da igual.

Lo que sí importa es que **FilmPlay empareja un `.gbm` con el `.gbs` que se
llama igual**, así que con video y música en la misma carpeta un `.gbs` de
música llamado como un video pasaría a ser su banda sonora. Antes de convertir
se comprueba y se avisa, tanto en la ventana como en la terminal.

Mientras convierte, la lista marca cada fichero con su estado (`·` pendiente,
`▶` en curso con su porcentaje, `✓` hecho con los ficheros que ha dejado, `✗`
fallido con el motivo) y abajo van el fichero en curso, lo que queda y dos
barras: la del fichero y la del lote. El botón pasa a **Parar**, que suelta los
trozos que no han empezado y avisa a los que sí, así que corta en menos de un
segundo y no deja nada a medias. Cerrar la ventana **con una conversión en
marcha** pregunta antes de cortarla; con la lista cargada y quieta, no molesta.

Los avisos de cadencia salen en el panel del fichero con un botón **Aplicar**
que escribe el ajuste que hace falta: nadie tiene que copiar a mano un factor
de tempo de seis decimales. En la terminal, lo mismo con `--arreglar-cadencia`.

## Empaquetado

    make dist

Deja `dist/gbamedia/` con dos ejecutables: `gbamedia` (consola) y
`gbamedia-gui` (sin consola, para el acceso directo). `ffmpeg` y `ffprobe` se
copian de `bin/` y se localizan por ruta relativa al ejecutable, nunca por
`PATH`. **PyInstaller 6 mete todo lo empaquetado en `_internal/`**, así que en
el paquete acaban en `dist/gbamedia/_internal/bin/`; ahí es donde los busca el
localizador (`sys._MEIPASS/bin`), y por eso al lado del `.exe` solo se ven los
dos ejecutables. La extensión en C viaja dentro del paquete, compilada en la plataforma
que construye cada binario.

### Windows sin salir de WSL

Si el anfitrión es Windows con WSL2, no hace falta ni máquina virtual ni CI:

    ./packaging/windows.sh

(o `make windows`) copia el árbol a una carpeta de Windows -`C:\gbamedia-build`
por defecto; `DESTINO=` o `packaging/local.env` la cambian- y monta ahí un
venv con el Python de Windows, **compila la extensión en C con
MSVC**, baja `ffmpeg.exe` y `ffprobe.exe` (compilación GPL de BtbN, alojada en
GitHub), pasa la suite y deja `dist\gbamedia\gbamedia.exe`. Requiere Python
3.11+ y las Build Tools de Visual Studio en el lado de Windows; `PYWIN=` cambia
el intérprete.

El `.gbm` que produce el binario de Windows es **byte a byte idéntico** al de
Linux (comprobado con MSVC/cp311 contra gcc/cp312): el codec es aritmética
entera de principio a fin, así que cualquier diferencia sería un error de
portabilidad, no una licencia para que varíe.

Los paquetes de las tres plataformas los construye
`.github/workflows/package.yml` con una matriz de GitHub Actions: zip en
Windows, zip en macOS y AppImage en Linux. Linux se compila en la imagen más
vieja razonable, porque el binario solo corre en glibc igual o más nueva que la
de la máquina que lo construyó.

macOS sin firmar exige abrir la primera vez con el botón derecho; evitarlo
necesita una cuenta de desarrollador de Apple.

Las pruebas doradas usan los `.gbm`/`.gbs` generados con el conversor original.
Se buscan en `../ezfode_sd/MEDIA`; con `GBAMEDIA_ORIGINALES` se apunta a otro
sitio. Si no están, esas pruebas se saltan.

## Estado

| Fase | Qué | Estado |
|---|---|---|
| 0 | Andamiaje y pruebas doradas | hecho |
| 1 | Codificador de audio `.gbs` | hecho, **byte a byte** |
| 2 | Codificador de video `.gbm` | hecho |
| 3 | Entrada moderna, escalado y cadencia | hecho |
| 4 | CLI | hecho |
| 5 | GUI | hecho |
| 6 | Lotes | hecho |
| 7 | Empaquetado | hecho |
| 8 | Núcleo en C | hecho, **byte a byte** contra el de Python |

## Probado en el emulador

Los ficheros que produce el conversor se reproducen en mGBA con el
decodificador de la ROM, servidos desde una tarjeta virtual construida con el
proyecto de la **tarjeta SD virtual** (repositorio aparte): construye la
imagen, engancha el blob del parche (`_EZFO_startUp` y `_EZFO_readSectors`, con
las direcciones sacadas de `ezfo-patch/ezfo.sym`) y sirve los sectores desde
ella.

| | |
|---|---|
| ![menú](screenshots/menu.png) | ![listado](screenshots/listing.png) |
| El menú de FilmPlay | El listado, con los tamaños correctos |
| ![video](screenshots/video-high.png) | ![vectores](screenshots/video-vectors.png) |
| Preset alta: texto pequeño legible | Preset estándar, con compensación de movimiento |
| ![troceado](screenshots/video-chunked.png) | ![música](screenshots/music.png) |
| El mismo video repartido en trozos de 25 frames | Un `.gbs` de un mp3, con su duración |

| Prueba | Fichero | Resultado |
|---|---|---|
| Listado | ambos | tamaños correctos: `M00000.GBM` 615 KB, `M00001.GBM` 1255 KB |
| Video sin pérdida | `M00000` (preset alta, 300 frames) | se reproduce; texto pequeño legible |
| Video con vectores | `M00001` (preset estándar, 280 frames) | se reproduce limpio, sin deriva ni bloques desplazados |
| Video troceado | `M00001` en trozos de 25 frames | igual de limpio: las costuras no se ven (los frames de corte pierden 1,8 dB durante una décima) |
| Núcleo en C | los dos, regenerados con la extensión | se reproducen igual; el fichero es el mismo byte a byte que el del núcleo de Python |
| Nombres libres | `CORTO.GBM` y un nombre largo junto a los `M0000n` | los lista los cuatro con su tamaño y reproduce el de nombre libre con su audio; el largo se ve como `FURRET~1.GBM` |
| Modo de audio libre | compresión + 8:1 estéreo, y alta + 11:1 mono | las dos combinaciones que el conversor original nunca emitió con video se reproducen igual: el modo va en la cabecera del `.gbs` y el reproductor lo respeta |
| Música | `.gbs` de un mp3 | "Playing... Mode 8:1, Total Time 00:39", el tiempo avanza |
| Final de fichero | `M00000` -> `M00001` | encadena con el siguiente sin un solo frame de basura |

El de vectores es el que importa: son 280 frames de compensación de movimiento
decodificados por la ROM sin acumular error, o sea que la tabla de vectores
deducida, los desplazamientos lineales y la suma de color empaquetada son
correctos. Y como ese fichero está hecho a trozos, también prueba que repartir
el video entre procesos no deja costuras.

Lo que el emulador **no** puede validar es la ruta real de lectura de la SD en
la Omega. Eso sigue necesitando la GBA.

## Licencia

GPL-3.0-or-later.
