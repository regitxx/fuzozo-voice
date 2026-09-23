.syntax unified
.thumb
.text
.global lab_bulk_get
.thumb_func
lab_bulk_get:
    push {r4-r7, lr}
    sub sp, #172
    ldr r4, context_address
    ldr r5, [r4]
    ldr r6, [r4, #8]
    ldr r7, [r4, #4]
    cmp r6, r7
    bhs done
    subs r7, r7, r6
    cmp r7, #80
    it hi
    movhi r7, #80
    adds r5, r5, r6
    adds r6, r6, r7
    str r6, [r4, #8]
    mov r0, sp
    ldr r3, alphabet_address
next_byte:
    cbz r7, acknowledge
    ldrb r1, [r5]
    lsrs r2, r1, #4
    and r1, r1, #15
    ldrb r2, [r3, r2]
    strb r2, [r0]
    ldrb r1, [r3, r1]
    strb r1, [r0, #1]
    adds r5, #1
    adds r0, #2
    subs r7, #1
    b next_byte
acknowledge:
    movs r1, #0
    strb r1, [r0]
    mov r1, sp
    ldr r0, format_address
    ldr r3, print_address
    blx r3
done:
    add sp, #172
    pop {r4-r7, pc}
.balign 4
context_address: .word 0x2802f5b4
format_address: .word 0x2802f5ec
print_address: .word 0x020b9bf5
alphabet_address: .word 0x2802f5fc
