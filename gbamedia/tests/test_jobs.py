"""Modelo de trabajos, numeracion, perfiles y CLI."""
import json

import pytest

from gbamedia.cli import main as cli
from gbamedia.core.gbm_encode import CALIDADES
from gbamedia.jobs.convert import Destinos, Trabajo, convertir, verificar
from gbamedia.jobs.naming import Numerador, nombre_de_salida, sanear
from gbamedia.jobs.options import Opciones, cargar_perfil, guardar_perfil
from gbamedia.media import fit


# --- opciones -----------------------------------------------------------

def test_el_preset_fija_tambien_el_modo_de_audio():
    """Igual que el conversor original: alta -> 0, estandar -> 2, compresion -> 4."""
    assert Opciones(preset="alta").modo.numero == 0
    assert Opciones(preset="estandar").modo.numero == 2
    assert Opciones(preset="compresion").modo.numero == 4
    assert Opciones(preset="alta", modo_audio=3).modo.numero == 3


def test_las_sobrescrituras_solo_pisan_lo_que_se_pasa():
    base = Opciones(preset="estandar", brillo=20)
    assert base.con(brillo=None).brillo == 20
    assert base.con(brillo=0).brillo == 0
    assert base.con(preset="alta").brillo == 20


def test_opciones_invalidas():
    for malas in ({"preset": "ninguno"}, {"ajuste": "ninguno"},
                  {"modo_audio": 9}, {"canal": 2}, {"volumen": 4}):
        with pytest.raises(ValueError):
            Opciones(**malas)


def test_la_calidad_manual_pisa_la_del_preset():
    o = Opciones(preset="alta", tolerancias=(3, 3, 4, 4, 5), frame_size=1234,
                 sin_vectores=True)
    assert o.calidad.tolerancias == (3, 3, 4, 4, 5)
    assert o.calidad.frame_size == 1234
    assert o.calidad.vectores is False
    assert CALIDADES["alta"].tolerancias == (0, 0, 0, 0, 0), "no se ha tocado"


def test_perfil_va_y_vuelve(tmp_path):
    o = Opciones(preset="compresion", ajuste=fit.RECORTE, volumen=2,
                 tolerancias=(1, 2, 3, 4, 5))
    ruta = tmp_path / "perfil.json"
    guardar_perfil(o, ruta)
    assert cargar_perfil(ruta) == o
    # Solo se guarda lo que se aparta del valor por defecto
    assert "brillo" not in json.loads(ruta.read_text())
    with pytest.raises(ValueError):
        Opciones.desde_json({"invento": 1})


# --- numeracion ---------------------------------------------------------

def test_numerador_busca_el_primer_hueco(tmp_path):
    for n in (0, 1, 3):
        (tmp_path / f"M{n:05d}.gbm").touch()
    numerador = Numerador(tmp_path)
    assert numerador.reservar() == "M00002"
    assert numerador.reservar() == "M00004", "no repite lo ya reservado"
    with pytest.raises(ValueError):
        numerador.reservar(1)


def test_el_nombre_de_salida_cabe_en_8_3():
    """La ROM lee entradas de directorio cortas: lo que no quepa en 8.3 se ve
    en la consola como FURRET~1.GBM, que no dice nada."""
    assert sanear("/x/furret walk (full version)_360p.mp4") == "furretwa"
    assert sanear("/x/Cancion Buena.mp3") == "cancionb"
    assert sanear("/x/a:b*c.mp3") == "abc"
    assert sanear("/x/...mp4") == "media"
    assert len(sanear("/x/" + "z" * 40 + ".mp4")) == 8


def test_dos_origenes_que_se_recortan_igual_no_se_pisan():
    usados = {"furretwa"}
    assert nombre_de_salida("/x/furret walk 150bpm.mp4", usados) == "furretw2"


def test_el_mismo_origen_da_siempre_el_mismo_nombre():
    """Convertir otra vez tiene que reemplazar su salida, no dejar otra al
    lado: por eso el nombre no depende de lo que ya haya en la carpeta."""
    a = nombre_de_salida("/x/tema.mp3")
    b = nombre_de_salida("/x/tema.mp3")
    assert a == b == "tema"


# --- conversion ---------------------------------------------------------

