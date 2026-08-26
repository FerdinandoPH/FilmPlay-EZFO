"""Interfaz de terminal. La misma que usa la ventana por dentro.

Toda la logica vive en `jobs` y `core`: aqui solo se traducen argumentos a
`Opciones` y se imprime el resultado.
"""
import argparse
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..settings import modo_depuracion
from ..core.gbm_encode import BUSQUEDAS
from ..core.gbs_decode import MODOS
from ..i18n import IDIOMAS, _
from .. import i18n
from ..jobs.convert import (Destinos, Trabajo, analizar, asignar_nombres,
                              colisiones, convertir, verificar)
from ..jobs import batch
from ..jobs.naming import Numerador
from ..jobs.parallel import TROZO, trabajadores_por_defecto
from ..jobs.options import (PRESETS, Opciones, Perfiles, cargar_perfil,
                             guardar_perfil)
from ..media import fit
from ..media.ffmpeg import FaltaFfmpeg

from ..media.probe import EXTENSIONES

ALIAS_MODO = {"8:1": 0, "11:1": 1, "16:1": 2, "32:1": 3, "64:1": 4}


def idioma_pedido(argv) -> str | None:
    """Mira si hay --idioma antes de construir el parser.

    La ayuda se traduce al construirlo, asi que el idioma tiene que estar
    puesto antes; no da tiempo a esperar a `parse_args`.
    """
    for n, arg in enumerate(argv or []):
        if arg == "--idioma" and n + 1 < len(argv):
            return argv[n + 1]
        if arg.startswith("--idioma="):
            return arg.split("=", 1)[1]
    return None


