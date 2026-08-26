#!/usr/bin/env python3
"""Aplica el parche de EZ Flash Omega a FilmPlay.gba.

Tres cambios sobre la ROM original:

1. Se anade el blob EZFO (ezfo.bin) en el espacio libre a partir de 0x08400400,
   junto con un pequeno instalador de arranque.

2. Se desvia el arranque. La cadena original es
       0x08000000 -> 0x083FFFEC -> 0x08400000 -> [desbloqueo Supercard] -> crt0
   El codigo de desbloqueo se copia a IWRAM 0x03000000 y se ejecuta desde ahi.
   Se sustituye por un salto absoluto al instalador, que copia el blob a
   0x03004000, llama a ezfo_install() y continua al crt0 original en 0x080000C0.

3. Se parchean los tres cuerpos de la rutina de lectura de sector para que
   salten a ezfo_read_entry. Como son copiados a RAM por FilmPlay, parchear el
   original en ROM hace que toda copia herede el cambio.

Uso:  python3 patch.py [rom_entrada] [rom_salida]
"""
import hashlib
import os
import struct
import sys

from fixes import fatfix, portfix, bpbfix, eoffix

HERE = os.path.dirname(os.path.abspath(__file__))

# --trace construye la variante instrumentada del shim: FilmPlay real, mas
# hitos de arranque por color de fondo, para depurar en hardware donde no hay
# depurador. Ver informe §18.
TRACE = "--trace" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]

if TRACE:
    BLOB, SYMS = "ezfo-trace.bin", "ezfo-trace.sym"
    ENTRY_SYM = "ezfo_boot_mark"
    default_out = "FilmPlay-EZFO-trace.gba"
else:
    BLOB, SYMS = "ezfo.bin", "ezfo.sym"
    ENTRY_SYM = None            # nada del blob se llama en el arranque
    default_out = "FilmPlay-EZFO.gba"

BLOB = os.path.join(HERE, BLOB)
SYMS = os.path.join(HERE, SYMS)

ROM_IN = args[0] if len(args) > 0 else os.path.join(HERE, "..", "FilmPlay.gba")
ROM_OUT = args[1] if len(args) > 1 else os.path.join(HERE, "..", default_out)

BASE = 0x08000000

# --- disposicion en RAM del blob: se lee del ELF, nunca a mano ---
def load_syms():
    out = {}
    for line in open(SYMS):
        parts = line.split()
        if len(parts) == 3:
            out[parts[2]] = int(parts[0], 16)
    return out

SYM = load_syms()
BLOB_RAM = SYM["__blob_start"]
ENTRY_ADDR = SYM[ENTRY_SYM] if ENTRY_SYM else None
EZFO_READ_ENTRY = SYM.get("ezfo_read_entry", 0)
EOF_HOOK = SYM.get("ezfo_eof_hook", 0)

# --- disposicion en ROM ---
INSTALLER_ROM = 0x08400400     # instalador de arranque
BLOB_ROM = 0x08400500          # blob EZFO

# --- puntos de parcheo en la ROM original ---
UNLOCK_STUB = 0x08400038       # codigo de desbloqueo Supercard (se copia a IWRAM)
CRT0 = 0x080000C0              # entrada real de FilmPlay
BODIES = [0x08022124, 0x080C3CDC, 0x08123E40]


def w(v):
    return struct.pack("<I", v)


def build_installer(blob_words, call_addr=None):
    """Instalador de arranque, ejecutado desde ROM.

    Copia el blob a IWRAM y salta al crt0 original. Si call_addr no es None,
    llama antes a esa direccion (solo lo usa la ROM de diagnostico).

    En la ROM normal NO se llama a nada del blob desde aqui: la deteccion de
    la flashcart es perezosa, en la primera lectura, porque los caminos de
    fallo de _EZFO_startUp dejan la ROM desmapeada y este codigo vive en ROM.
    Ver el comentario de ezfo_state en src/shim.c.

    Los desplazamientos del pool de literales se calculan, nunca se escriben a
    mano: hacerlo a mano ya produjo un fallo una vez.
    """
    LDR_PC = 0xE59F0000            # ldr rX, [pc, #imm]  (rX en bits 12-15)

    code = [
        ("lit", 0, "blob_rom"),    # ldr r0, =BLOB_ROM
        ("lit", 1, "blob_ram"),    # ldr r1, =BLOB_RAM
        ("lit", 2, "words"),       # ldr r2, =blob_words
        ("raw", 0xE4903004),       # ldr r3, [r0], #4
        ("raw", 0xE4813004),       # str r3, [r1], #4
        ("raw", 0xE2522001),       # subs r2, r2, #1
        ("raw", 0x1AFFFFFB),       # bne  -> ldr r3
    ]
    if call_addr is not None:
        code += [
            ("lit", 0, "entry"),   # ldr r0, =entrada del blob
            ("raw", 0xE1A0E00F),   # mov lr, pc
            ("raw", 0xE12FFF10),   # bx  r0
        ]
    code += [
        ("lit", 0, "crt0"),        # ldr r0, =CRT0
        ("raw", 0xE12FFF10),       # bx  r0
    ]

    pool = ["blob_rom", "blob_ram", "words"]
    if call_addr is not None:
        pool.append("entry")
    pool.append("crt0")
    values = {"blob_rom": BLOB_ROM, "blob_ram": BLOB_RAM,
              "words": blob_words, "crt0": CRT0}
    if call_addr is not None:
        values["entry"] = call_addr

    pool_base = len(code) * 4
    out = []
    for i, ins in enumerate(code):
        if ins[0] == "raw":
            out.append(ins[1])
        else:
            _, reg, name = ins
            lit_at = pool_base + pool.index(name) * 4
            imm = lit_at - (i * 4 + 8)
            assert 0 <= imm < 4096, f"literal fuera de alcance: {name}"
            out.append(LDR_PC | (reg << 12) | imm)
    out += [values[n] for n in pool]
    return b"".join(w(x) for x in out)


