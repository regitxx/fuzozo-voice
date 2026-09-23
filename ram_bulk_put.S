.syntax unified
.thumb
.text
.global lab_bulk_put
.thumb_func
lab_bulk_put:
    push {r4-r7, lr}
    sub sp, #4
    cmp r2, #2
    bne done
    ldr r4, context_address
    ldr r5, [r3, #4]
    ldr r6, [r4, #8]
    ldr r7, [r4, #4]
next_byte:
    ldrb r0, [r5]
    cbz r0, acknowledge
    cmp r6, r7
    bhs done
    ldrb r1, [r5, #1]
    cbz r1, done
    subs r0, #48
    cmp r0, #9
    it hi
    subhi r0, #39
    cmp r0, #15
    bhi done
    subs r1, #48
    cmp r1, #9
    it hi
    subhi r1, #39
    cmp r1, #15
    bhi done
    orr.w r0, r1, r0, lsl #4
    ldr r2, [r4]
    strb r0, [r2, r6]
    adds r6, #1
    adds r5, #2
    b next_byte
acknowledge:
    str r6, [r4, #8]
    mov r1, r6
    ldr r0, format_address
    ldr r3, print_address
    blx r3
done:
    add sp, #4
    pop {r4-r7, pc}
.balign 4
context_address: .word 0x2802f5b4
format_address: .word 0x2802f5ec
print_address: .word 0x020b9bf5