def construir_parser() -> argparse.ArgumentParser:
    # Las opciones de cadencia siguen funcionando siempre -no se rompen los
    # guiones ya escritos-, pero solo se anuncian con DEBUG_ON: la medida se
    # equivoca en material real y el remedio que propone puede ser peor que la
    # enfermedad.
    oculto = None if modo_depuracion() else argparse.SUPPRESS

    p = argparse.ArgumentParser(
        prog="gbamedia",
        description=_("Convierte video y música a los formatos .gbm/.gbs de "
                      "GBA Movie Player. Un video da un par .gbm + .gbs; "
                      "cualquier otra cosa, un .gbs suelto."))
    p.add_argument("entradas", nargs="*", type=Path,
                   help=_("ficheros o carpetas a convertir (no hace falta "
                          "con --lote)"))

    d = p.add_argument_group(_("destinos"))
    d.add_argument("-o", "--salida", type=Path,
                   help=_("carpeta única para todo"))
    d.add_argument("-v", "--salida-video", type=Path,
                   help=_("carpeta de los pares de video .gbm + .gbs"))
    d.add_argument("-m", "--salida-musica", type=Path,
                   help=_("carpeta de la música suelta .gbs"))

    v = p.add_argument_group(_("video"))
    v.add_argument("-p", "--preset", choices=PRESETS,
                   help=_("calidad (por defecto: alta, que es sin pérdida)"))
    v.add_argument("--frame-size", type=int, metavar="N",
                   help=_("objetivo de bytes por frame"))
    v.add_argument("--tolerancias", metavar="A,B,C,D,E",
                   help=_("tolerancia por banda de tamaño de bloque; "
                          "ignora la del preset"))
    v.add_argument("--sin-vectores", action="store_true",
                   help=_("no usar compensación de movimiento"))
    v.add_argument("--busqueda", choices=BUSQUEDAS,
                   help=_("rápida (por defecto) criba los 256 vectores con "
                          "una métrica barata y mide exactos los cuatro "
                          "finalistas; exhaustiva los mide todos y tarda el "
                          "triple"))
    v.add_argument("--ajuste", choices=fit.AJUSTES,
                   help=_("cómo meter la imagen en 240x160 (por defecto: "
                          "barras)"))
    v.add_argument("--color-barras", metavar="COLOR")
    v.add_argument("--brillo", type=int, metavar="N", help="-100..100")
    v.add_argument("--contraste", type=int, metavar="N", help="0..200")
    v.add_argument("--realce", type=int, metavar="N", help="0..100")

    a = p.add_argument_group(_("audio"))
    a.add_argument("--modo", metavar="MODO",
                   help=_("0..4 o {alias}", alias=" / ".join(ALIAS_MODO)))
    a.add_argument("--canal", choices=["izq", "der"])
    a.add_argument("--volumen", type=int, choices=[1, 2, 4, 8])

    c = p.add_argument_group(_("cadencia"))
    c.add_argument("--tempo", type=float, metavar="K",
                   help=oculto or _("factor de tempo aplicado a video y "
                                   "audio a la vez"))
    c.add_argument("--bpm", metavar="ORIGEN:DESTINO",
                   help=oculto or _("calcula el factor de tempo entre dos "
                                   "tempos"))
    c.add_argument("--mezclar-frames", action="store_true",
                   help=oculto or _("mezclar frames en vez de "
                                   "descartarlos"))
    c.add_argument("--arreglar-cadencia", action="store_true",
                   help=oculto or _("aplica el arreglo que propone cada "
                                   "aviso de cadencia en vez de solo "
                                   "contarlo"))
    c.add_argument("--solo-analizar", action="store_true",
                   help=_("informa de duración y cadencia, y no convierte"))

    r = p.add_argument_group(_("recorte y salida"))
    r.add_argument("--desde", type=float, metavar="SEG")
    r.add_argument("--duracion", type=float, metavar="SEG")
    r.add_argument("--nombre", metavar="NOMBRE",
                   help=_("nombre de salida sin extensión, solo con una "
                          "entrada"))
    r.add_argument("--numerar", action="store_true",
                   help=_("nombrar los videos Mnnnnn como el conversor "
                          "original, en vez de con el nombre del origen"))
    r.add_argument("--numero", type=int, metavar="N",
                   help=_("número Mnnnnn concreto, solo con una entrada"))
    r.add_argument("--rellenar-cluster", type=int, metavar="BYTES", default=None,
                   help=_("completar con ceros hasta múltiplo del cluster"))

    g = p.add_argument_group(_("lote y control"))
    g.add_argument("--perfil", type=Path,
                   help=_("opciones por defecto (JSON); si no se da "
                          "--perfil-musica, valen también para la música"))
    g.add_argument("--perfil-musica", type=Path,
                   help=_("opciones por defecto solo para la música (JSON)"))
    g.add_argument("--lote", type=Path,
                   help=_("manifiesto con sobrescrituras por fichero "
                          "(JSON)"))
    g.add_argument("--guardar-lote", type=Path,
                   help=_("escribe el lote resuelto y sale"))
    g.add_argument("--guardar-perfil", type=Path,
                   help=_("escribe las opciones efectivas y sale"))
    g.add_argument("--trabajos", type=int, default=0, metavar="N",
                   help=_("trabajadores (por defecto: núcleos). Un video se "
                          "trocea y usa todos; la música se reparte por "
                          "fichero"))
    g.add_argument("--trozo", type=int, default=TROZO, metavar="N",
                   help=_("frames por trozo al repartir un video (por "
                          "defecto {trozo}); 0 no trocea. Cambiarlo cambia el "
                          "fichero en un uno por ciento", trozo=TROZO))
    g.add_argument("--simular", action="store_true",
                   help=_("dice que haría y no escribe nada"))
    g.add_argument("--verificar", action="store_true",
                   help=_("decodifica lo producido y lo valida"))
    g.add_argument("--idioma", choices=IDIOMAS,
                   help=_("idioma de los mensajes (por defecto, el del "
                          "sistema)"))
    g.add_argument("-q", "--callado", action="store_true")
    return p


