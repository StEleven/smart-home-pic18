/** @file sht30.h
 * Non-blocking SHT30 single-shot measurements on the shared I2C bus.
 * Context and its buffers must outlive every active transaction. Initialize
 * only at boot / when inactive; a timeout never aborts an MCC transaction.
 */
#ifndef SHT30_H
#define SHT30_H

#include <stdbool.h>
#include <stdint.h>

typedef enum
{
    SHT30_OK = 0,
    SHT30_BUSY,
    SHT30_ERROR_PARAMETER,
    SHT30_ERROR_I2C,
    SHT30_ERROR_TIMEOUT,
    SHT30_ERROR_CRC,
    SHT30_ERROR_RANGE
} SHT30_Status_t;

typedef enum
{
    SHT30_STATE_IDLE = 0,
    SHT30_STATE_WAIT_COMMAND,
    SHT30_STATE_WAIT_CONVERSION,
    SHT30_STATE_WAIT_READ
} SHT30_State_t;

typedef struct
{
    SHT30_State_t state;
    uint8_t address;
    uint8_t command[2];
    uint8_t rxData[6];
    uint32_t stageStartMs;
    uint32_t timeoutMs;
    bool timeoutReported;
} SHT30_Context_t;

void SHT30_Initialize(SHT30_Context_t *context);

/** Start command 0x2400 (high repeatability, no clock stretching).
 * BUSY means retry later; only OK starts a measurement. Valid addresses are
 * the SHT3x 7-bit addresses 0x44 and 0x45. timeoutMs is a stage diagnostic.
 */
SHT30_Status_t SHT30_Start(SHT30_Context_t *context, uint8_t address,
                         uint32_t nowMs, uint32_t timeoutMs);

/** Advance one short step. complete is true only for a fresh valid sample;
 * humidity10 is then 0..1000 (0.1 %RH). On a hardware-stuck timeout the
 * context remains active and MUST continue to be polled until MCC completes.
 * A late result after a timeout is discarded, without releasing a live owner.
 */
SHT30_Status_t SHT30_Task(SHT30_Context_t *context, uint32_t nowMs,
                        bool *complete, uint16_t *humidity10);
bool SHT30_IsActive(const SHT30_Context_t *context);

#endif
