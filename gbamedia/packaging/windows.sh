#!/bin/bash
# Construye el paquete de Windows desde WSL, usando el Python de Windows.
#
# No hace falta ni maquina virtual ni CI: si el anfitrion es Windows con WSL2,
# el Python y el compilador de Windows se invocan desde aqui por la
# interoperabilidad de WSL. La extension en C se compila con MSVC, asi que el
# paquete sale igual de rapido que el de Linux.
#
# Requisitos en el lado de Windows:
#   - Python 3.11 o 3.12 (con `py` o en AppData)
#   - Build Tools de Visual Studio (para compilar `_fast.c`)
#
# Uso:  ./packaging/windows.sh            construye y prueba
#       DESTINO=/mnt/d/otra ./windows.sh    otra carpeta de construccion
#
# Para no repetirlo, se puede dejar fijado en packaging/local.env:
#       DESTINO=/mnt/d/Users/tuyo/Documents/gbamedia-build
#
# El arbol se copia a una carpeta de Windows porque compilar y empaquetar sobre
# \\wsl$\ es lento y PyInstaller se atraganta con las rutas UNC.
set -euo pipefail

AQUI=$(cd "$(dirname "$0")/.." && pwd)

# Ajustes de esta maquina (DESTINO, PYWIN...). No va al repositorio: la carpeta
# de construccion y donde este el Python de Windows son cosa de cada uno.
[[ -f "$AQUI/packaging/local.env" ]] && . "$AQUI/packaging/local.env"

DESTINO=${DESTINO:-/mnt/c/gbamedia-build}
FFMPEG=${FFMPEG:-https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip}

if [[ -z "${PYWIN:-}" ]]; then
  PYWIN=$(ls /mnt/c/Users/*/AppData/Local/Programs/Python/Python31*/python.exe \
          2>/dev/null | sort -r | head -1 || true)
fi
[[ -x "$PYWIN" ]] || { echo "no encuentro el Python de Windows; pon PYWIN=" >&2; exit 1; }
echo "python de windows: $("$PYWIN" --version)"

echo "== copiando el arbol a $DESTINO"
mkdir -p "$DESTINO"
# Lo excluido no se borra en el destino, que es justo lo que hace falta: el
# venv de Windows, la extension compilada y el ffmpeg descargado viven **solo**
# ahi y no deben desaparecer en cada pasada.
rsync -a --delete \
      --exclude '.venv*' --exclude build --exclude dist \
      --exclude '*.so' --exclude '*.pyd' --exclude 'bin/*.exe' \
      --exclude '*.egg-info' --exclude __pycache__ --exclude .pytest_cache \
      "$AQUI/" "$DESTINO/"

cd "$DESTINO"
if [[ ! -x .venv-win/Scripts/python.exe ]]; then
  echo "== creando el venv de windows"
  # Si quedaron restos, los borra Windows: sobre una unidad montada en WSL,
  # `rm -rf` se queda a medias con "permission denied" y deja el venv roto.
  [[ -e .venv-win ]] && cmd.exe /c "rmdir /s /q .venv-win" >/dev/null 2>&1
  "$PYWIN" -m venv .venv-win
fi
VENV=.venv-win/Scripts/python.exe

echo "== instalando"
# setuptools >= 77 hace falta para la licencia en formato PEP 639
# del pyproject; el que trae el venv de Windows por defecto es mas viejo
"$VENV" -m pip install -q --upgrade pip "setuptools>=77" wheel
"$VENV" -m pip install -q -e ".[gui,dev,dist]"

echo "== compilando la extension en C"
"$VENV" setup.py build_ext --inplace
"$VENV" -c "from gbamedia.core import fast; assert fast.hay_c(), 'sin nucleo en C'"

if [[ ! -f bin/ffmpeg.exe ]]; then
  echo "== descargando ffmpeg (compilacion GPL)"
  mkdir -p bin
  curl -sL --retry 3 -o /tmp/ffmpeg-win.zip "$FFMPEG"
  # Con python y no con unzip: WSL no siempre lo trae y esto ya depende de
  # tener un python a mano.
  python3 - "$PWD/bin" <<'FIN'
import sys, zipfile
from pathlib import Path
destino = Path(sys.argv[1])
destino.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile("/tmp/ffmpeg-win.zip") as z:
    for nombre in z.namelist():
        corto = nombre.rsplit("/", 1)[-1]
        if corto in ("ffmpeg.exe", "ffprobe.exe"):
            (destino / corto).write_bytes(z.read(nombre))
            print("extraido", corto)
FIN
fi

echo "== pruebas"
QT_QPA_PLATFORM=offscreen "$VENV" -m pytest -q

echo "== empaquetando"
# El .spec busca bin/ffmpeg.exe en GBAMEDIA_RAIZ, y quien lo lee es un proceso
# de Windows: con la ruta de WSL no encuentra nada y el paquete sale sin
# ffmpeg, que es justo lo que no se puede olvidar.
# Y hay que pasarla por WSLENV: las variables de entorno de WSL **no** cruzan
# a un proceso de Windows si no se nombran ahi.
RAIZ_WIN=$(wslpath -w "$DESTINO")
GBAMEDIA_RAIZ="$RAIZ_WIN" WSLENV=GBAMEDIA_RAIZ \
    "$VENV" -m PyInstaller --noconfirm --clean \
    --distpath dist --workpath build packaging/gbamedia.spec

# PyInstaller 6 mete lo empaquetado en _internal/, que es justo donde lo busca
# el localizador (sys._MEIPASS/bin).
[[ -f dist/gbamedia/_internal/bin/ffmpeg.exe ]] || {
  echo "el paquete ha salido sin ffmpeg" >&2; exit 1; }

echo
echo "listo: $DESTINO/dist/gbamedia/gbamedia.exe"