def _modo(texto: str | None) -> int | None:
    if texto is None:
        return None
    if texto in ALIAS_MODO:
        return ALIAS_MODO[texto]
    try:
        numero = int(texto)
    except ValueError:
        raise SystemExit(_("modo de audio inválido: {que}", que=texto))
    if numero not in MODOS:
        raise SystemExit(_("modo de audio inválido: {que}", que=texto))
    return numero


def _tolerancias(texto: str | None):
    if texto is None:
        return None
    partes = [int(x) for x in texto.replace(" ", "").split(",")]
    if len(partes) != 5:
        raise SystemExit(_("--tolerancias necesita cinco valores"))
    return tuple(partes)


def _tempo(args) -> float | None:
    if args.bpm:
        try:
            origen, destino = (float(x) for x in args.bpm.split(":"))
        except ValueError:
            raise SystemExit(_("--bpm se escribe ORIGEN:DESTINO"))
        from ..media.cadence import factor_tempo
        return factor_tempo(origen, destino)
    return args.tempo


def opciones_desde_argumentos(args, perfil=Ellipsis) -> Opciones:
    """Las opciones que salen de los argumentos, sobre el perfil que se diga.

    Por defecto, sobre el de `--perfil`.
    """
    if perfil is Ellipsis:
        perfil = args.perfil
    base = cargar_perfil(perfil) if perfil else Opciones()
    return base.con(
        preset=args.preset,
        frame_size=args.frame_size,
        tolerancias=_tolerancias(args.tolerancias),
        sin_vectores=args.sin_vectores or None,
        busqueda=args.busqueda,
        ajuste=args.ajuste,
        color_barras=args.color_barras,
        brillo=args.brillo,
        contraste=args.contraste,
        realce=args.realce,
        modo_audio=_modo(args.modo),
        canal={"izq": 0, "der": 1}.get(args.canal),
        volumen=({1: 0, 2: 1, 4: 2, 8: 3}.get(args.volumen)
                 if args.volumen else None),
        tempo=_tempo(args),
        mezclar_frames=args.mezclar_frames or None,
        desde=args.desde,
        duracion=args.duracion,
        nombre=args.nombre,
        numerar=args.numerar or None,
        rellenar_cluster=args.rellenar_cluster,
    )


def perfiles_desde_argumentos(args) -> Perfiles:
    """Los dos juegos de valores por defecto. Lo que se pide por argumentos
    pisa a los dos: quien escribe --volumen 4 lo quiere en todo."""
    return Perfiles(
        opciones_desde_argumentos(args, args.perfil),
        opciones_desde_argumentos(args, args.perfil_musica or args.perfil))


def reunir(entradas) -> list[Path]:
    fuera = []
    for entrada in entradas:
        if entrada.is_dir():
            fuera += sorted(f for f in entrada.rglob("*")
                            if f.suffix.lower() in EXTENSIONES and f.is_file())
        elif entrada.is_file():
            fuera.append(entrada)
        else:
            raise SystemExit(_("no existe: {ruta}", ruta=entrada))
    if not fuera:
        raise SystemExit(_("no hay nada que convertir"))
    return fuera


def destinos_desde_argumentos(args) -> Destinos:
    video = args.salida_video or args.salida or Path("salida/videos")
    musica = args.salida_musica or args.salida or Path("salida")
    return Destinos(Path(video), Path(musica))


def _tarea(argumentos):
    trabajo, destinos = argumentos
    try:
        return convertir(trabajo, destinos), None
    except Exception as e:                     # se informa, no se aborta el lote
        return None, f"{trabajo.origen.name}: {e}"


