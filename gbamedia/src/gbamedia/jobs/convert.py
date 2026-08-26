"""De un fichero de entrada a los ficheros que come la GBA.

Un video da un par `.gbm` + `.gbs`; cualquier otra cosa, un `.gbs` suelto. El
`.gbs` companero dura **exactamente** `frames/10` segundos: los dos flujos se
consumen a su ritmo nominal y nadie los resincroniza en el reproductor.
"""
from dataclasses import dataclass, field
from pathlib import Path


from ..settings import modo_depuracion
from ..i18n import _
from ..core import gbm_decode, gbs_decode
from ..core.containers import TAM_CABECERA, leer_cabecera
from ..core.gbm_encode import envolver
from ..core.gbs_encode import codificar as codificar_audio
from ..media import cadence, decode, probe
from .naming import Numerador, nombre_de_salida
from .options import Opciones
from .parallel import TROZO, Cancelado, codificar_video

FPS = probe.FPS_DESTINO


@dataclass
class Destinos:
    video: Path
    musica: Path

    @classmethod
    def unico(cls, carpeta) -> "Destinos":
        carpeta = Path(carpeta)
        return cls(carpeta, carpeta)

    def preparar(self) -> None:
        self.video.mkdir(parents=True, exist_ok=True)
        self.musica.mkdir(parents=True, exist_ok=True)


@dataclass
class Trabajo:
    origen: Path
    opciones: Opciones = field(default_factory=Opciones)
    nombre: str | None = None       # ya reservado, si lo hay
    info: probe.Info | None = None

    def sondear(self) -> probe.Info:
        if self.info is None:
            self.info = probe.sondear(self.origen)
        return self.info


@dataclass
class Resultado:
    trabajo: Trabajo
    ficheros: list = field(default_factory=list)
    nombre: str = ""                # el que se ha usado, sin extension
    frames: int = 0
    duracion: float = 0.0
    avisos: list = field(default_factory=list)
    bytes_video: int = 0
    bytes_audio: int = 0

    @property
    def es_video(self) -> bool:
        return self.frames > 0


def analizar(trabajo: Trabajo, muestra: float = 40.0) -> list:
    """Avisos de cadencia sin convertir nada.

    En modo normal no hay avisos: la medida se equivoca en material real y
    mandar a retocar el tempo de un video sano es peor que no decir nada. Con
    `DEBUG_ON` al lado del ejecutable vuelven a salir.
    """
    info = trabajo.sondear()
    avisos = []
    if info.tiene_video and modo_depuracion():
        aviso = cadence.aviso_fps(info.fps)
        if aviso:
            avisos.append(aviso)
        opciones = trabajo.opciones.opciones_media
        energia = cadence.Energia()
        for n, frame in enumerate(decode.frames(info, opciones)):
            energia.anadir(frame)
            if n >= muestra * FPS:
                break
        aviso = cadence.aviso_ciclo(energia.frecuencia())
        if aviso:
            avisos.append(aviso)
    return avisos


def _rellenar(datos: bytes, cluster: int) -> bytes:
    """Completa hasta multiplo de cluster.

    La ROM sin parchear reproduce hasta el final de la cadena FAT y no hasta el
    tamano del fichero, asi que suelta lo que haya en el ultimo cluster. Con
    ceros ahi, eso es silencio o negro en vez de basura. Con la ROM parcheada
    no hace falta.
    """
    if cluster <= 0 or len(datos) % cluster == 0:
        return datos
    return datos + bytes(cluster - len(datos) % cluster)


