/* Shim que sustituye la rutina de lectura de sector de FilmPlay.
 *
 * Contrato heredado del cuerpo original (ver informe §13.2):
 *   r0 = puntero destino (ya calculado por el stub de entrada)
 *   r1 = numero de sector (LBA absoluto)
 *   r14 = direccion de retorno
 *
 * Se llega aqui por un salto absoluto instalado sobre el cuerpo original, no
 * por un BL, asi que lr sigue apuntando al llamante real de FilmPlay y basta
 * con retornar normalmente.
 *
 * Todo el codigo vive en RAM: la EZ Flash Omega deja la ROM inaccesible
 * mientras lee, asi que no se puede ejecutar ni leer nada desde ROM aqui.
 */

#include "io_ezfo.h"

/* Waitstates de ROM. La EZ Flash Omega original se cuelga leyendo la SD con
 * 3,1; hacen falta 3,2 o mas lento (README de gba-flashcartio). El bit 4 de
 * WAITCNT es el segundo acceso de WS0: 1 = 1 ciclo (3,1), 0 = 2 ciclos (3,2).
 * Se fuerza alrededor de cada lectura y se restaura despues, de modo que da
 * igual lo que FilmPlay haga con el registro por su cuenta. */
#define REG_WAITCNT (*(vu16*)0x04000204)

/* El cuerpo original (0x08022124-0x0802220C) NO toca WAITCNT: sale con
 * `pop {r3-r7}; bx lr` y nada mas. El `strh` a 0x04000204 que parecia suyo es
 * de la funcion vecina, cuyo epilogo es `pop {r3,r4,ip}`.
 *
 * Asi que aqui se guarda y se restaura, sin imponer ningun valor. Durante la
 * lectura se fuerza 4,2 sin prefetch: la EZ Flash Omega se cuelga leyendo la SD
 * con 3,1 (README de gba-flashcartio), y no hay nada que precargar porque el
 * codigo corre en IWRAM con la ROM desmapeada. */
#define WAITCNT_LECTURA 0x0002

#define ROMPAGE_PSRAM 0x200

/* --- Telemetria de hito por color de fondo (solo en la build de traza) ---
 *
 * En hardware no hay depurador. Esta build arranca FilmPlay de verdad y marca
 * por color hasta donde llega, para saber si pide siquiera el primer sector.
 * Ver informe §18.
 */
#ifndef EZFO_TRACE
#define EZFO_TRACE 0
#endif

#if EZFO_TRACE
#define REG_DISPCNT (*(vu16*)0x04000000)
#define REG_VCOUNT (*(vu16*)0x04000006)
#define PALETTE0 (*(vu16*)0x05000000)

#define ROJO 0x001F
#define VERDE 0x03E0
#define AMARILLO 0x03FF
#define MAGENTA 0x7C1F
#define CIAN 0x7FE0
#define BLANCO 0x7FFF

/* Repinta cada frame: si FilmPlay tiene una IRQ de VBlank que toca la paleta,
 * el color se impone igual. */
static void EWRAM_CODE mark(u16 c, u32 n) {
  while (n--) {
    REG_DISPCNT = 0x0000;
    PALETTE0 = c;
    while (REG_VCOUNT != 160)
      ;
    while (REG_VCOUNT == 160)
      ;
  }
}

static int EWRAM_BSS trace_n;

/* Llamado por el instalador de arranque, justo antes de saltar al crt0. */
void EWRAM_CODE ezfo_boot_mark(void) {
  mark(ROJO, 45);
}
#endif

/* 0 = sin inicializar, 1 = lista, 2 = no hay flashcart utilizable.
 * Vive en .sbss, que el instalador deja a cero, asi que 0 = sin inicializar.
 *
 * La inicializacion es PEREZOSA, en la primera lectura, y no en el arranque.
 * Motivo: _EZFO_startUp conmuta la pagina de ROM del cartucho, y por todos sus
 * caminos de fallo RETORNA CON LA ROM DESMAPEADA (la prueba de la pagina de
 * bootloader deja esa pagina puesta; el barrido de NOR agotado deja la 511).
 * Llamarla desde el instalador de arranque, que se ejecuta EN ROM, significa
 * que cualquier fallo de deteccion devuelve el control a una ROM inaccesible:
 * cuelgue total, pantalla negra y sin respuesta al mando. Desde aqui se
 * ejecuta en RAM y se puede restaurar la pagina antes de volver. */
static int EWRAM_BSS ezfo_state;

/* Restaura la ROM cuando la deteccion falla y la ha dejado desmapeada.
 * Misma secuencia de desbloqueo que SetRompage de gba-flashcartio. */
