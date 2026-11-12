#ifndef HOST_SERIAL_H
#define HOST_SERIAL_H
#include <stdint.h>

typedef struct {
    uint32_t receivedFrames, rejectedFrames, commands, rxOverflows, uartErrors;
    uint32_t sentStates, duplicateCommands, txOverflows;
} HostSerialDebug_t;
extern volatile HostSerialDebug_t g_hostSerialDebug;

void HostSerial_Initialize(uint32_t nowMs);
void HostSerial_Task(uint32_t nowMs);
/* Called by the low-priority interrupt manager; bounded byte copying only. */
void HostSerial_RxISR(void);
#endif
