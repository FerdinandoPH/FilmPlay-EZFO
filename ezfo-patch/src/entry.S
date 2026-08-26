@ Punto de entrada al que saltan los cuerpos parcheados de FilmPlay.
@
@ El cuerpo original hacia `stmdb sp!, {r3-r7}` ... `ldmia sp!, {r3-r7}`, es
@ decir preservaba r3-r7 y destruia r0-r2 y r12. La convencion AAPCS que usa
@ el shim en C preserva r4-r11 pero NO r3, asi que hay que salvarlo aparte
@ para no cambiar el contrato que ve el llamante.
@
@ Se llega aqui por salto absoluto (no por BL), asi que lr apunta ya al
@ llamante real de FilmPlay.
@
@ El cuerpo original tambien sale siempre con r0 = 0 (residuo de su bucle de
@ espera `subs r0,r0,#1`). Se reproduce, para no cambiar nada que el llamante
@ pudiera estar mirando.
@
@   r0 = puntero destino, r1 = sector

    .section .ewram, "ax", %progbits
    .arm
    .global ezfo_read_entry
    .type   ezfo_read_entry, %function
ezfo_read_entry:
    stmdb   sp!, {r3, lr}
    bl      ezfo_read_shim
    ldmia   sp!, {r3, lr}
    mov     r0, #0          @ el cuerpo original sale siempre con r0 = 0
    bx      lr
    .size   ezfo_read_entry, . - ezfo_read_entry


@ ============================================================================
@ R13: parar al llegar al tamano del fichero, no al final de la cadena
@
@ FilmPlay lee "el siguiente sector" de un fichero con una rutina que solo
@ declara el fin cuando se acaba la CADENA DE CLUSTERS. Con clusters de 32 KB
@ eso son hasta 32 KB de basura tras el ultimo byte util: 1,3 s de ruido al
@ final de un .gbs (informe §28).
@
@ Se engancha en el retorno "todo bien" de esa rutina, que es comun a los tres
@ caminos (FAT12, FAT16, FAT32) y consiste en:
@
@     mov r0, #1
@     b   <epilogo>            @ epilogo = ldmia sp!, {r3-r9, pc}
@
@ Las dos palabras se sustituyen por `ldr pc, [pc,#-4]` + direccion de este
@ gancho, asi que la llamada es independiente de donde se haya cargado la
@ copia (FilmPlay tiene varias, y la misma copia corre unas veces desde EWRAM
@ y otras desde IWRAM). Como no se toca la pila, el gancho puede rematar con
@ el mismo epilogo.
@
@ Contrato al entrar:
@   r4 = descriptor de fichero, con
@        +0x0C primer cluster   +0x10 tamano en bytes   +0x20 cluster actual
@        +0x28 primer sector del cluster actual   +0x2C sector dentro del cluster
@   r0 esta muerto (iba a valer 1); r3-r9 los restaura el epilogo, asi que se
@   pueden destruir; r10, r11 y sp son del llamante y no se tocan.
@
@ La cuenta de sectores que quedan se lleva aparte, en una tabla propia de
@ cuatro fichas indexada por el puntero al descriptor, para no escribir en
@ ninguna variable de FilmPlay.
@
@ Dos casos que NO se tocan:
@   - tamano 0: son los directorios, que se leen con esta misma rutina y donde
@     el unico fin valido es el de la cadena.
@   - descriptor desconocido: se devuelve 1, o sea el comportamiento original.
@ ============================================================================

    .section .ewram, "ax", %progbits
    .arm
    .global ezfo_eof_hook
    .type   ezfo_eof_hook, %function
ezfo_eof_hook:
    ldr     r0, [r4, #0x28]         @ primer sector del cluster actual
    ldr     r1, [r4, #0x2C]         @ sector dentro del cluster
    add     r0, r0, r1              @ r0 = posicion, cambia con cada sector servido
    ldr     r2, =ezfo_eof_tabla

    mov     r5, #0                  @ ficha de este descriptor
    mov     r6, #0                  @ ficha libre
    mov     r7, r2
    mov     r3, #4
1:  ldr     r12, [r7]
    cmp     r12, r4
    moveq   r5, r7
    cmp     r12, #0
    moveq   r6, r7
    add     r7, r7, #12
    subs    r3, r3, #1
    bne     1b

    @ ¿recien abierto o rebobinado?  cluster actual == primer cluster y
    @ contador == 1 solo se dan juntos justo despues de abrir.
    ldr     r3, [r4, #0x20]
    ldr     r12, [r4, #0x0C]
    cmp     r3, r12
    cmpeq   r1, #1
    bne     3f

    ldr     r3, [r4, #0x10]         @ tamano en bytes
    cmp     r3, #0
    bne     2f
    cmp     r5, #0                  @ directorio: soltar la ficha si la tenia
    strne   r3, [r5]
    mov     r0, #1
    b       4f

2:  cmp     r5, #0                  @ elegir ficha: la suya, una libre, o la 1a
    movne   r7, r5
    bne     20f
    cmp     r6, #0
    movne   r7, r6
    moveq   r7, r2
20: str     r4, [r7]
    str     r0, [r7, #4]
    sub     r3, r3, #1              @ tamano >= 1 aqui
    mov     r3, r3, lsr #9          @ (tam-1)/512 = sectores que quedan tras
    str     r3, [r7, #8]            @ el primero, que se acaba de servir
    mov     r0, #1
    b       4f

3:  cmp     r5, #0
    moveq   r0, #1                  @ descriptor sin ficha: como siempre
    beq     4f
    ldr     r12, [r5, #4]
    cmp     r12, r0
    moveq   r0, #1                  @ la posicion no cambio: no hubo sector nuevo
    beq     4f
    str     r0, [r5, #4]
    ldr     r3, [r5, #8]
    cmp     r3, #0
    moveq   r0, #0                  @ se acabo el fichero
    beq     4f
    sub     r3, r3, #1
    str     r3, [r5, #8]
    mov     r0, #1

4:  ldmia   sp!, {r3, r4, r5, r6, r7, r8, r9, pc}
    .ltorg
    .size   ezfo_eof_hook, . - ezfo_eof_hook

    .section .bss
    .align  2
    .global ezfo_eof_tabla
ezfo_eof_tabla:
    .space  4 * 12
    .size   ezfo_eof_tabla, . - ezfo_eof_tabla