def nombre_para(trabajo: "Trabajo", destinos: Destinos, usados=(),
                numerador: Numerador | None = None) -> str:
    """El nombre de salida de un trabajo, sin extension.

    Manda lo que se haya escrito a mano; luego el que ya tuviera asignado
    -convertir otra vez tiene que **reemplazar** su salida, no dejar otra al
    lado-; y si no, el del fichero de origen recortado a 8.3, que es lo que la
    GBA sabe ensenar. El `Mnnnnn` del conversor original solo sale con
    `numerar`.
    """
    if trabajo.opciones.nombre:
        return trabajo.opciones.nombre
    if trabajo.nombre:
        return trabajo.nombre
    if trabajo.opciones.numerar and trabajo.sondear().es_video:
        return (numerador or Numerador(destinos.video)).reservar()
    return nombre_de_salida(trabajo.origen, usados)


def colisiones(trabajos, destinos: Destinos) -> list:
    """Ficheros que se van a reemplazar, y los `.gbs` que cambian de dueno.

    El caso feo no es reemplazar -convertir dos veces lo mismo tiene que
    reemplazar-, sino que la musica y el video compartan carpeta: FilmPlay
    empareja un `.gbm` con el `.gbs` que se llama igual, asi que un `.gbs` de
    musica con el nombre de un video **se convierte en su banda sonora**.

    Devuelve pares (trabajo, motivo), con el motivo ya escrito.
    """
    fuera = []
    for trabajo in trabajos:
        if trabajo.nombre is None or trabajo.info is None:
            continue
        es_video = trabajo.info.es_video
        carpeta = destinos.video if es_video else destinos.musica
        for extension in ((".gbm", ".gbs") if es_video else (".gbs",)):
            ruta = carpeta / f"{trabajo.nombre}{extension}"
            if ruta.exists():
                fuera.append((trabajo, _("reemplaza {ruta}", ruta=ruta)))
                break
        if (not es_video and destinos.musica == destinos.video
                and (destinos.video / f"{trabajo.nombre}.gbm").exists()):
            fuera.append((trabajo, _(
                "en esa carpeta hay un video {nombre}.gbm: este .gbs pasaría "
                "a ser su banda sonora", nombre=trabajo.nombre)))
    return fuera


def asignar_nombres(trabajos, destinos: Destinos, usados=()) -> None:
    """Reparte los nombres de un lote de una vez.

    De uno en uno, dos origenes que se recortan al mismo nombre se pisarian sin
    enterarse; y con `numerar`, cada trabajo se llevaria el mismo numero porque
    ninguno esta escrito todavia.
    """
    numerador = Numerador(destinos.video)
    usados = set(usados)
    for trabajo in trabajos:
        trabajo.nombre = nombre_para(trabajo, destinos, usados, numerador)
        usados.add(trabajo.nombre)


def convertir(trabajo: Trabajo, destinos: Destinos, progreso=None, *,
              trabajadores: int = 0, trozo: int = TROZO,
              cancelar=None) -> Resultado:
    """Convierte un fichero. `progreso(hechos, total)` va por trozos de video.

    `cancelar` es un `threading.Event`: en cuanto se levanta se sueltan los
    trozos que no han empezado y se lanza `Cancelado`, sin dejar nada escrito.
    """
    info = trabajo.sondear()
    destinos.preparar()
    if info.es_video:
        return _convertir_video(trabajo, info, destinos, progreso,
                                trabajadores, trozo, cancelar)
    return _convertir_musica(trabajo, info, destinos, progreso, cancelar)


def _mirando(frames, energia):
    """Deja pasar los frames apuntando su energia, que se mide aqui y no en
    los procesos de trabajo: cuesta nada y hace falta entera y en orden."""
    for frame in frames:
        energia.anadir(frame)
        yield frame


