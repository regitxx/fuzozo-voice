.syntax unified
.thumb
.text
.global lab_volume
.thumb_func
lab_volume:
    push {r4-r6, lr}
    ldr r4, context_address
    ldr r5, config_address
    ldr r0, [r4]
    cmp r0, #100
    bhi mute
    ldrb r1, [r5, #1]
    cmp r0, r1
    beq mute
    ldr r6, volume_address
    blx r6
mute:
    ldr r0, [r4, #4]
    cmp r0, #1
    bhi result
    ldrb r1, [r5, #5]
    cmp r0, r1
    beq result
    movs r1, #1
    ldr r6, mute_address
    blx r6
result:
    ldrb r0, [r5, #1]
    str r0, [r4, #8]
    ldrb r0, [r5, #5]
    str r0, [r4, #12]
    movs r0, #1
    str r0, [r4, #16]
    pop {r4-r6, pc}
.balign 4
context_address: .word 0x2802f594
config_address: .word 0x280180d0
volume_address: .word 0x0218a345
mute_address: .word 0x0218a369
