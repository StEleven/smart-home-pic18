/* Forced before the production driver; bypass only MCC hardware headers. */
#ifndef SERVO_TEST_HARDWARE_H
#define SERVO_TEST_HARDWARE_H
#include <stdint.h>
#include <stdbool.h>
#define PINS_H
#define TMR3_H

typedef struct { uint8_t TMR3IE; } ServoTestInterruptBits;
extern volatile ServoTestInterruptBits PIE5bits;
void Test_PinHigh(uint8_t index);
void Test_PinLow(uint8_t index);
void Test_SnapshotHook(void);

#define SERVO1_SetHigh() Test_PinHigh(0U)
#define SERVO2_SetHigh() Test_PinHigh(1U)
#define SERVO3_SetHigh() Test_PinHigh(2U)
#define SERVO1_SetLow() Test_PinLow(0U)
#define SERVO2_SetLow() Test_PinLow(1U)
#define SERVO3_SetLow() Test_PinLow(2U)
#define SERVO1_SetDigitalMode() ((void)0)
#define SERVO2_SetDigitalMode() ((void)0)
#define SERVO3_SetDigitalMode() ((void)0)
#define SERVO1_SetPushPull() ((void)0)
#define SERVO2_SetPushPull() ((void)0)
#define SERVO3_SetPushPull() ((void)0)
#define SERVO1_SetDigitalOutput() ((void)0)
#define SERVO2_SetDigitalOutput() ((void)0)
#define SERVO3_SetDigitalOutput() ((void)0)

/* extension_config.h is bypassed only to route the fourth GPIO into trace. */
#define EXTENSION_CONFIG_H
#define HOME_CURTAIN_PIN_INIT() ((void)0)
#define HOME_CURTAIN_PIN_HIGH() Test_PinHigh(3U)
#define HOME_CURTAIN_PIN_LOW() Test_PinLow(3U)
#define SERVO_DRIVER_TEST_SNAPSHOT_HOOK() Test_SnapshotHook()

void TMR3_PeriodSet(uint16_t value);
void TMR3_CounterSet(uint16_t value);
void TMR3_OverflowCallbackRegister(void (*callback)(void));
void TMR3_OverflowInterruptEnable(void);
void TMR3_OverflowInterruptDisable(void);
void TMR3_Start(void);
#endif
