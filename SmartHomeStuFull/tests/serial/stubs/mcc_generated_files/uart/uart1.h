#ifndef SERIAL_TEST_UART1_H
#define SERIAL_TEST_UART1_H
#include <stdbool.h>
#include <stdint.h>
typedef struct { uint8_t RXFOIF, FERIF, PERIF; } SerialTestErrorBits;
typedef struct { uint8_t U1RXIP; } SerialTestPriorityBits;
typedef struct { uint8_t U1RXIE; } SerialTestEnableBits;
extern volatile SerialTestErrorBits U1ERRIRbits;
extern volatile SerialTestPriorityBits IPR4bits;
extern volatile SerialTestEnableBits PIE4bits;
bool UART1_IsTxReady(void);
bool UART1_IsRxReady(void);
void UART1_Write(uint8_t byte);
uint8_t UART1_Read(void);
#endif
