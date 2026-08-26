# Todo ocurre dentro del venv del proyecto. Nada global.
PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: venv c test puro lento gui cli dist windows limpia

venv:
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e '.[dev]'
	$(PY) setup.py build_ext --inplace

# La extension en C es opcional: si no compila, el paquete tira de Python.
c:
	$(PY) setup.py build_ext --inplace

test:
	$(PY) -m pytest -q

# La misma suite con el nucleo de Python, que es la implementacion de
# referencia. Las dos tienen que dar el mismo byte.
puro:
	GBAMEDIA_PURO=1 $(PY) -m pytest -q

lento:
	$(PY) -m pytest -q -m lento

gui:
	$(PY) -m gbamedia.gui.window

cli:
	$(PY) -m gbamedia

dist:
	GBAMEDIA_RAIZ=$(CURDIR) $(PY) -m PyInstaller --noconfirm --clean \
		--distpath dist --workpath build packaging/gbamedia.spec

# Paquete de Windows desde WSL, con el Python y el MSVC del anfitrion.
windows:
	./packaging/windows.sh

limpia:
	rm -rf build dist *.egg-info
	find src -name '*.so' -o -name '*.pyd' | xargs -r rm -f
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