def main(argv=None) -> int:
    # Sin esto, el ejecutable congelado de Windows vuelve a arrancar la
    # aplicacion entera en cada proceso de trabajo en vez de la funcion.
    multiprocessing.freeze_support()
    i18n.usar(idioma_pedido(argv if argv is not None else sys.argv[1:])
              or i18n.del_sistema())
    args = construir_parser().parse_args(argv)
    perfiles = perfiles_desde_argumentos(args)
    opciones = perfiles.video
    decir = (lambda *a: None) if args.callado else print

    if args.guardar_perfil:
        guardar_perfil(opciones, args.guardar_perfil)
        decir(_("perfil escrito en {ruta}", ruta=args.guardar_perfil))
        return 0

    destinos = destinos_desde_argumentos(args)
    if args.lote:
        try:
            # Ojo: nada de `_` como variable de descarte en un modulo que
            # importa `_` para traducir; se lo come para el resto de la funcion.
            _perfiles, destinos_lote, trabajos = batch.cargar(args.lote)
        except batch.LoteInvalido as e:
            raise SystemExit(f"{args.lote}: {e}")
        # Los argumentos sueltos siguen pisando al perfil del lote, pero no a
        # lo que cada fichero haya pedido para si.
        propios = opciones.a_json()
        if propios:
            trabajos = [Trabajo(t.origen, t.opciones.con(**propios), t.nombre)
                        for t in trabajos]
        if destinos_lote and not (args.salida or args.salida_video
                                  or args.salida_musica):
            destinos = destinos_lote
        if args.entradas:
            trabajos += [Trabajo(f, perfiles.para(f))
                         for f in reunir(args.entradas)]
    else:
        if not args.entradas:
            raise SystemExit(_("no hay nada que convertir"))
        trabajos = [Trabajo(f, perfiles.para(f))
                    for f in reunir(args.entradas)]

    if (args.nombre or args.numero is not None) and len(trabajos) > 1:
        raise SystemExit(_("--nombre y --numero solo valen con una "
                           "entrada"))

    try:
        for t in trabajos:
            t.sondear()
    except FaltaFfmpeg as e:
        raise SystemExit(str(e))

    if args.guardar_lote:
        batch.guardar(args.guardar_lote, perfiles, destinos, trabajos)
        decir(_("lote escrito en {ruta}", ruta=args.guardar_lote))
        return 0

    if args.solo_analizar:
        return _informar(trabajos, decir)

    if args.numero is not None:
        trabajos[0].nombre = Numerador(destinos.video).reservar(args.numero)
    if args.arreglar_cadencia:
        _arreglar(trabajos, decir)
    asignar_nombres(trabajos, destinos)
    for trabajo, motivo in colisiones(trabajos, destinos):
        decir(_("aviso: {nombre}: {motivo}", nombre=trabajo.origen.name,
                motivo=motivo))

    if args.simular:
        for t in trabajos:
            tipo = _("video") if t.info.es_video else _("música")
            destino = destinos.video if t.info.es_video else destinos.musica
            decir(_("{nombre} -> {tipo}: {destino}/{salida}",
                    nombre=t.origen.name, tipo=tipo, destino=destino,
                    salida=t.nombre or _("(nombre del fichero)")))
        return 0

    return _convertir_todos(trabajos, destinos, args, decir)


def _arreglar(trabajos, decir) -> None:
    """Aplica lo que propone cada aviso, que es lo que casi siempre se quiere.

    Analizar cuesta lo que decodificar 40 s de video, calderilla al lado de
    convertirlo, y evita la ronda de "avisa, copia el factor, vuelve a lanzar".
    """
    for n, t in enumerate(trabajos):
        cambios = {}
        for aviso in analizar(t):
            if aviso.arreglo:
                cambios.update(aviso.arreglo)
        if not cambios:
            continue
        trabajos[n] = Trabajo(t.origen, t.opciones.con(**cambios), t.nombre,
                              t.info)
        dicho = ", ".join(f"{k}={v}" for k, v in cambios.items())
        decir(_("{nombre}: cadencia arreglada ({que})",
                nombre=t.origen.name, que=dicho))