def test_convertir_un_video(hay_ffmpeg, fuentes, tmp_path):
    destinos = Destinos(tmp_path / "videos", tmp_path)
    trabajo = Trabajo(fuentes / "Audio Video Sync Test_360p.mp4",
                      Opciones(duracion=3))
    resultado = convertir(trabajo, destinos)

    assert [f.name for f in resultado.ficheros] == ["audiovid.gbm",
                                                    "audiovid.gbs"]
    assert resultado.frames == 30
    assert resultado.duracion == pytest.approx(3.0)
    # El .gbs companero dura lo que el video, no lo que durase la fuente
    assert "30 frames" in verificar(resultado.ficheros[0])
    assert "8:1 Stereo" in verificar(resultado.ficheros[1])
    # Con solo 3 s no se puede medir la cadencia, asi que no se inventa nada
    assert not resultado.avisos


def test_convertir_musica_suelta(hay_ffmpeg, re_gbamedia, tmp_path):
    destinos = Destinos(tmp_path / "videos", tmp_path)
    wav = re_gbamedia / "windows.wav"
    resultado = convertir(Trabajo(wav, Opciones(modo_audio=4)), destinos)
    assert [f.name for f in resultado.ficheros] == ["windows.gbs"]
    assert resultado.frames == 0
    assert "64:1 Mono" in verificar(resultado.ficheros[0])


def test_rellenar_cluster(hay_ffmpeg, re_gbamedia, tmp_path):
    """La ROM sin parchear lee hasta el final de la cadena FAT."""
    destinos = Destinos(tmp_path / "videos", tmp_path)
    wav = re_gbamedia / "windows.wav"
    resultado = convertir(
        Trabajo(wav, Opciones(rellenar_cluster=32768)), destinos)
    assert resultado.ficheros[0].stat().st_size % 32768 == 0


# --- linea de ordenes ---------------------------------------------------

def test_argumentos_a_opciones():
    args = cli.construir_parser().parse_args(
        ["x.mp4", "-p", "estandar", "--modo", "32:1", "--canal", "der",
         "--volumen", "4", "--ajuste", "recorte", "--bpm", "140:150"])
    o = cli.opciones_desde_argumentos(args)
    assert o.preset == "estandar"
    assert o.modo_audio == 3
    assert o.canal == 1
    assert o.volumen == 2            # x4 es el indice 2
    assert o.ajuste == fit.RECORTE
    assert o.tempo == pytest.approx(1.071429, abs=1e-6)


def test_el_perfil_es_la_base_y_los_argumentos_lo_pisan(tmp_path):
    ruta = tmp_path / "p.json"
    guardar_perfil(Opciones(preset="compresion", brillo=15), ruta)
    args = cli.construir_parser().parse_args(
        ["x.mp4", "--perfil", str(ruta), "--brillo", "40"])
    o = cli.opciones_desde_argumentos(args)
    assert o.preset == "compresion"      # del perfil
    assert o.brillo == 40                # pisado por el argumento


def test_modos_de_audio_por_etiqueta_o_numero():
    assert cli._modo("16:1") == 2
    assert cli._modo("2") == 2
    assert cli._modo(None) is None
    for malo in ("9", "loquesea"):
        with pytest.raises(SystemExit):
            cli._modo(malo)


