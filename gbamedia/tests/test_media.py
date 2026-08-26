"""Entrada moderna: sondeo, escalado y cadencia."""
from fractions import Fraction

import numpy as np
import pytest

from gbamedia.media import cadence, decode, fit, probe

SYNC = "Audio Video Sync Test_360p.mp4"
FURRET = "furret walk (full version)_360p.mp4"
FURRET_150 = "furret walk 150bpm.mp4"


# --- escalado -----------------------------------------------------------

def test_las_tres_politicas_de_ajuste():
    barras = fit.filtro_escalado(fit.BARRAS)
    recorte = fit.filtro_escalado(fit.RECORTE)
    estirado = fit.filtro_escalado(fit.ESTIRADO)
    assert "decrease" in barras and "pad=240:160" in barras
    assert "increase" in recorte and "crop=240:160" in recorte
    assert estirado == "scale=240:160"
    with pytest.raises(ValueError):
        fit.filtro_escalado("loquesea")


def test_preproceso_neutro_no_mete_filtros():
    assert fit.Imagen().neutro
    assert fit.filtro_imagen(fit.Imagen()) == ""
    assert "eq=" in fit.filtro_imagen(fit.Imagen(brillo=10))
    assert "unsharp" in fit.filtro_imagen(fit.Imagen(realce=20))


# --- cadencia -----------------------------------------------------------

def test_bpm_validos_son_los_que_caen_en_la_rejilla():
    """Un tiempo tiene que durar un multiplo exacto de 100 ms."""
    for bpm in cadence.bpm_validos(60, 300):
        periodo_ms = 60000 / bpm
        assert abs(periodo_ms / 100 - round(periodo_ms / 100)) < 1e-9
        assert abs(cadence.frames_por_ciclo(bpm)
                   - round(cadence.frames_por_ciclo(bpm))) < 1e-9
    assert 120.0 in cadence.bpm_validos()
    assert 150.0 in cadence.bpm_validos()


def test_el_caso_de_furret_walk():
    """140 BPM da 4,29 frames por ciclo; 150 los deja en 4 clavados."""
    assert cadence.frames_por_ciclo(140) == pytest.approx(4.2857, abs=1e-4)
    assert cadence.bpm_mas_cercano(140) == 150.0
    assert cadence.factor_tempo(140, 150) == pytest.approx(1.071429, abs=1e-6)
    assert cadence.frames_por_ciclo(150) == 4.0


def test_aviso_de_fps():
    assert cadence.aviso_fps(Fraction(30)) is None
    assert cadence.aviso_fps(Fraction(10)) is None
    assert cadence.aviso_fps(Fraction(25)).codigo == cadence.FPS
    assert cadence.aviso_fps(Fraction(24000, 1001)).codigo == cadence.FPS
    assert cadence.aviso_fps(Fraction(5)).arreglo is None, \
        "no se puede inventar movimiento que no esta"
    assert cadence.aviso_fps(Fraction(25)).arreglo == {"mezclar_frames": True}


def test_aviso_de_ciclo():
    assert cadence.aviso_ciclo(1.0) is None          # el patron de sincronia
    assert cadence.aviso_ciclo(2.5) is None          # furret walk arreglado
    aviso = cadence.aviso_ciclo(2.3333)              # furret walk original
    assert aviso.codigo == cadence.CICLO
    assert "150.0" in aviso.sugerencia
    # El arreglo viaja con el aviso: nadie tiene que copiar el factor a mano
    assert aviso.arreglo == {"tempo": 1.071429}


def test_el_arreglo_del_aviso_hace_desaparecer_el_aviso():
    """Aplicar lo que propone tiene que resolverlo de verdad, no aliviarlo."""
    aviso = cadence.aviso_ciclo(140 / 60.0)
    factor = aviso.arreglo["tempo"]
    assert cadence.aviso_ciclo(140 / 60.0 * factor) is None


def test_la_medida_se_redondea_al_bpm_entero():
    assert cadence.bpm_medido(2.331) == 140.0
    assert cadence.bpm_medido(1.003) == 60.0


def test_frecuencia_dominante_sobre_una_senal_conocida():
    """Un parpadeo cada 4 frames a 10 fps son 2,5 Hz."""
    marcos = []
    for i in range(400):
        v = 255 if i % 4 == 0 else 0
        marcos.append(np.full((160, 240, 3), v, dtype=np.uint8))
    assert cadence.frecuencia_dominante(marcos) == pytest.approx(2.5, abs=0.1)


