"""Catalogo ingles.

Las claves son las cadenas en espanol tal como aparecen en el codigo, que es el
idioma original del proyecto. Lo que no este aqui sale en espanol, nunca en
blanco.

Las cadenas se comprueban con `tests/test_i18n.py`, que saca del codigo todas
las llamadas a `_()` y falla si alguna no esta traducida.
"""

CATALOGO = {
    # --- ventana: lista y barra
    "⚙  Valores por defecto\n    vídeo y música":
        "⚙  Default settings\n    video and music",
    "Se aplican a todo el que no haya decidido otra cosa":
        "Used by every file that has not decided otherwise",
    "Añadir...": "Add...",
    "Añadir carpeta...": "Add folder...",
    "Añadir ficheros": "Add files",
    "Añadir carpeta": "Add folder",
    "Quitar": "Remove",
    "Quitar de la lista": "Remove from the list",
    "Arrastra aquí ficheros o carpetas.": "Drag files or folders here.",
    "No hay nada en la lista.": "The list is empty.",
    "{n} ficheros": "{n} files",
    "{n} vídeo": "{n} video",
    "{n} música": "{n} music",
    "{n} hecho": "{n} done",
    "{n} fallido": "{n} failed",
    "vídeo": "video",
    "música": "music",
    "frames": "frames",
    "bloques": "blocks",
    "1 ajuste propio": "1 setting of its own",
    "{n} ajustes propios": "{n} settings of its own",
    "aviso de cadencia": "cadence warning",
    "{hechos}/{total} {unidad} ({parte:.0f} %)":
        "{hechos}/{total} {unidad} ({parte:.0f} %)",
    "hecho": "done",
    "fallido": "failed",
    "convirtiendo": "converting",
    "pendiente": "pending",

    # --- ventana: carpetas y conversion
    "Elegir carpeta...": "Choose folder...",
    "Elegir carpeta": "Choose folder",
    "Abrir carpeta": "Open folder",
    "Abrir carpeta de salida": "Open output folder",
    "Sin carpeta de salida: se pregunta al convertir.":
        "No output folder yet: you will be asked when converting.",
    "Video: {video}\nMusica: {musica}": "Video: {video}\nMusic: {musica}",
    "todavía no hay carpeta de salida elegida":
        "no output folder has been chosen yet",
    "Carpeta de salida": "Output folder",
    "Carpetas distintas para video y música":
        "Separate folders for video and music",
    "Carpeta": "Folder",
    "Video": "Video",
    "Examinar...": "Browse...",
    "Convertir todo": "Convert all",
    "Convertir selección": "Convert selection",
    "Convertir selección ({cuantas})": "Convert selection ({cuantas})",
    "Convertir ({n})": "Convert ({n})",
    "Volver a convertir ({n})": "Convert again ({n})",
    "Analizar cadencia": "Analyse cadence",
    "la cadencia solo aplica al video": "cadence only applies to video",
    "analizados {n}: {avisan} con algo que arreglar":
        "{n} analysed: {avisan} with something to fix",
    "aplicado a {n}: {que}": "applied to {n}: {que}",
    "Parar": "Stop",
    "Parando...": "Stopping...",
    "parando: se sueltan los trozos que no han empezado":
        "stopping: chunks that have not started are dropped",
    "parado": "stopped",
    ", parado a mitad": ", stopped halfway",
    "repartiendo trozos...": "handing out chunks...",
    "Fichero {n} de {total}  ·  {nombre}": "File {n} of {total}  ·  {nombre}",
    "quedan {tiempo}": "{tiempo} left",
    "{s} s": "{s} s",
    "{m} min {s:02d} s": "{m} min {s:02d} s",
    "lote": "batch",
    "{n} convertido(s)": "{n} converted",
    " en {carpeta}": " in {carpeta}",
    "no hay nada que convertir": "there is nothing to convert",
    "ya están todos hechos; para rehacer alguno, selecciónalo":
        "they are all done; to redo one, select it",
    "{n} sin leer, se quedan fuera: {cuales}":
        "{n} could not be read and are left out: {cuales}",
    "no se han podido leer: {cuales}": "could not be read: {cuales}",
    "Falta ffmpeg": "ffmpeg is missing",
    "No se encuentra ffmpeg/ffprobe. Ponlos en bin/ junto al ejecutable o "
    "apunta GBAMEDIA_FFMPEG a su carpeta.":
        "ffmpeg/ffprobe not found. Put them in bin/ next to the executable, "
        "or point GBAMEDIA_FFMPEG at their folder.",
    "Salir de gbamedia": "Quit gbamedia",
    "Hay una conversión en marcha. Si sales ahora se parará a medias y "
    "quedarán {n} sin terminar.":
        "A conversion is running. Quitting now stops it halfway and leaves "
        "{n} unfinished.",

    # --- ventana: menus y lotes
    "&Lote": "&Batch",
    "Abrir lote...": "Open batch...",
    "Guardar lote...": "Save batch...",
    "Abrir lote": "Open batch",
    "Guardar lote": "Save batch",
    "Lote inválido": "Invalid batch",
    "Cargar valores por defecto...": "Load default settings...",
    "Guardar valores por defecto...": "Save default settings...",
    "Valores por defecto para {clase}": "Default settings for {clase}",
    "Idioma": "Language",

    # --- panel
    "Vídeo": "Video",
    "Música": "Music",
    "Cada clase de fichero tiene sus propios valores por defecto":
        "Each kind of file has its own default settings",
    "Valores por defecto para {que}": "Default settings for {que}",
    "los vídeos": "video",
    "la música": "music",
    "Se aplican a todo el que no haya decidido otra cosa. Selecciona ficheros "
    "para darles ajustes propios.":
        "Used by every file that has not decided otherwise. Select files to "
        "give them settings of their own.",
    "{n} ficheros seleccionados": "{n} files selected",
    "Lo que cambies se aplica a todos.": "What you change applies to all.",
    "(varios)": "(several)",
    "volver al valor del lote": "back to the batch value",
    "Aplicar": "Apply",
    "Imagen": "Image",
    "Calidad": "Quality",
    "Audio": "Audio",
    "Cadencia": "Cadence",
    "Velocidad": "Speed",
    "Recorte y salida": "Trimming and output",
    "Ajuste": "Fit",
    "Barras (no deforma)": "Bars (no distortion)",
    "Recorte (llena la pantalla)": "Crop (fills the screen)",
    "Estirado (deforma)": "Stretched (distorts)",
    "Color de las barras": "Bar colour",
    "Brillo": "Brightness",
    "Contraste": "Contrast",
    "Realce": "Sharpening",
    "Preset": "Preset",
    "Alta": "High",
    "Estandar": "Standard",
    "Compresion": "Compression",
    "Bytes por frame": "Bytes per frame",
    "Sin compensación de movimiento": "No motion compensation",
    "Búsqueda de vectores": "Vector search",
    "Rápida": "Fast",
    "Exhaustiva (más lenta)": "Exhaustive (slower)",
    "Modo": "Mode",
    "El del preset": "The preset's",
    "el del preset": "the preset's",
    "Canal (solo mono)": "Channel (mono only)",
    "Izquierdo": "Left",
    "Derecho": "Right",
    "Volumen": "Volume",
    "Normal (x1)": "Normal (x1)",
    "El doble (x2)": "Double (x2)",
    "Cuatro veces (x4)": "Four times (x4)",
    "Ocho veces (x8)": "Eight times (x8)",
    "Mezclar frames en vez de descartarlos":
        "Blend frames instead of dropping them",
    "Factor de tempo": "Tempo factor",
    "Empezar en (s)": "Start at (s)",
    "Duración (s)": "Duration (s)",
    "todo": "all",
    "Nombre de salida": "Output name",
    "automático": "automatic",

    # --- avisos de cadencia
    "El original tiene menos frames de los que caben":
        "The original has fewer frames than fit",
    "Va a {fps:.3f} fps y la consola reproduce a {destino}, así que algunos "
    "frames se verán repetidos. No hay nada que arreglar: no se puede "
    "inventar movimiento que no está.":
        "It runs at {fps:.3f} fps and the console plays at {destino}, so some "
        "frames will be seen twice. There is nothing to fix: motion that is "
        "not there cannot be invented.",
    "El movimiento va a dar tirones": "The motion will judder",
    "El original va a {fps:.3f} fps, que no es múltiplo de {destino}: al "
    "quedarse con uno de cada tantos, unos frames duran más que otros y el "
    "movimiento sale a saltos.":
        "The original runs at {fps:.3f} fps, which is not a multiple of "
        "{destino}: keeping one frame out of every so many makes some frames "
        "last longer than others, and the motion comes out jerky.",
    "Mezclar cada frame con los que se descartan, que reparte el movimiento "
    "en vez de tirarlo.":
        "Blend each frame with the ones being dropped, which spreads the "
        "motion out instead of throwing it away.",
    "La animación se irá desfasando de la música":
        "The animation will drift out of step with the music",
    "El movimiento se repite {bpm:.1f} veces por minuto, o sea cada "
    "{ciclo:.2f} frames. Como la consola solo puede enseñar frames enteros, "
    "cada ciclo cae un poco más tarde que el anterior y en unos segundos se "
    "ve que la imagen va por detrás del sonido.":
        "The motion repeats {bpm:.1f} times a minute, that is every "
        "{ciclo:.2f} frames. Since the console can only show whole frames, "
        "each cycle lands a little later than the one before, and within "
        "seconds the picture visibly lags the sound.",
    "Acelerar imagen y sonido un {porciento:+.1f} % para dejar el movimiento "
    "en {destino:.1f} por minuto, que sale exacto a {frames:.0f} frames por "
    "ciclo.":
        "Speed picture and sound up by {porciento:+.1f} % to leave the motion "
        "at {destino:.1f} a minute, which comes out exactly {frames:.0f} "
        "frames per cycle.",

    # --- colisiones
    "reemplaza {ruta}": "replaces {ruta}",
    "en esa carpeta hay un video {nombre}.gbm: este .gbs pasaría a ser su "
    "banda sonora":
        "that folder has a video called {nombre}.gbm: this .gbs would become "
        "its soundtrack",
    "Ya hay ficheros ahí": "There are files there already",
    "{n} conversión(es) van a escribir encima de lo que ya hay:":
        "{n} conversion(s) will write over what is already there:",
    "... y {n} más": "... and {n} more",
    "aviso: {nombre}: {motivo}": "warning: {nombre}: {motivo}",
    "leyendo...": "reading...",
    "Poner los videos en una subcarpeta {sub}/":
        "Put videos in a {sub}/ subfolder",
    "Los videos irán a {sub}/ y la música a la carpeta elegida.":
        "Videos go to {sub}/ and music to the chosen folder.",
    "Todo en la misma carpeta. Ojo: un .gbs de música que se llame como un "
    "video pasa a ser su banda sonora, así que se avisará si va a pasar.":
        "Everything in one folder. Careful: a music .gbs named like a video "
        "becomes its soundtrack, so you will be warned if that is about to "
        "happen.",

    # --- linea de ordenes
    "Convierte video y música a los formatos .gbm/.gbs de GBA Movie Player. "
    "Un video da un par .gbm + .gbs; cualquier otra cosa, un .gbs suelto.":
        "Converts video and music to the .gbm/.gbs formats of GBA Movie "
        "Player. A video gives a .gbm + .gbs pair; anything else, a single "
        ".gbs.",
    "ficheros o carpetas a convertir (no hace falta con --lote)":
        "files or folders to convert (not needed with --lote)",
    "destinos": "output",
    "carpeta única para todo": "single folder for everything",
    "carpeta de los pares de video .gbm + .gbs":
        "folder for the .gbm + .gbs video pairs",
    "carpeta de la música suelta .gbs": "folder for standalone .gbs music",
    "video": "video",
    "musica": "music",
    "audio": "audio",
    "cadencia": "cadence",
    "recorte y salida": "trimming and output",
    "lote y control": "batch and control",
    "calidad (por defecto: alta, que es sin pérdida)":
        "quality (default: alta, which is lossless)",
    "objetivo de bytes por frame": "target bytes per frame",
    "tolerancia por banda de tamaño de bloque; ignora la del preset":
        "tolerance per block size band; overrides the preset's",
    "no usar compensación de movimiento": "do not use motion compensation",
    "rápida (por defecto) criba los 256 vectores con una métrica barata y "
    "mide exactos los cuatro finalistas; exhaustiva los mide todos y tarda "
    "el triple":
        "rapida (default) sifts the 256 vectors with a cheap metric and "
        "measures the four finalists exactly; exhaustiva measures them all "
        "and takes three times as long",
    "cómo meter la imagen en 240x160 (por defecto: barras)":
        "how to fit the picture into 240x160 (default: bars)",
    "0..4 o {alias}": "0..4 or {alias}",
    "factor de tempo aplicado a video y audio a la vez":
        "tempo factor applied to video and audio at once",
    "calcula el factor de tempo entre dos tempos":
        "works out the tempo factor between two tempos",
    "mezclar frames en vez de descartarlos":
        "blend frames instead of dropping them",
    "aplica el arreglo que propone cada aviso de cadencia en vez de solo "
    "contarlo":
        "apply the fix each cadence warning proposes instead of just "
        "reporting it",
    "informa de duración y cadencia, y no convierte":
        "report duration and cadence, and convert nothing",
    "nombre de salida sin extensión, solo con una entrada":
        "output name without extension, only with a single input",
    "nombrar los videos Mnnnnn como el conversor original, en vez de con el "
    "nombre del origen":
        "name videos Mnnnnn like the original converter instead of after the "
        "source file",
    "número Mnnnnn concreto, solo con una entrada":
        "a specific Mnnnnn number, only with a single input",
    "completar con ceros hasta múltiplo del cluster":
        "pad with zeros up to a multiple of the cluster",
    "opciones por defecto (JSON); si no se da --perfil-musica, valen también "
    "para la música":
        "default options (JSON); without --perfil-musica they apply to music "
        "as well",
    "opciones por defecto solo para la música (JSON)":
        "default options for music only (JSON)",
    "manifiesto con sobrescrituras por fichero (JSON)":
        "manifest with per-file overrides (JSON)",
    "escribe el lote resuelto y sale": "write the resolved batch and exit",
    "escribe las opciones efectivas y sale":
        "write the effective options and exit",
    "trabajadores (por defecto: núcleos). Un video se trocea y usa todos; la "
    "música se reparte por fichero":
        "workers (default: cores). A video is chunked and uses them all; "
        "music is shared out per file",
    "frames por trozo al repartir un video (por defecto {trozo}); 0 no "
    "trocea. Cambiarlo cambia el fichero en un uno por ciento":
        "frames per chunk when sharing out a video (default {trozo}); 0 does "
        "not chunk. Changing it changes the file by about one per cent",
    "idioma de los mensajes (por defecto, el del sistema)":
        "language of the messages (default: the system's)",
    "dice que haría y no escribe nada": "say what it would do and write nothing",
    "decodifica lo producido y lo valida":
        "decode what was produced and validate it",

    # --- linea de ordenes: mensajes
    "modo de audio inválido: {que}": "invalid audio mode: {que}",
    "--tolerancias necesita cinco valores": "--tolerancias needs five values",
    "--bpm se escribe ORIGEN:DESTINO": "--bpm is written FROM:TO",
    "no existe: {ruta}": "does not exist: {ruta}",
    "--nombre y --numero solo valen con una entrada":
        "--nombre and --numero only work with a single input",
    "perfil escrito en {ruta}": "profile written to {ruta}",
    "lote escrito en {ruta}": "batch written to {ruta}",
    "{nombre} -> {tipo}: {destino}/{salida}": "{nombre} -> {tipo}: {destino}/{salida}",
    "(nombre del fichero)": "(the file's name)",
    "{nombre}  [{clase}]  {s:.2f} s": "{nombre}  [{clase}]  {s:.2f} s",
    "{ancho}x{alto} a {fps:.3f} fps -> {frames} frames a 10 fps":
        "{ancho}x{alto} at {fps:.3f} fps -> {frames} frames at 10 fps",
    "audio {codec} {hz} Hz {canales} canal(es)":
        "audio {codec} {hz} Hz {canales} channel(s)",
    "aviso: {titulo}": "warning: {titulo}",
    "remedio: {que}": "fix: {que}",
    "se aplica solo con --arreglar-cadencia":
        "only applied with --arreglar-cadencia",
    "{nombre}: cadencia arreglada ({que})": "{nombre}: cadence fixed ({que})",
    "{nombre}: {n}/{total} frames": "{nombre}: {n}/{total} frames",
    "{nombre}: ERROR {error}": "{nombre}: ERROR {error}",
    "ERROR {error}": "ERROR {error}",
    "{origen} -> {salida}  {frames} frames, {s:.2f} s, {kv:.0f} KB + "
    "{ka:.0f} KB":
        "{origen} -> {salida}  {frames} frames, {s:.2f} s, {kv:.0f} KB + "
        "{ka:.0f} KB",
    "{origen} -> {salida}  {s:.2f} s, {ka:.0f} KB":
        "{origen} -> {salida}  {s:.2f} s, {ka:.0f} KB",
    "verificado {nombre}: {que}": "verified {nombre}: {que}",
    "VERIFICACIÓN FALLIDA {nombre}: {error}":
        "VERIFICATION FAILED {nombre}: {error}",
}