def _informar(trabajos, decir) -> int:
    for t in trabajos:
        i = t.info
        clase = _("video") if i.es_video else _("música")
        decir("\n" + _("{nombre}  [{clase}]  {s:.2f} s",
                        nombre=t.origen.name, clase=clase, s=i.duracion))
        if i.es_video:
            decir("  " + _("{ancho}x{alto} a {fps:.3f} fps -> {frames} "
                            "frames a 10 fps", ancho=i.ancho, alto=i.alto,
                            fps=float(i.fps), frames=i.frames_destino))
        if i.tiene_audio:
            decir("  " + _("audio {codec} {hz} Hz {canales} canal(es)",
                            codec=i.codec_audio, hz=i.frecuencia,
                            canales=i.canales))
        for aviso in analizar(t):
            _decir_aviso(aviso, decir)
    return 0


def _decir_aviso(aviso, decir) -> None:
    decir("  " + _("aviso: {titulo}", titulo=aviso.titulo))
    decir(f"    {aviso.mensaje}")
    if aviso.sugerencia:
        decir("    " + _("remedio: {que}", que=aviso.sugerencia))
    if aviso.arreglo:
        decir("    " + _("se aplica solo con --arreglar-cadencia"))


def _convertir_todos(trabajos, destinos, args, decir) -> int:
    destinos.preparar()
    procesos = trabajadores_por_defecto(args.trabajos)
    fallos = 0
    resultados = []

    # Un video se reparte entre todos los procesos por trozos, asi que se
    # convierten de uno en uno; la musica no se trocea y se reparte por
    # fichero. Mezclar los dos repartos anidaria piscinas de procesos.
    videos = [t for t in trabajos if t.sondear().es_video]
    musica = [t for t in trabajos if not t.sondear().es_video]

    # La barra solo tiene sentido en un terminal: redirigida a un fichero,
    # el retorno de carro no borra nada y deja un churro ilegible.
    interactivo = sys.stdout.isatty() and not args.callado
    for t in videos:
        def progreso(n, total, nombre=t.origen.name):
            if interactivo and total:
                print("\r" + _("{nombre}: {n}/{total} frames", nombre=nombre,
                            n=n, total=total), end="", flush=True)
        try:
            resultados.append(convertir(t, destinos, progreso,
                                        trabajadores=procesos,
                                        trozo=args.trozo))
        except Exception as e:
            fallos += 1
            decir(_("{nombre}: ERROR {error}", nombre=t.origen.name,
                    error=e))
        if interactivo:
            print("\r" + " " * 60 + "\r", end="")

    if len(musica) == 1 or procesos == 1:
        for t in musica:
            try:
                resultados.append(convertir(t, destinos))
            except Exception as e:
                fallos += 1
                decir(_("{nombre}: ERROR {error}", nombre=t.origen.name,
                        error=e))
    elif musica:
        with ProcessPoolExecutor(max_workers=min(procesos, len(musica))) as piscina:
            for resultado, error in piscina.map(
                    _tarea, [(t, destinos) for t in musica]):
                if error:
                    fallos += 1
                    decir(_("ERROR {error}", error=error))
                else:
                    resultados.append(resultado)

    for r in resultados:
        nombres = ", ".join(f.name for f in r.ficheros)
        if r.es_video:
            decir(_("{origen} -> {salida}  {frames} frames, {s:.2f} s, "
                    "{kv:.0f} KB + {ka:.0f} KB",
                    origen=r.trabajo.origen.name, salida=nombres,
                    frames=r.frames, s=r.duracion,
                    kv=r.bytes_video / 1024, ka=r.bytes_audio / 1024))
        else:
            decir(_("{origen} -> {salida}  {s:.2f} s, {ka:.0f} KB",
                    origen=r.trabajo.origen.name, salida=nombres,
                    s=r.duracion, ka=r.bytes_audio / 1024))
        for aviso in r.avisos:
            _decir_aviso(aviso, decir)
        if args.verificar:
            for f in r.ficheros:
                try:
                    decir("  " + _("verificado {nombre}: {que}", nombre=f.name,
                             que=verificar(f)))
                except Exception as e:
                    fallos += 1
                    decir("  " + _("VERIFICACIÓN FALLIDA {nombre}: {error}",
                                 nombre=f.name, error=e))

    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