def test_una_ventana_corta_no_da_medida():
    """Mejor no decir nada que mandar a retocar el tempo de un video sano.

    Por debajo de 30 s el pico mas alto del espectro deja de ser el
    fundamental: furret walk llega a medirse a 210 BPM en un trozo de 19 s.
    """
    energia = cadence.Energia()
    for i in range(100):
        energia.anadir(np.full((16, 24), 255 if i % 4 == 0 else 0,
                               dtype=np.uint8))
    assert not energia.fiable
    assert energia.frecuencia() == 0.0
    assert cadence.aviso_ciclo(energia.frecuencia()) is None


# --- duracion del .gbs companero ---------------------------------------

def test_ajustar_duracion():
    pcm = np.ones((44100, 2), dtype=np.int16)
    assert len(decode.ajustar_duracion(pcm, 0.5)) == 22050
    largo = decode.ajustar_duracion(pcm, 2.0)
    assert len(largo) == 88200
    assert np.all(largo[44100:] == 0), "el hueco se rellena con silencio"
    assert decode.ajustar_duracion(pcm, 1.0) is pcm


# --- cadenas de filtros -------------------------------------------------

def test_el_tempo_toca_los_dos_flujos():
    o = decode.Opciones(tempo=1.071429)
    assert "setpts=PTS/1.071429" in decode.cadena_video(o)
    assert "atempo=1.071429" in decode.cadena_audio(o)


def test_atempo_se_encadena_fuera_de_rango():
    """atempo solo acepta 0,5..2 de una vez."""
    assert decode.cadena_audio(decode.Opciones(tempo=5.0)).count("atempo") == 3
    assert decode.cadena_audio(decode.Opciones(tempo=0.25)).count("atempo") == 2


def test_mezclar_frames_en_vez_de_descartar():
    normal = decode.cadena_video(decode.Opciones())
    mezcla = decode.cadena_video(decode.Opciones(mezclar_frames=True))
    assert "fps=10" in normal and "minterpolate" not in normal
    assert "mi_mode=blend" in mezcla


# --- con ffmpeg de verdad ----------------------------------------------

def test_sondeo(hay_ffmpeg, fuentes):
    info = probe.sondear(fuentes / SYNC)
    assert info.es_video and info.tiene_audio
    assert (info.ancho, info.alto) == (640, 360)
    assert info.fps == 30
    assert info.duracion == pytest.approx(63.09, abs=0.1)
    assert info.frames_destino == 631


def test_un_wav_no_es_video(hay_ffmpeg, re_gbamedia):
    info = probe.sondear(re_gbamedia / "windows.wav")
    assert not info.es_video and info.tiene_audio


def test_frames_y_audio(hay_ffmpeg, fuentes):
    info = probe.sondear(fuentes / SYNC)
    opciones = decode.Opciones(duracion=6)
    marcos = [f.copy() for f in decode.frames(info, opciones)]
    assert len(marcos) == 60
    assert marcos[0].shape == (160, 240, 3)
    assert marcos[0].dtype == np.uint8

    pcm = decode.audio(info, opciones)
    assert pcm.dtype == np.int16 and pcm.shape[1] == 2
    assert len(pcm) == pytest.approx(6 * 44100, rel=0.02)


@pytest.mark.parametrize("politica", list(fit.AJUSTES))
def test_las_tres_politicas_dan_240x160(hay_ffmpeg, fuentes, politica):
    info = probe.sondear(fuentes / SYNC)
    opciones = decode.Opciones(ajuste=politica, duracion=1)
    marco = next(iter(decode.frames(info, opciones)))
    assert marco.shape == (160, 240, 3)


@pytest.mark.lento
def test_la_cadencia_medida_cuadra_con_el_informe(hay_ffmpeg, fuentes):
    """Las tres cifras de INFORME_VIABILIDAD.md §34, medidas de nuevo."""
    esperado = {SYNC: (1.0, False), FURRET: (2.333, True),
                FURRET_150: (2.5, False)}
    for nombre, (hz_doc, avisa) in esperado.items():
        info = probe.sondear(fuentes / nombre)
        energia = cadence.Energia()
        for marco in decode.frames(info, decode.Opciones(duracion=40)):
            energia.anadir(marco)
        hz = energia.frecuencia()
        assert hz == pytest.approx(hz_doc, abs=0.02), nombre
        assert (cadence.aviso_ciclo(hz) is not None) is avisa, nombre