def test_reunir_recorre_carpetas(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.mp4").touch()
    (tmp_path / "sub" / "b.mp3").touch()
    (tmp_path / "notas.txt").touch()
    encontrados = [f.name for f in cli.reunir([tmp_path])]
    assert encontrados == ["a.mp4", "b.mp3"]
    with pytest.raises(SystemExit):
        cli.reunir([tmp_path / "no_existe"])


def test_simular_no_escribe_nada(hay_ffmpeg, fuentes, tmp_path, capsys):
    codigo = cli.main([str(fuentes / "Audio Video Sync Test_360p.mp4"),
                       "-o", str(tmp_path), "--simular"])
    assert codigo == 0
    assert "audiovid" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


# --- lotes --------------------------------------------------------------

def _manifiesto(tmp_path, ficheros, perfil=None, salida=None):
    import json as _json
    datos = {"ficheros": ficheros}
    if perfil:
        datos["perfil"] = perfil
    if salida:
        datos["salida"] = salida
    ruta = tmp_path / "lote.json"
    ruta.write_text(_json.dumps(datos), encoding="utf-8")
    return ruta


def test_las_tres_capas_del_lote(tmp_path):
    from gbamedia.jobs import batch
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.mp4").touch()
    ruta = _manifiesto(
        tmp_path,
        [{"origen": "a.mp4"},
         {"origen": "b.mp4", "opciones": {"preset": "alta", "brillo": 30},
          "nombre": "M00042"}],
        perfil={"preset": "compresion", "volumen": 1})

    perfiles, destinos, trabajos = batch.cargar(ruta)
    assert destinos is None
    assert perfiles.video.preset == "compresion"
    assert perfiles.musica.preset == "compresion", \
        "un 'perfil' a secas es el de los dos"
    # sin sobrescritura: hereda el perfil del lote
    assert trabajos[0].opciones.preset == "compresion"
    assert trabajos[0].opciones.volumen == 1
    # con sobrescritura: pisa solo lo que menciona
    assert trabajos[1].opciones.preset == "alta"
    assert trabajos[1].opciones.brillo == 30
    assert trabajos[1].opciones.volumen == 1, "el resto sigue siendo del lote"
    assert trabajos[1].nombre == "M00042"


def test_las_rutas_del_lote_son_relativas_al_manifiesto(tmp_path):
    from gbamedia.jobs import batch
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.mp4").touch()
    ruta = tmp_path / "sub" / "lote.json"
    ruta.write_text('{"ficheros": ["a.mp4"], '
                    '"salida": {"video": "fuera"}}', encoding="utf-8")
    _, destinos, trabajos = batch.cargar(ruta)
    assert trabajos[0].origen == tmp_path / "sub" / "a.mp4"
    assert destinos.video == tmp_path / "sub" / "fuera"
    assert destinos.musica == destinos.video


def test_lote_invalido(tmp_path):
    from gbamedia.jobs import batch
    for contenido in ('{"ficheros": []}',
                      '{"ficheros": ["no_existe.mp4"]}',
                      '{"ficheros": [{"origen": "a.mp4"}], "invento": 1}',
                      '{"ficheros": [{"nombre": "x"}]}',
                      '{"perfil": {"preset": "ninguno"}, "ficheros": ["a.mp4"]}',
                      '[]'):
        ruta = tmp_path / "malo.json"
        ruta.write_text(contenido, encoding="utf-8")
        with pytest.raises(batch.LoteInvalido):
            batch.cargar(ruta)


def test_el_lote_va_y_vuelve(tmp_path):
    from gbamedia.jobs import batch
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.mp3").touch()
    perfil = Opciones(preset="estandar")
    trabajos = [Trabajo(tmp_path / "a.mp4", perfil),
                Trabajo(tmp_path / "b.mp3", perfil.con(volumen=3), "tema")]
    destinos = Destinos(tmp_path / "v", tmp_path / "m")
    ruta = tmp_path / "ida.json"
    batch.guardar(ruta, perfil, destinos, trabajos)

    perfiles2, destinos2, trabajos2 = batch.cargar(ruta)
    assert perfiles2.video == perfil and perfiles2.musica == perfil
    assert destinos2 == destinos
    assert [t.opciones for t in trabajos2] == [t.opciones for t in trabajos]
    assert trabajos2[1].nombre == "tema"


def test_el_lote_guarda_los_dos_juegos_de_valores(tmp_path):
    """Video y musica tienen sus propios valores por defecto, y cada fichero
    hereda los de su clase."""
    from gbamedia.jobs import batch
    from gbamedia.jobs.options import Perfiles
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.mp3").touch()
    perfiles = Perfiles(Opciones(preset="compresion"), Opciones(modo_audio=0))
    trabajos = [Trabajo(tmp_path / "a.mp4", perfiles.video),
                Trabajo(tmp_path / "b.mp3", perfiles.musica)]
    ruta = tmp_path / "dos.json"
    batch.guardar(ruta, perfiles, None, trabajos)
    assert "perfil_musica" in ruta.read_text(encoding="utf-8")

    vuelta, _, trabajos2 = batch.cargar(ruta)
    assert vuelta == perfiles
    assert trabajos2[0].opciones.preset == "compresion"
    assert trabajos2[1].opciones.modo_audio == 0
    # ningun fichero se aparta de los suyos, asi que no se escribe nada propio
    assert [t.opciones for t in trabajos2] == [t.opciones for t in trabajos]


def test_cli_con_lote(hay_ffmpeg, fuentes, tmp_path, capsys):
    import json as _json
    ruta = tmp_path / "lote.json"
    ruta.write_text(_json.dumps({
        "perfil": {"preset": "compresion"},
        "salida": {"video": str(tmp_path / "v"), "musica": str(tmp_path / "m")},
        "ficheros": [{"origen": str(fuentes / "Audio Video Sync Test_360p.mp4"),
                      "opciones": {"preset": "alta"}}],
    }), encoding="utf-8")
    assert cli.main(["--lote", str(ruta), "--simular"]) == 0
    assert "audiovid" in capsys.readouterr().out


def test_cancelar_corta_la_conversion_sin_dejar_nada(hay_ffmpeg, fuentes,
                                                     tmp_path):
    """Parar tiene que parar de verdad y no dejar medio fichero.

    Todo se escribe al final, asi que soltar los trozos que no han empezado
    deja el destino como estaba.
    """
    import threading

    from gbamedia.jobs.parallel import Cancelado

    cancelar = threading.Event()
    cancelar.set()
    trabajo = Trabajo(fuentes / "Audio Video Sync Test_360p.mp4",
                      Opciones(duracion=2.0))
    destinos = Destinos(tmp_path / "v", tmp_path / "m")
    with pytest.raises(Cancelado):
        convertir(trabajo, destinos, cancelar=cancelar)
    assert not list((tmp_path / "v").glob("*"))


def test_cancelar_a_mitad_no_tarda_en_soltar(hay_ffmpeg, fuentes, tmp_path):
    """Se levanta la bandera mientras convierte: tiene que salir enseguida."""
    import threading
    import time

    from gbamedia.jobs.parallel import Cancelado

    cancelar = threading.Event()
    trabajo = Trabajo(fuentes / "Audio Video Sync Test_360p.mp4",
                      Opciones(preset="estandar", duracion=30.0))
    destinos = Destinos(tmp_path / "v", tmp_path / "m")

    def al_avanzar(hechos, total):
        cancelar.set()

    arranque = time.monotonic()
    with pytest.raises(Cancelado):
        convertir(trabajo, destinos, al_avanzar, cancelar=cancelar)
    assert time.monotonic() - arranque < 30
    assert not list((tmp_path / "v").glob("*"))


def test_sin_debug_no_hay_avisos(hay_ffmpeg, fuentes, tmp_path, monkeypatch):
    """El aviso de cadencia llego a proponer acelerar un 700 %: en modo normal
    ni se mide ni se cuenta."""
    from gbamedia.jobs import convert as modulo

    trabajo = Trabajo(fuentes / "furret walk (full version)_360p.mp4",
                      Opciones(preset="compresion", duracion=32.0))
    destinos = Destinos(tmp_path / "v", tmp_path)

    monkeypatch.setattr(modulo, "modo_depuracion", lambda: False)
    assert modulo.analizar(trabajo) == []
    assert modulo.convertir(trabajo, destinos).avisos == []

    monkeypatch.setattr(modulo, "modo_depuracion", lambda: True)
    assert modulo.analizar(trabajo), "con DEBUG_ON vuelve a avisar"


def test_el_factor_de_tempo_absurdo_no_se_propone():
    """Si la medida se va a un armonico, el remedio es peor que la
    enfermedad: mas vale callar."""
    from gbamedia.media import cadence
    assert cadence.aviso_ciclo(8.6 / 60.0) is None
    assert cadence.aviso_ciclo(140 / 60.0) is not None


def test_avisa_de_que_un_gbs_de_musica_secuestra_un_video(tmp_path):
    """FilmPlay empareja un .gbm con el .gbs que se llama igual: si la musica
    comparte carpeta con el video, un nombre repetido le cambia la banda
    sonora sin que nadie se entere."""
    from gbamedia.jobs.convert import colisiones

    class _Info:
        def __init__(self, es_video):
            self.es_video = es_video

    destinos = Destinos(tmp_path, tmp_path)          # todo junto
    (tmp_path / "tema.gbm").touch()
    musica = Trabajo(tmp_path / "tema.mp3", Opciones(), "tema", _Info(False))

    motivos = [m for _, m in colisiones([musica], destinos)]
    assert any("banda sonora" in m for m in motivos)


def test_no_avisa_cuando_no_hay_nada_que_pisar(tmp_path):
    from gbamedia.jobs.convert import colisiones

    class _Info:
        es_video = True

    destinos = Destinos(tmp_path / "v", tmp_path)
    trabajo = Trabajo(tmp_path / "a.mp4", Opciones(), "a", _Info())
    assert colisiones([trabajo], destinos) == []
