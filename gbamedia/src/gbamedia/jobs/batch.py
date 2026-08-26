"""Lotes: un manifiesto con las opciones del conjunto y las de cada fichero.

Las tres capas del plan, de menor a mayor prioridad:

    valores por defecto  <  perfil del lote  <  sobrescritura por fichero

El manifiesto es el mismo formato que usa la ventana, de modo que un lote
preparado en la interfaz se relanza desde la terminal y al reves.

    {
      "perfil_video":  { "preset": "estandar" },
      "perfil_musica": { "modo_audio": 0 },
      "salida":  { "video": "/sd/MEDIA/videos", "musica": "/sd/MEDIA" },
      "ficheros": [
        { "origen": "intro.mp4" },
        { "origen": "baile.mp4", "opciones": { "tempo": 1.071429 } },
        { "origen": "tema.mp3", "opciones": { "modo_audio": 1 },
          "nombre": "tema principal" }
      ]
    }
"""
import json
from pathlib import Path

from .convert import Destinos, Trabajo
from .options import Opciones, Perfiles


class LoteInvalido(ValueError):
    pass


def cargar(ruta) -> tuple[Perfiles, Destinos | None, list[Trabajo]]:
    ruta = Path(ruta)
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    if not isinstance(datos, dict):
        raise LoteInvalido("el manifiesto tiene que ser un objeto JSON")

    sobra = set(datos) - {"perfil", "perfil_video", "perfil_musica",
                          "salida", "ficheros"}
    if sobra:
        raise LoteInvalido(f"claves desconocidas: {sorted(sobra)}")

    # "perfil" a secas es el formato viejo, de cuando habia uno solo. Y si no
    # se dicen los de la musica, son los mismos que los del video.
    try:
        comun = datos.get("perfil", {})
        video = Opciones.desde_json(datos.get("perfil_video", comun))
        musica = (Opciones.desde_json(datos["perfil_musica"])
                  if "perfil_musica" in datos else None)
    except ValueError as e:
        raise LoteInvalido(f"valores por defecto del lote: {e}")
    perfiles = Perfiles(video, musica)

    destinos = None
    if "salida" in datos:
        salida = datos["salida"]
        carpeta_video = salida.get("video") or salida.get("musica")
        carpeta_musica = salida.get("musica") or salida.get("video")
        if not carpeta_video:
            raise LoteInvalido("'salida' necesita 'video' o 'musica'")
        destinos = Destinos(_resolver(carpeta_video, ruta),
                            _resolver(carpeta_musica, ruta))

    entradas = datos.get("ficheros")
    if not entradas:
        raise LoteInvalido("el lote no tiene ficheros")

    trabajos = []
    for n, entrada in enumerate(entradas):
        if isinstance(entrada, str):
            entrada = {"origen": entrada}
        if "origen" not in entrada:
            raise LoteInvalido(f"el fichero {n} no dice su 'origen'")
        sobra = set(entrada) - {"origen", "opciones", "nombre"}
        if sobra:
            raise LoteInvalido(
                f"{entrada['origen']}: claves desconocidas {sorted(sobra)}")
        try:
            # La sobrescritura solo pisa lo que menciona; lo demas viene del
            # perfil del lote.
            opciones = perfiles.para(entrada["origen"]).con(
                **entrada.get("opciones", {}))
        except (TypeError, ValueError) as e:
            raise LoteInvalido(f"{entrada['origen']}: {e}")
        origen = _resolver(entrada["origen"], ruta)
        if not origen.is_file():
            raise LoteInvalido(f"no existe: {origen}")
        trabajos.append(Trabajo(origen, opciones, entrada.get("nombre")))
    return perfiles, destinos, trabajos


def _resolver(texto: str, manifiesto: Path) -> Path:
    """Las rutas del manifiesto se leen relativas a el, no al directorio actual.

    Asi un lote se puede mover de sitio con sus ficheros al lado.
    """
    ruta = Path(texto).expanduser()
    return ruta if ruta.is_absolute() else (manifiesto.parent / ruta).resolve()


def guardar(ruta, perfiles: Perfiles, destinos: Destinos | None,
            trabajos: list[Trabajo]) -> None:
    if isinstance(perfiles, Opciones):        # comodidad: un perfil para todo
        perfiles = Perfiles(perfiles)
    datos: dict = perfiles.a_json()
    if destinos is not None:
        datos["salida"] = {"video": str(destinos.video),
                           "musica": str(destinos.musica)}
    ficheros = []
    for t in trabajos:
        entrada: dict = {"origen": str(t.origen)}
        # Solo lo que se aparta de los valores por defecto de su clase
        suyos = perfiles.para(t.origen).a_json()
        propio = {k: v for k, v in t.opciones.a_json().items()
                  if v != suyos.get(k, getattr(Opciones(), k))}
        if propio:
            entrada["opciones"] = propio
        if t.nombre:
            entrada["nombre"] = t.nombre
        ficheros.append(entrada)
    datos["ficheros"] = ficheros
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
        f.write("\n")