static void EWRAM_CODE ezfo_restore_rom(void) {
  *(vu16*)0x9fe0000 = 0xd200;
  *(vu16*)0x8000000 = 0x1500;
  *(vu16*)0x8020000 = 0xd200;
  *(vu16*)0x8040000 = 0x1500;
  *(vu16*)0x9880000 = ROMPAGE_PSRAM;
  *(vu16*)0x9fc0000 = 0x1500;
}

void EWRAM_CODE ezfo_install(void) {
  if (_EZFO_startUp()) {
    ezfo_state = 1;
  } else {
    ezfo_restore_rom();
    ezfo_state = 2;
  }
}

/* --- R11: la interrupcion de audio pasaba por un enganche en ROM ---
 *
 * FilmPlay alimenta los FIFO de sonido desde la interrupcion de Timer 1, pero
 * el vector 0x03007FFC NO apunta a su manejador: apunta a 0x08400068, un
 * enganche del Supercard que mira combos de teclas para resetear y solo
 * despues encadena al manejador real, cuya direccion guarda en 0x03007FA0.
 * Ese manejador real vive en EWRAM (0x0200039C) y no toca la ROM.
 *
 * El problema es el enganche: esta EN ROM. Y _EZFO_readSectors desmapea TODA
 * la ROM del cartucho mientras lee (SetRompage(ROMPAGE_BOOTLOADER)), asi que
 * durante la lectura ese codigo no existe. Por eso el driver desactiva las
 * interrupciones por defecto, y por eso el sonido zumba en cada lectura: los
 * FIFO siguen sonando pero nadie los rellena. Se oye con DMA y sin el, que es
 * lo que descarto R6.
 *
 * Aqui se sustituye el enganche por uno equivalente en IWRAM. Lo unico que se
 * pierde son los combos de teclas del Supercard, que en una Omega no sirven
 * para nada. Con eso, todo el camino de la interrupcion vive en RAM y se
 * pueden dejar las interrupciones activas durante la lectura
 * (FLASHCARTIO_EZFO_DISABLE_IRQ=0).
 */
#if FLASHCARTIO_EZFO_DISABLE_IRQ == 0

/* Equivalente del enganche original, sin los combos de teclas:
 *   REG_IME = 1 (el original tambien lo hace: permite anidar interrupciones)
 *   salta a *(0x03007FA0) dejando lr intacto, para que el manejador de
 *   FilmPlay retorne al despachador de la BIOS con su `pop {r3,pc}`.
 * Se pueden pisar r0-r3 e ip: la BIOS ya los ha salvado.
 */
/* Equivalente del enganche original, sin los combos de teclas:
 *   REG_IME = 1 (el original tambien lo hace: permite anidar interrupciones)
 *   salta a *(0x03007FA0) dejando lr intacto, para que el manejador de
 *   FilmPlay retorne al despachador de la BIOS con su `pop {r3,pc}`.
 * Se pueden pisar r0-r3 e ip: la BIOS ya los ha salvado.
 *
 * R14 (intento descartado): se probo a hacerlo no reentrante, con bandera y
 * llamando al manejador en vez de saltar a el, para cortar la recursion que
 * mata la consola al abrir un .gbm. No arregla el fallo, asi que no se deja
 * puesto: no tiene sentido tocar el camino de interrupcion que YA funciona en
 * hardware para el audio a cambio de nada. Ver informe §29.
 */
__attribute__((naked)) void EWRAM_CODE ezfo_irq_stub(void) {
  __asm__ volatile(
      "mov  r0, #0x04000000\n"
      "add  r0, r0, #0x200\n"
      "mov  r1, #1\n"
      "strh r1, [r0, #8]\n"      /* REG_IME = 1 */
      "mov  r0, #0x03000000\n"
      "orr  r0, r0, #0x7F00\n"
      "orr  r0, r0, #0xA0\n"
      "ldr  r0, [r0]\n"          /* manejador real de FilmPlay */
      "cmp  r0, #0\n"
      "bxeq lr\n"                /* aun no instalado: no hay nada que hacer */
      "bx   r0\n");
}

/* Se llama antes de cada lectura, no una sola vez: da igual quien escriba el
 * vector ni cuando, aqui siempre queda apuntando a RAM justo antes de que la
 * ROM desaparezca. */
static void EWRAM_CODE ezfo_hook_irq(void) {
  if (*(vu32*)0x03007FFC >= 0x08000000)
    *(vu32*)0x03007FFC = (u32)ezfo_irq_stub;
}



#else
#define ezfo_hook_irq() ((void)0)
#endif

