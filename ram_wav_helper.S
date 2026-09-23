.syntax unified
.thumb
.text
.global lab_wav_helper
.thumb_func
lab_wav_helper:
    push {r3-r7, lr}
    ldr r4, context_address
    movs r6, #1
    str r6, [r4, #20]
    ldr r0, [r4]
    movw r1, #0x20a
    ldr r7, open_address
    blx r7
    str r0, [r4, #16]
    cmp r0, #0
    blt finish
    mov r5, r0
    movs r6, #0
write_chunk:
    ldr r1, [r4, #4]
    adds r1, r1, r6
    ldr r2, [r4, #8]
    subs r2, r2, r6
    movw r3, #2048
    cmp r2, r3
    it hi
    movhi r2, r3
    mov r0, r5
    ldr r7, write_address
    blx r7
    cmp r0, #0
    ble close_file
    adds r6, r6, r0
    ldr r2, [r4, #8]
    cmp r6, r2
    blo write_chunk
close_file:
    str r6, [r4, #12]
    mov r0, r5
    ldr r7, close_address
    blx r7
    str r0, [r4, #24]
finish:
    movs r6, #3
    str r6, [r4, #20]
    pop {r3-r7, pc}
.balign 4
context_address: .word 0x2802f594
open_address: .word 0x0212c8e9
write_address: .word 0x0212cc41
close_address: .word 0x0212ca11
