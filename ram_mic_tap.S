.syntax unified
.thumb
.text
.global lab_mic_tap
.thumb_func
lab_mic_tap:
    push {r0-r7, lr}
    ldr r4, context_address
    movs r3, #1
    str r3, [r4, #24]
    ldr r3, [r4, #16]
    cbz r3, finish
    ldr r5, [r0, #4]
    cbz r5, finish
    ldr r3, [r4, #28]
    adds r5, r5, r3
    ldrh r6, [r0, #8]
    lsrs r6, r6, #2
    ldr r7, [r4, #8]
    ldr r2, [r4, #4]
    cmp r7, r2
    bhs finish
    subs r2, r2, r7
    lsrs r2, r2, #1
    cmp r6, r2
    it hi
    movhi r6, r2
    ldr r1, [r4]
    adds r1, r1, r7
copy_sample:
    cbz r6, copied
    ldrh r2, [r5]
    strh r2, [r1]
    adds r5, #4
    adds r1, #2
    adds r7, #2
    subs r6, #1
    b copy_sample
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
context_address: .word 0x2802f5b4
original_callback: .word 0x021895e5
