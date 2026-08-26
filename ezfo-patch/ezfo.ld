/* El blob EZFO se enlaza para ejecutarse en EWRAM 0x0202C000 y se copia ahi
 * al arrancar. Debe estar en RAM: la EZ Flash Omega deja la ROM inaccesible
 * mientras lee de la SD.
 *
 * Estuvo en IWRAM 0x03004000 hasta que se descubrio (informe §31) que al
 * entrar en modo video FilmPlay vuelca un solapamiento de 31 KB sobre
 * 0x03000000-0x03007BFF y se lleva por delante el blob entero. En modo video
 * no queda un solo byte libre de IWRAM.
 *
 * 0x0202C000 esta en el unico hueco de EWRAM que FilmPlay no toca nunca
 * MIENTRAS REPRODUCE VIDEO: 0x0202BC00-0x0202FFFF, 17,4 KB, medido con una
 * vigilancia de rango sobre toda la EWRAM.
 *
 * Ojo con ese "mientras reproduce video". Antes de abrir el .gbm el hueco
 * empieza mucho antes, en 0x02029B00; en cuanto el video corre, FilmPlay baja
 * sus buffers hasta 0x0202BBFF y pide sectores directamente sobre 0x0202A000.
 * Medir el hueco sin llegar a reproducir da 25,8 KB y es mentira.
 *
 * 17,4 KB es tambien el techo de EZFO_CACHE_SECTORS: con 32 sectores el blob
 * son 18 056 B y no cabe. 16 es el maximo (informe §33.1).
 */
ENTRY(ezfo_install)

MEMORY {
  RAM (rwx) : ORIGIN = 0x0202C000, LENGTH = 16K
}

SECTIONS {
  .blob : {
    __blob_start = .;
    *(.ewram)           /* codigo marcado EWRAM_CODE en gba-flashcartio */
    *(.ewram.*)
    *(.text .text.*)
    *(.rodata .rodata.*)
    . = ALIGN(4);
    *(.data .data.*)
    . = ALIGN(4);
    __bss_start = .;
    *(.sbss .sbss.*)    /* EWRAM_BSS */
    *(.bss .bss.*)
    *(COMMON)
    . = ALIGN(4);
    __bss_end = .;
    __blob_end = .;
  } > RAM

  /DISCARD/ : { *(.comment) *(.ARM.attributes) *(.note.*) }
}