/* --- R12: lectura anticipada, para el pinchazo del final de la cancion ---
 *
 * FilmPlay pide los sectores DE UNO EN UNO. En regimen normal eso se nota
 * poco: 16 lecturas cada 22 frames. Pero al cerrar el bucle de una cancion
 * hace una rafaga de 49 lecturas en un solo frame (medido en el emulador:
 * 15 para acabar el fichero, 1 de FAT para rebobinar, 33 para volver a
 * llenar el buffer), y en la Omega cada peticion cuesta un cambio de pagina
 * de ROM, un SD_Enable/SD_Disable y un comando SD entero para 512 bytes.
 * La rafaga bloquea la CPU casi un segundo y el sonido se queda sin datos.
 *
 * Los sectores de la rafaga son contiguos, asi que basta con leer por
 * delante: en cada fallo se piden EZFO_CACHE_SECTORS sectores seguidos y los
 * siguientes se sirven copiando de RAM. El driver agrupa de 4 en 4 por
 * comando SD, asi que con 8 se pasa de 33 peticiones y 33 comandos a 5 y 10.
 *
 * La cache vive dentro del propio blob, en el hueco libre de EWRAM
 * 0x02029B00-0x0202FFFF (informe §31): 1484 B de codigo + 4 KB de cache.
 *
 * Es segura porque este shim solo lee: la tarjeta no cambia por debajo.
 */
#ifndef EZFO_CACHE_SECTORS
#define EZFO_CACHE_SECTORS 8
#endif

#if EZFO_CACHE_SECTORS > 0

static u8 EWRAM_BSS __attribute__((aligned(4)))
cache[EZFO_CACHE_SECTORS * 512];
static u32 EWRAM_BSS cache_base; /* primer sector que contiene */
static u32 EWRAM_BSS cache_n;    /* 0 = vacia */

static void EWRAM_CODE copia_sector(u32* dst, const u32* src) {
  for (int i = 0; i < 128; i++)
    dst[i] = src[i];
}

static bool EWRAM_CODE ezfo_lee(u32 sector, void* dest) {
  if (cache_n && sector - cache_base < cache_n) {
    copia_sector((u32*)dest, (const u32*)(cache + (sector - cache_base) * 512));
    return true;
  }

  cache_n = 0; /* si la lectura falla, la cache queda invalidada */
  if (!_EZFO_readSectors(sector, EZFO_CACHE_SECTORS, cache)) {
    /* Puede ser el final de la tarjeta: se reintenta sin anticipacion. */
    return _EZFO_readSectors(sector, 1, dest);
  }
  cache_base = sector;
  cache_n = EZFO_CACHE_SECTORS;
  copia_sector((u32*)dest, (const u32*)cache);
  return true;
}

#else
#define ezfo_lee(sector, dest) _EZFO_readSectors((sector), 1, (dest))
#endif

/* Punto de entrada al que saltan los cuerpos parcheados. */
void EWRAM_CODE ezfo_read_shim(void* dest, u32 sector) {
  const u16 waitcnt = REG_WAITCNT;
  REG_WAITCNT = WAITCNT_LECTURA;
  ezfo_hook_irq();

#if EZFO_TRACE
  trace_n++;
  if (trace_n == 1)
    mark(AMARILLO, 45); /* FilmPlay ha pedido su primer sector */
#endif

  if (ezfo_state == 0) {
    ezfo_install();
#if EZFO_TRACE
    mark(ezfo_state == 1 ? VERDE : MAGENTA, 45);
#endif
  }

  if (ezfo_state == 1) {
    ezfo_lee(sector, dest);
  } else {
    /* Sin tarjeta: se entrega un sector a cero en vez de dejar el buffer como
     * estaba. Asi FilmPlay ve un MBR invalido y muestra su mensaje de error,
     * en lugar de recorrer una FAT de basura y colgarse. */
    u32* p = (u32*)dest;
    for (int i = 0; i < 128; i++)
      p[i] = 0;
  }

#if EZFO_TRACE
  if (trace_n == 1)
    mark(CIAN, 45); /* primera lectura completada */
  if (trace_n == 5)
    mark(BLANCO, 30); /* FilmPlay va por el quinto sector: esta montando */
  /* Latido: un frame verde cada N lecturas. Si FilmPlay sigue pidiendo
   * sectores se ve parpadeo; si se queda quieto, la pantalla se congela. */
#define LATIDO 15
  if (trace_n > 5 && (trace_n & LATIDO) == 0)
    mark(VERDE, 1);
#endif

  REG_WAITCNT = waitcnt;
}