# La ROM no se distribuye con el parche -tiene dueno-, asi que lo unico que
# puede hacer esto es comprobar que la copia de quien parchea es la que se
# analizo. Un hash identifica el fichero sin contener nada de el.
SHA_ESPERADO = ("60895549e302e68832c0586ed4e51cdc"
                "b091ae8c90fe9ca3ccdf9c6f2b5d773a")


def comprobar(rom: bytes) -> None:
    visto = hashlib.sha256(rom).hexdigest()
    if visto == SHA_ESPERADO:
        return
    print("aviso: esta no es la ROM sobre la que se dedujeron los offsets")
    print(f"  esperado {SHA_ESPERADO}")
    print(f"  leido    {visto}")
    print("  el parche se aplica igual, pero puede caer en el sitio "
          "equivocado; comprueba el resultado antes de usarlo")


def main():
    rom = bytearray(open(ROM_IN, "rb").read())
    comprobar(bytes(rom))
    blob = open(BLOB, "rb").read()
    assert len(blob) % 4 == 0, "el blob debe estar alineado a 4"

    orig_len = len(rom)
    need = (BLOB_ROM - BASE) + len(blob)
    if len(rom) < need:
        rom.extend(b"\xff" * (need - len(rom)))

    installer = build_installer(len(blob) // 4, ENTRY_ADDR)

    def poke(addr, data, what):
        off = addr - BASE
        assert off + len(data) <= len(rom), what
        rom[off:off + len(data)] = data
        print(f"  0x{addr:08X}  {len(data):5d} B  {what}")

    print("parcheando:")
    poke(INSTALLER_ROM, installer, "instalador de arranque")
    poke(BLOB_ROM, blob, "blob EZFO")

    # Desvio del arranque: salto absoluto al instalador. Funciona igual desde
    # IWRAM porque `ldr pc,[pc,#-4]` toma el destino del literal contiguo.
    poke(UNLOCK_STUB, w(0xE51FF004) + w(INSTALLER_ROM),
         "desvio de arranque (sustituye desbloqueo Supercard)")

    # Cuerpos de la rutina de lectura -> salto absoluto al shim.
    # Se salta, no se llama, asi que lr sigue apuntando al llamante de FilmPlay.
    for body in BODIES:
        poke(body, w(0xE51FF004) + w(EZFO_READ_ENTRY), "cuerpo de lectura de sector")

    # R9: tests de fin de cadena FAT no conformes, en todas las copias
    print("arreglando fin de cadena FAT (R9):")
    nfixed = fatfix.apply(rom, BASE)

    # R10: sectores reservados del BPB truncados a 8 bits
    print("arreglando sectores reservados del BPB (R10):")
    bpbfix.apply(rom, BASE)

    # Puerto de estado de tarjeta alojado dentro de la ROM
    print("neutralizando el puerto 0x083F0000:")
    portfix.apply(rom, BASE)

    # R13: parar en el tamano del fichero, no al final de la cadena
    if EOF_HOOK:
        print("parando en el tamano del fichero (R13):")
        eoffix.apply(rom, EOF_HOOK, BASE)

    open(ROM_OUT, "wb").write(rom)
    print()
    print(f"ROM original : {orig_len} bytes")
    print(f"ROM parcheada: {len(rom)} bytes -> {ROM_OUT}")
    print(f"blob EZFO    : {len(blob)} bytes en ROM 0x{BLOB_ROM:08X} -> RAM 0x{BLOB_RAM:08X}")
    if ENTRY_SYM:
        print(f"llamada arranque: {ENTRY_SYM} = 0x{ENTRY_ADDR:08X}")
    else:
        print("llamada arranque: ninguna (deteccion perezosa en la 1a lectura)")
    if TRACE:
        print("modo         : TRAZA (FilmPlay con hitos por color)")
    print(f"shim         : ezfo_read_entry = 0x{EZFO_READ_ENTRY:08X}")
    print(f"sitios FAT   : {nfixed} arreglados")


if __name__ == "__main__":
    main()
