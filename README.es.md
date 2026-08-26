[English](README.md) · **Español**

# FilmPlay para EZ Flash Omega

GBA Movie Player era un accesorio de 2004 para ver vídeo y escuchar música en
una Game Boy Advance desde una tarjeta SD. Más tarde se publicó su ROM,
adaptada para funcionar con la flashcart Supercard SD Mini (llamada
FilmPlay.gba). Con los años, FilmPlay.gba cayó en el olvido, pues no era
compatible con las flashcarts modernas.

Ahora, con la ayuda de Claude, hice ingeniería inversa de la ROM original, y,
gracias a la librería de
[gba-flashcartio](https://github.com/afska/gba-flashcartio), logré
adaptarla para que funcionase con la EZ Flash Omega (y DE).

Para funcionar, FilmPlay.gba utiliza un formato propietario para los vídeos y
la música (par .gbm+.gbs para vídeos, y solo .gbs para música). Puesto que el
conversor original solo funcionaba bien en Windows XP y requiere códecs muy
viejos, también hice ingeniería inversa de los formatos y creé un conversor
moderno.

| | |
|---|---|
| ![Menú principal de FilmPlay en la GBA Movie Player parcheada](gbamedia/screenshots/menu.png)<br>![Reproduciendo una canción convertida](gbamedia/screenshots/music.png)<br>![Reproduciendo un vídeo convertido](gbamedia/screenshots/video-vectors.png) | ![La ventana del conversor gbamedia](gbamedia/screenshots/gui.png) |
| En la GBA | Programa conversor |

| | |
|---|---|
| [`ezfo-patch/`](ezfo-patch/) | El parche a la ROM original para añadir la compatibilidad con EZ Flash Omega |
| [`gbamedia/`](gbamedia/) | El conversor de vídeo y música a `.gbm`/`.gbs`, que reemplaza al original |

Durante el desarrollo de este parche también creé un guion para mGBA (0.10+)
que simula la interfaz SD de una EZ Flash Omega, para depurar aplicaciones de
GBA que interactúen con la SD (se puede acceder al repositorio desde la
carpeta `sdcard`).

## Para usarlo

Para usar FilmPlay, la tarjeta SD de tu EZ Flash Omega (DE) debe pesar
≤256 GB, estar formateada en FAT32 y tener clusters de 32 KB.

Hace falta la **ROM de GBA Movie Player** para la **Supercard SD**
(filmplay.gba), que debe obtenerse legalmente.

**1. Parchear la ROM**: descarga `ezfo-patch.zip` de las **Releases** del
repositorio y descomprímelo. Con tu propia ROM copiada en esa carpeta:

    python3 patch.py FilmPlay.gba FilmPlay-EZFO.gba

**2. Convertir tu vídeo y música**: baja el paquete de tu sistema (Windows,
macOS o Linux) de las **Releases** del repositorio y descomprímelo.

Se ofrecen dos versiones: `gbamedia-gui` (GUI para el usuario común) y
`gbamedia` (CLI de la que depende el GUI).

Admite formatos modernos (mp4, mkv, mp3, m4a...) y conversión por lotes. El
[README de `gbamedia/`](gbamedia/README.es.md) explica el resto de opciones.

## Para desarrollar

El repositorio tiene tres carpetas principales:

* `ezfo-patch`: crea el parche al FilmPlay original para que funcione con la
  EZ Flash Omega, usando C y ensamblador de GBA. Necesita Python y gba-dev
  (de devkitPro). Puede compilarse con `make`
* `gbamedia`: nuevo conversor al formato de FilmPlay, junto con los
  documentos que describen el formato. Programado en Python, con un núcleo
  opcional en C para más velocidad
* `sdcard`: contiene el simulador de SD para mGBA (Lua). Más información en
  su propio repositorio

## Licencia

GPL-3.0-or-later, para el código de este repositorio. `gba-flashcartio` es MIT.
