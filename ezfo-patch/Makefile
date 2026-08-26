DEVKIT  := /opt/devkitpro/devkitARM/bin
CC      := $(DEVKIT)/arm-none-eabi-gcc
LD      := $(DEVKIT)/arm-none-eabi-gcc
OBJCOPY := $(DEVKIT)/arm-none-eabi-objcopy
OBJDUMP := $(DEVKIT)/arm-none-eabi-objdump
NM      := $(DEVKIT)/arm-none-eabi-nm

FLASHCARTIO := gba-flashcartio/lib

# Vueltas del bucle de espera de respuesta de la SD (0x100000 = original)
SD_TIMEOUT ?= 0x100000

# Sectores de lectura adelantada (R12, informe §26 y §33). Cada uno son 512 B
# de cache dentro del blob. 16 es el maximo: el hueco de EWRAM donde vive el
# blob mientras se reproduce video son 17,4 KB, y con 32 sectores no cabe.
CACHE_SECTORS ?= 16

# Configuracion por defecto de la ROM principal (ver informe §25 y §26):
#   DISABLE_DMA=1   el driver copia con la CPU; FilmPlay ocupa DMA1 y DMA2 y
#                   gba-flashcartio solo sabe usar DMA3 o DMA1.
#   DISABLE_IRQ=0   las interrupciones siguen vivas durante la lectura, con el
#                   vector redirigido a un stub en IWRAM (R11). Sin esto el
#                   FIFO de audio se queda sin recargar en cada lectura.
DISABLE_DMA ?= 1
DISABLE_IRQ ?= 0

# -marm: la ROM llama en modo ARM.  -fno-builtin/-ffreestanding: sin libc.
# EZFO_ENABLE=1, ED_ENABLE=0: solo hace falta EZ Flash Omega.
CFLAGS := -ffunction-sections -fdata-sections -Ibuild/gen/ezflashomega -marm -mcpu=arm7tdmi -O2 -ffreestanding -fno-builtin -fno-common \
          -fomit-frame-pointer -mlong-calls -Wall -Wextra \
          -DFLASHCARTIO_ED_ENABLE=0 -DFLASHCARTIO_EZFO_ENABLE=1 -DEZFO_SD_TIMEOUT=$(SD_TIMEOUT) -DEZFO_CACHE_SECTORS=$(CACHE_SECTORS) \
          -DFLASHCARTIO_DISABLE_DMA=$(DISABLE_DMA) -DFLASHCARTIO_EZFO_DISABLE_IRQ=$(DISABLE_IRQ) $(EXTRA_DEFS)

LDFLAGS := -nostdlib -nostartfiles -Wl,--gc-sections -Wl,-u,ezfo_install -Wl,-u,ezfo_read_entry -Wl,-u,ezfo_eof_hook -T ezfo.ld -Wl,-Map,ezfo.map

OBJS := build/io_ezfo.o build/shim.o build/entry.o

all: ezfo.bin

build:
	@mkdir -p build

GEN := build/gen

# Copia generada de gba-flashcartio con EWRAM_CODE sin el atributo de seccion.
# Asi cada funcion cae en su propia .text.<nombre> y --gc-sections puede
# descartar _EZFO_writeSectors, que no se usa. El arbol vendorizado no se toca.
$(GEN)/sys.h: $(FLASHCARTIO)/sys.h
	@mkdir -p $(GEN)
	sed 's|__attribute__((section(".ewram"), long_call))|__attribute__((long_call))|' $< > $@

$(GEN)/ezflashomega/io_ezfo.h: $(FLASHCARTIO)/ezflashomega/io_ezfo.h
	@mkdir -p $(GEN)/ezflashomega
	cp $< $@

# El tiempo de espera de Wait_SD_Response se hace parametrizable: 0x100000
# vueltas son ~0,6 s de CPU bloqueada, y al agotarse el driver NO aborta, copia
# el buffer igual. Ver informe §27.
$(GEN)/ezflashomega/io_ezfo.c: $(FLASHCARTIO)/ezflashomega/io_ezfo.c
	@mkdir -p $(GEN)/ezflashomega
	sed 's|count > 0x100000|count > EZFO_SD_TIMEOUT|' $< > $@

GENSRC := $(GEN)/sys.h $(GEN)/ezflashomega/io_ezfo.h $(GEN)/ezflashomega/io_ezfo.c

build/io_ezfo.o: $(GENSRC) | build
	$(CC) $(CFLAGS) -c $(GEN)/ezflashomega/io_ezfo.c -o $@

build/shim.o: src/shim.c $(GENSRC) | build
	$(CC) $(CFLAGS) -c $< -o $@

ezfo.elf: $(OBJS) ezfo.ld
	$(LD) $(LDFLAGS) $(OBJS) -o $@

ezfo.bin: ezfo.elf
	$(OBJCOPY) -O binary $< $@
	$(NM) -n ezfo.elf > ezfo.sym
	@echo "--- simbolos ---"
	@$(NM) -n ezfo.elf | grep -E ' [TtDdBb] ' | head -30
	@echo "--- tamano ---"
	@ls -l ezfo.bin | awk '{printf "  ezfo.bin = %d bytes\n",$$5}'

dis: ezfo.elf
	$(OBJDUMP) -d $<

clean:
	rm -rf build ezfo.elf ezfo.bin ezfo.map ezfo.sym

build/entry.o: src/entry.S | build
	$(CC) $(CFLAGS) -c $< -o $@

# --- ROM de traza: FilmPlay real, con hitos por color (ver informe §18) ---
# Instrumentacion embebida en el propio shim (EZFO_TRACE), no un blob aparte:
# util para depurar un problema futuro de arranque en hardware, donde no hay
# depurador.
trace: ezfo-trace.bin

ezfo-trace.ld: ezfo.ld
	sed 's|ENTRY(ezfo_install)|ENTRY(ezfo_boot_mark)|' $< > $@

build/shim-trace.o: src/shim.c $(GENSRC) | build
	$(CC) $(CFLAGS) -DEZFO_TRACE=1 -c $< -o $@

ezfo-trace.elf: build/shim-trace.o build/io_ezfo.o build/entry.o ezfo-trace.ld
	$(LD) -nostdlib -nostartfiles -Wl,--gc-sections \
	      -Wl,-u,ezfo_boot_mark -Wl,-u,ezfo_read_entry \
	      -T ezfo-trace.ld -Wl,-Map,ezfo-trace.map \
	      build/shim-trace.o build/io_ezfo.o build/entry.o -o $@

ezfo-trace.bin: ezfo-trace.elf
	$(OBJCOPY) -O binary $< $@
	$(NM) -n ezfo-trace.elf > ezfo-trace.sym
	@ls -l $@ | awk '{printf "  ezfo-trace.bin = %d bytes\n",$$5}'
