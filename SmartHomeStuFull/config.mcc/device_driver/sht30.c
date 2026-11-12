/** @file sht30.c
 * Sensirion SHT3x-DIS datasheet v7 (Dec 2022), sections 2.2, 4.3, 4.4,
 * 4.12, 4.13: https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf
 * High-repeatability conversion is at most 15.5 ms over the supply range.
 */
#include <stddef.h>
#include "sht30.h"
#include "i2c_bus.h"

#define SHT30_CONVERSION_MS 16UL

static uint8_t SHT30_CRC(const uint8_t *data)
{
    uint8_t crc = 0xFFU;
    uint8_t byteIndex;
    uint8_t bitIndex;
    for (byteIndex = 0U; byteIndex < 2U; byteIndex++)
    {
        crc ^= data[byteIndex];
        for (bitIndex = 0U; bitIndex < 8U; bitIndex++)
        {
            crc = ((crc & 0x80U) != 0U)
                ? (uint8_t)((uint8_t)(crc << 1) ^ 0x31U)
                : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

static SHT30_Status_t SHT30_Finish(SHT30_Context_t *context,
                                  SHT30_Status_t status)
{
    context->state = SHT30_STATE_IDLE;
    return status;
}

void SHT30_Initialize(SHT30_Context_t *context)
{
    uint8_t index;
    if (context == NULL) { return; }
    context->state = SHT30_STATE_IDLE;
    context->address = 0x44U;
    context->command[0] = 0x24U;
    context->command[1] = 0x00U;
    for (index = 0U; index < 6U; index++) { context->rxData[index] = 0U; }
    context->stageStartMs = 0UL;
    context->timeoutMs = 0UL;
    context->timeoutReported = false;
}

SHT30_Status_t SHT30_Start(SHT30_Context_t *context, uint8_t address,
                         uint32_t nowMs, uint32_t timeoutMs)
{
    I2C_BusStatus_t status;
    if ((context == NULL) || ((address != 0x44U) && (address != 0x45U)) ||
        (timeoutMs == 0UL) || (timeoutMs > 0x7FFFFFFFUL))
    {
        return SHT30_ERROR_PARAMETER;
    }
    if (context->state != SHT30_STATE_IDLE) { return SHT30_BUSY; }
    context->address = address;
    context->command[0] = 0x24U;
    context->command[1] = 0x00U;
    status = I2C_Bus_WriteStart(I2C_BUS_OWNER_SHT30, address,
                              context->command, 2U);
    if (status == I2C_BUS_BUSY) { return SHT30_BUSY; }
    if (status != I2C_BUS_OK) { return SHT30_ERROR_I2C; }
    context->stageStartMs = nowMs;
    context->timeoutMs = timeoutMs;
    context->timeoutReported = false;
    context->state = SHT30_STATE_WAIT_COMMAND;
    return SHT30_OK;
}

SHT30_Status_t SHT30_Task(SHT30_Context_t *context, uint32_t nowMs,
                        bool *complete, uint16_t *humidity10)
{
    I2C_BusStatus_t status;
    uint16_t rawTemperature;
    uint16_t rawHumidity;
    int32_t temperature100;
    if ((context == NULL) || (complete == NULL) || (humidity10 == NULL))
    {
        return SHT30_ERROR_PARAMETER;
    }
    *complete = false;
    if (context->state == SHT30_STATE_IDLE) { return SHT30_ERROR_PARAMETER; }

    if (context->state == SHT30_STATE_WAIT_CONVERSION)
    {
        /* The command transaction was already polled to completion. No owner
         * is held during sensor conversion or while waiting for a free bus. */
        if ((uint32_t)(nowMs - context->stageStartMs) < SHT30_CONVERSION_MS)
        {
            return SHT30_BUSY;
        }
        if ((uint32_t)(nowMs - context->stageStartMs) >=
            (SHT30_CONVERSION_MS + context->timeoutMs))
        {
            return SHT30_Finish(context, SHT30_ERROR_TIMEOUT);
        }
        status = I2C_Bus_ReadStart(I2C_BUS_OWNER_SHT30, context->address,
                                  context->rxData, 6U);
        if (status == I2C_BUS_BUSY) { return SHT30_BUSY; }
        if (status != I2C_BUS_OK)
        {
            return SHT30_Finish(context, SHT30_ERROR_I2C);
        }
        context->stageStartMs = nowMs;
        context->state = SHT30_STATE_WAIT_READ;
        return SHT30_BUSY;
    }

    if ((context->state != SHT30_STATE_WAIT_COMMAND) &&
        (context->state != SHT30_STATE_WAIT_READ))
    {
        /* Do not guess at ownership or release a transaction on bad state. */
        return SHT30_ERROR_PARAMETER;
    }
    status = I2C_Bus_Poll(I2C_BUS_OWNER_SHT30);
    if (status == I2C_BUS_BUSY)
    {
        if ((!context->timeoutReported) &&
            ((uint32_t)(nowMs - context->stageStartMs) >= context->timeoutMs))
        {
            context->timeoutReported = true;
            return SHT30_ERROR_TIMEOUT;
        }
        return SHT30_BUSY;
    }
    /* Poll releases the owner only after hardware completion. Late results
     * following a diagnostic timeout are drained but never accepted as new. */
    if (context->timeoutReported ||
        ((uint32_t)(nowMs - context->stageStartMs) >= context->timeoutMs))
    {
        return SHT30_Finish(context, SHT30_ERROR_TIMEOUT);
    }
    if (status != I2C_BUS_OK)
    {
        return SHT30_Finish(context, SHT30_ERROR_I2C);
    }
    if (context->state == SHT30_STATE_WAIT_COMMAND)
    {
        context->stageStartMs = nowMs;
        context->state = SHT30_STATE_WAIT_CONVERSION;
        return SHT30_BUSY;
    }

    if ((SHT30_CRC(&context->rxData[0]) != context->rxData[2]) ||
        (SHT30_CRC(&context->rxData[3]) != context->rxData[5]))
    {
        return SHT30_Finish(context, SHT30_ERROR_CRC);
    }
    rawTemperature = ((uint16_t)context->rxData[0] << 8) | context->rxData[1];
    rawHumidity = ((uint16_t)context->rxData[3] << 8) | context->rxData[4];
    temperature100 = -4500L +
        (int32_t)(((uint32_t)rawTemperature * 17500UL + 32767UL) / 65535UL);
    if ((temperature100 < -4000L) || (temperature100 > 12500L))
    {
        return SHT30_Finish(context, SHT30_ERROR_RANGE);
    }
    *humidity10 = (uint16_t)(((uint32_t)rawHumidity * 1000UL + 32767UL) / 65535UL);
    if (*humidity10 > 1000U)
    {
        return SHT30_Finish(context, SHT30_ERROR_RANGE);
    }
    *complete = true;
    return SHT30_Finish(context, SHT30_OK);
}

bool SHT30_IsActive(const SHT30_Context_t *context)
{
    return ((context != NULL) && (context->state != SHT30_STATE_IDLE));
}
