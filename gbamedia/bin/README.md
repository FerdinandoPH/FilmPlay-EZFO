# ffmpeg and ffprobe go here / ffmpeg y ffprobe van aquí

## English

Both binaries are embedded in the package and located by a path relative to the
executable, never via `PATH`.

The project is **GPL**, so **GPL** builds of ffmpeg are used, which are the
full ones. Only decoding is needed (mp4, mkv, mp3, aac, flac...), but carrying
the full build avoids surprises with unusual inputs.

During development there is no need to copy them: if they are not here,
`GBAMEDIA_FFMPEG` is tried and, as a last resort, the system ffmpeg.

They are downloaded by the packaging workflow
(`.github/workflows/package.yml`).

## Español

Los dos binarios se empotran en el paquete y se buscan por ruta relativa al
ejecutable, nunca por `PATH`.

El proyecto es **GPL**, así que se usan compilaciones **GPL** de ffmpeg, que son
las completas. Solo se necesita decodificar (mp4, mkv, mp3, aac, flac...), pero
llevar la compilación completa evita sorpresas con entradas raras.

En desarrollo no hace falta copiarlos: si no están aquí se prueba
`GBAMEDIA_FFMPEG` y, como último recurso, el ffmpeg del sistema.

Los descarga el guion de empaquetado (`.github/workflows/package.yml`).
