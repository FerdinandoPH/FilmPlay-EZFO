"""Codificacion de video repartida entre varios trabajadores.

El formato no tiene keyframes: el frame 0 se codifica contra un framebuffer
negro y el decodificador se limita a aplicar diferencias. Eso quiere decir que
**cortar el video en trozos y arrancar cada trozo con la referencia a negro
produce un fichero igual de valido**; el codificador original hace lo mismo
cada 600 frames por su cuenta. Lo unico que cuesta es que el primer frame de
cada trozo sale caro, y aun asi el control de tamano lo limita a `FrameSize`.

Con eso, un video se reparte entre todos los nucleos sin tocar el formato. El
proceso principal solo decodifica (1,4 ms por frame) y va repartiendo trozos.

Con el nucleo en C se reparte entre **hilos**, porque el C suelta el GIL
mientras codifica y asi los frames no hay que copiarlos a ningun sitio: pasar
un video de dos minutos a los procesos son 124 MB por las tuberias, mas de lo
que cuesta codificarlo. Sin el nucleo en C manda el GIL y hacen falta procesos.
"""
import multiprocessing
import os
import threading
from collections import deque
from concurrent.futures import (ProcessPoolExecutor, ThreadPoolExecutor,
                                TimeoutError)

from ..core.gbm_encode import CALIDADES, Calidad, CodificadorVideo
from ..core.fast import nucleo
from ..errors import Cancelado

TROZO = 25                # frames por trozo: 2,5 s de video
EN_VUELO = 2              # trozos de mas que se dejan encolados por proceso
ATENCION = 0.2            # cada cuanto se mira si hay que parar, en segundos


__all__ = ["Cancelado", "codificar_video", "trabajadores_por_defecto",
           "TROZO"]


def trabajadores_por_defecto(pedidos: int = 0) -> int:
    if pedidos:
        return max(1, pedidos)
    return max(1, min(os.cpu_count() or 1, 16))


# Ni la bandera de cancelacion ni el contador se pueden pasar como argumento de
# la tarea: los objetos de multiprocessing solo viajan por herencia al arrancar
# el proceso, que es lo que hace `initargs`.
_CANCELAR = None
_HECHOS = None


class _Contador:
    """Lo mismo que un `multiprocessing.Value`, para los hilos."""

    def __init__(self):
        self.value = 0
        self._cerrojo = threading.Lock()

    def get_lock(self):
        return self._cerrojo


def _iniciar(bandera, contador):
    global _CANCELAR, _HECHOS
    _CANCELAR, _HECHOS = bandera, contador


def _codificar_trozo(tarea):
    frames, calidad = tarea
    cod = CodificadorVideo(calidad)
    payloads = []
    for frame in frames:
        # Mirar la bandera frame a frame es lo que hace que "Parar" pare en
        # decimas y no cuando acabe el trozo que cada proceso tenga entre manos.
        if _CANCELAR is not None and _CANCELAR.is_set():
            raise Cancelado()
        payloads.append(cod.frame(frame))
        if _HECHOS is not None:
            # El progreso tiene que ser por frame y no por trozo: con mas
            # procesos que trozos, todos acaban a la vez y la barra daria un
            # salto del 0 al 100.
            with _HECHOS.get_lock():
                _HECHOS.value += 1
    return payloads


def _agrupar(frames, trozo):
    lote = []
    for frame in frames:
        lote.append(frame)
        if len(lote) == trozo:
            yield lote
            lote = []
    if lote:
        yield lote


def _secuencial(frames, calidad, trozo, progreso, cancelar):
    """Un solo proceso, pero **con los mismos cortes**.

    Que el resultado no dependa del numero de procesos es lo que permite
    comparar salidas y reproducir una conversion en otra maquina.
    """
    payloads = []
    for lote in _agrupar(frames, trozo):
        if cancelar is not None and cancelar.is_set():
            raise Cancelado()
        payloads.extend(_codificar_trozo((lote, calidad)))
        if progreso:
            progreso(len(payloads))
    return payloads


def codificar_video(frames, calidad: Calidad | str = "alta", *,
                    trabajadores: int = 0, trozo: int = TROZO,
                    progreso=None, cancelar=None) -> list[bytes]:
    """Payloads de todos los frames, en orden.

    `progreso(hechos)` se llama al terminar cada trozo. `cancelar` es un
    `threading.Event`: si se levanta, se sueltan los trozos que no han empezado
    y se lanza `Cancelado`. Con `trozo <= 0` no se corta: el video entero va
    contra una sola referencia, como antes de que esto existiera.
    """
    if isinstance(calidad, str):
        calidad = CALIDADES[calidad]
    trabajadores = trabajadores_por_defecto(trabajadores)
    if trozo <= 0:
        trozo = 1 << 30
    if trabajadores == 1:
        return _secuencial(frames, calidad, trozo, progreso, cancelar)

    payloads: list[bytes] = []
    pendientes: deque = deque()
    tope = trabajadores + EN_VUELO

    def cancelado():
        return cancelar is not None and cancelar.is_set()

    def avisa():
        """Frames ya codificados, esten o no recogidos.

        Los trozos se recogen en orden pero se codifican todos a la vez, asi
        que lo que cuenta es lo que dicen los procesos.
        """
        if progreso:
            progreso(contador.value)

    def recoge():
        """Espera al trozo mas antiguo, mirando de reojo si hay que parar.

        Esperarlo a secas dejaba a "Parar" tardando lo que tardase el trozo
        que estuviera en marcha.
        """
        while True:
            if cancelado():
                raise Cancelado()
            try:
                datos = pendientes[0].result(timeout=ATENCION)
            except TimeoutError:
                avisa()
                continue
            break
        pendientes.popleft()
        payloads.extend(datos)
        avisa()

    if nucleo is not None:
        bandera, contador = threading.Event(), _Contador()
        _iniciar(bandera, contador)
        piscina = ThreadPoolExecutor(max_workers=trabajadores)
    else:
        # `spawn` y no `fork`: este camino solo se toma sin el nucleo en C, y
        # el que llama puede ser la ventana, que tiene hilos de Qt en marcha.
        # Bifurcar un proceso con hilos vivos es una fuente de bloqueos (y
        # Python ya avisa de ello). Arrancar de cero cuesta unas decimas por
        # trabajador, nada al lado de lo que tarda codificar en Python.
        contexto = multiprocessing.get_context("spawn")
        bandera = contexto.Event()
        contador = contexto.Value("i", 0)
        piscina = ProcessPoolExecutor(max_workers=trabajadores,
                                      mp_context=contexto,
                                      initializer=_iniciar,
                                      initargs=(bandera, contador))
    with piscina:
        try:
            for lote in _agrupar(frames, trozo):
                if cancelado():
                    raise Cancelado()
                pendientes.append(
                    piscina.submit(_codificar_trozo, (lote, calidad)))
                while len(pendientes) >= tope:
                    recoge()
            while pendientes:
                recoge()
        except BaseException:
            # No dejar procesos trabajando en un resultado que nadie va a
            # recoger: se suelta lo que no ha empezado y se avisa a lo que si.
            bandera.set()
            piscina.shutdown(wait=False, cancel_futures=True)
            raise
    return payloads