def _convertir_video(trabajo, info, destinos, progreso,
                     trabajadores=0, trozo=TROZO, cancelar=None) -> Resultado:
    opciones = trabajo.opciones
    medios = opciones.opciones_media
    nombre = nombre_para(trabajo, destinos)

    total = info.frames_destino or None
    energia = cadence.Energia()
    frames = decode.frames(info, medios)
    if modo_depuracion():
        frames = _mirando(frames, energia)
    payloads = codificar_video(
        frames, opciones.calidad,
        trabajadores=trabajadores, trozo=trozo, cancelar=cancelar,
        progreso=(lambda hechos: progreso(hechos, total)) if progreso else None)
    if not payloads:
        raise ValueError(f"{trabajo.origen}: no se ha decodificado ni un frame")

    datos_video = envolver(payloads)
    ruta_video = destinos.video / f"{nombre}.gbm"
    ruta_video.write_bytes(_rellenar(datos_video, opciones.rellenar_cluster))

    segundos = len(payloads) / FPS
    pcm = decode.ajustar_duracion(decode.audio(info, medios), segundos)
    datos_audio = codificar_audio(pcm, opciones.modo, opciones.canal,
                                  opciones.volumen)
    ruta_audio = destinos.video / f"{nombre}.gbs"
    ruta_audio.write_bytes(_rellenar(datos_audio, opciones.rellenar_cluster))

    avisos = []
    if modo_depuracion():
        for aviso in (cadence.aviso_fps(info.fps),
                      cadence.aviso_ciclo(energia.frecuencia())):
            if aviso:
                avisos.append(aviso)

    return Resultado(trabajo, [ruta_video, ruta_audio], nombre, len(payloads),
                     segundos, avisos, len(datos_video), len(datos_audio))


def _convertir_musica(trabajo, info, destinos, progreso,
                      cancelar=None) -> Resultado:
    opciones = trabajo.opciones
    nombre = nombre_para(trabajo, destinos)
    pcm = decode.audio(info, opciones.opciones_media)
    if cancelar is not None and cancelar.is_set():
        raise Cancelado()
    if not len(pcm):
        raise ValueError(f"{trabajo.origen}: no tiene audio que convertir")
    datos = codificar_audio(pcm, opciones.modo, opciones.canal,
                            opciones.volumen, progreso, cancelar)
    ruta = destinos.musica / f"{nombre}.gbs"
    ruta.write_bytes(_rellenar(datos, opciones.rellenar_cluster))
    return Resultado(trabajo, [ruta], nombre, 0, len(pcm) / probe.FRECUENCIA,
                     [], 0, len(datos))


def verificar(ruta) -> str:
    """Decodifica lo producido y comprueba que la ROM lo leeria entero.

    Es la red de seguridad: los flujos tienen que consumirse exactos y los
    frames teselar el fichero hasta el ultimo byte.
    """
    ruta = Path(ruta)
    datos = ruta.read_bytes()
    if ruta.suffix.lower() == ".gbm":
        frames = 0
        for st in gbm_decode.decodificar(datos):
            if not st.colores_exactos:
                raise ValueError(f"{ruta.name} frame {st.indice}: colores")
            if st.bits_sobrantes >= 32:
                raise ValueError(f"{ruta.name} frame {st.indice}: bits")
            if st.vectores_usados != st.tam_vectores:
                raise ValueError(f"{ruta.name} frame {st.indice}: vectores")
            frames += 1
        return f"{frames} frames, {frames / FPS:.2f} s"
    # Con --rellenar-cluster el fichero es mas largo que su contenido: la
    # cabecera dice donde acaba de verdad, y lo que sobra tiene que ser cero.
    util = min(leer_cabecera(datos).tamano or len(datos), len(datos))
    if any(datos[util:]):
        raise ValueError(f"{ruta.name}: {len(datos) - util} bytes de basura "
                         "detras del final")
    modo, bloques = gbs_decode.contar_bloques(datos[:util])
    esperado = TAM_CABECERA + bloques * modo.bloque
    if esperado != util:
        raise ValueError(f"{ruta.name}: {util - esperado} bytes sueltos")
    muestras = bloques * modo.muestras
    relleno = (f", {len(datos) - util} B de relleno"
               if len(datos) > util else "")
    return (f"modo {modo.numero} ({modo.etiqueta}), "
            f"{muestras / modo.frecuencia:.2f} s{relleno}")
