.syntax unified
.thumb
.text
.global lab_mic_ring
.thumb_func
lab_mic_ring:
    push {r0-r7, lr}
    ldr r4, context_address
    movs r3, #1
    str r3, [r4, #24]
    ldr r3, [r4, #16]
    cbz r3, finish
    ldr r5, [r0, #4]
    cbz r5, finish
    ldrh r6, [r0, #8]
    lsrs r6, r6, #3
    ldr r7, [r4, #8]
    ldr r1, [r4]
sample:
    cbz r6, copied
    ldrsh r2, [r5]
    ldrsh r3, [r5, #4]
    adds r2, r2, r3
    asrs r2, r2, #3
    movs r0, #255
    cmp r2, #0
    bge positive
    rsbs r2, r2, #0
    movs r0, #127
positive:
    movw r3, #8158
    cmp r2, r3
    it hi
    movhi r2, r3
    adds r2, #33
    clz r3, r2
    rsb r3, r3, #26
    add r12, r3, #1
    lsr.w r2, r2, r12
    and r2, r2, #15
    orr.w r2, r2, r3, lsl #4
    eors r2, r0
    uxth r0, r7
    strb r2, [r1, r0]
    adds r7, #1
    adds r5, #8
    subs r6, #1
    b sample
copied:
    str r7, [r4, #8]
finish:
    ldr r3, [r4, #20]
    adds r3, #1
    str r3, [r4, #20]
    movs r3, #0
    str r3, [r4, #24]
    pop.w {r0-r7, lr}
    ldr.w r12, original_callback
    bx r12
.balign 4
context_address: .word 0x2802f514
original_callback: .word 0x021895e5
