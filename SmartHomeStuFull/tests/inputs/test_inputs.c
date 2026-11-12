/* Deterministic host tests of production SHT30, HomeInputs, i2c_bus and
 * VCNL4200 code. Only the MCC hardware boundary and GPIO SFRs are faked.
 * Return value is the failed source line (zero means all checks passed).
 */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "sht30.h"
#include "home_inputs.h"
#include "vcnl4200.h"
#include "i2c_bus.h"
#include "mcc_generated_files/i2c_host/i2c1.h"

#define CHECK(condition) do { if (!(condition)) { return __LINE__; } } while (0)

volatile uint8_t ANSELA, TRISA, WPUA, PORTA;
int _fltused = 0; /* MSVC ABI marker for unused legacy VCNL float APIs. */

static bool fakeBusy;
static bool fakeAllowStart;
static bool fakeHold;
static bool fakeShtPresent;
static bool fakeVcnlPresent;
static uint16_t fakeAddress;
static uint8_t *fakeWrite;
static size_t fakeWriteLength;
static uint8_t *fakeRead;
static size_t fakeReadLength;
static uint32_t fakeNow;
static uint32_t fakeStarted;
static uint16_t fakeAlsConfig;
static uint16_t fakeAlsRaw;
static uint8_t fakeShtFrame[6];
static i2c_host_error_t fakeError;
static uint32_t fakeStartCount;

static void Fake_Reset(void)
{
    fakeBusy = false;
    fakeAllowStart = true;
    fakeHold = false;
    fakeShtPresent = true;
    fakeVcnlPresent = true;
    fakeNow = 0UL;
    fakeStarted = 0UL;
    fakeAlsConfig = 0x0140U; /* Existing boot setup: ALS enabled, 100 ms. */
    fakeAlsRaw = 10000U;
    fakeError = I2C_ERROR_NONE;
    fakeStartCount = 0UL;
    fakeShtFrame[0] = 0x66U;
    fakeShtFrame[1] = 0x66U;
    fakeShtFrame[2] = 0x93U;
    fakeShtFrame[3] = 0x80U;
    fakeShtFrame[4] = 0x00U;
    fakeShtFrame[5] = 0xA2U;
    ANSELA = 0xFFU;
    TRISA = 0U;
    WPUA = 0U;
    PORTA = 0xFFU;
    I2C_Bus_Initialize();
}

static bool Fake_Start(uint16_t address, uint8_t *writeData, size_t writeLength,
                       uint8_t *readData, size_t readLength)
{
    if (!fakeAllowStart || fakeBusy) { return false; }
    fakeBusy = true;
    fakeAddress = address;
    fakeWrite = writeData;
    fakeWriteLength = writeLength;
    fakeRead = readData;
    fakeReadLength = readLength;
    fakeStarted = fakeNow;
    fakeError = I2C_ERROR_NONE;
    fakeStartCount++;
    return true;
}

bool I2C1_Write(uint16_t address, uint8_t *data, size_t length)
{
    return Fake_Start(address, data, length, NULL, 0U);
}
bool I2C1_Read(uint16_t address, uint8_t *data, size_t length)
{
    return Fake_Start(address, NULL, 0U, data, length);
}
bool I2C1_WriteRead(uint16_t address, uint8_t *writeData, size_t writeLength,
                   uint8_t *readData, size_t readLength)
{
    return Fake_Start(address, writeData, writeLength, readData, readLength);
}
bool I2C1_IsBusy(void) { return fakeBusy; }
i2c_host_error_t I2C1_ErrorGet(void)
{
    i2c_host_error_t error = fakeError;
    fakeError = I2C_ERROR_NONE;
    return error;
}
void I2C1_CallbackRegister(void (*callback)(void)) { (void)callback; }

static void Fake_Complete(void)
{
    uint8_t index;
    uint16_t value;
    if (!fakeBusy) { return; }
    if (((fakeAddress == 0x44U) || (fakeAddress == 0x45U)) && !fakeShtPresent)
    {
        fakeError = I2C_ERROR_ADDR_NACK;
    }
    else if ((fakeAddress == VCNL4200_I2C_ADDRESS) && !fakeVcnlPresent)
    {
        fakeError = I2C_ERROR_ADDR_NACK;
    }
    else if (fakeRead != NULL)
    {
        if ((fakeAddress == 0x44U) || (fakeAddress == 0x45U))
        {
            for (index = 0U; index < fakeReadLength; index++)
            {
                fakeRead[index] = fakeShtFrame[index];
            }
        }
        else
        {
            value = ((fakeWriteLength == 1U) &&
                     (fakeWrite[0] == VCNL4200_REG_ALS_CONF))
                ? fakeAlsConfig : fakeAlsRaw;
            fakeRead[0] = (uint8_t)(value & 0xFFU);
            fakeRead[1] = (uint8_t)(value >> 8);
        }
    }
    fakeBusy = false;
}

static void Fake_Tick(uint32_t nowMs)
{
    fakeNow = nowMs;
    if (fakeBusy && !fakeHold && ((uint32_t)(nowMs - fakeStarted) >= 2UL))
    {
        Fake_Complete();
    }
}

static void RunInputs(uint32_t firstMs, uint32_t lastMs)
{
    uint32_t tick;
    for (tick = firstMs; tick <= lastMs; tick++)
    {
        Fake_Tick(tick);
        HomeInputs_Task(tick);
    }
}

static int TestShtLifecycle(void)
{
    SHT30_Context_t context;
    bool complete;
    uint16_t humidity = 111U;
    uint8_t anotherCommand = 0U;
    Fake_Reset();
    SHT30_Initialize(&context);
    CHECK(SHT30_Start(&context, 0x44U, 0UL, 100UL) == SHT30_OK);
    CHECK(fakeWriteLength == 2U && fakeWrite[0] == 0x24U && fakeWrite[1] == 0U);
    CHECK(SHT30_Start(&context, 0x44U, 0UL, 100UL) == SHT30_BUSY);
    CHECK(SHT30_Task(&context, 0UL, &complete, &humidity) == SHT30_BUSY);
    CHECK(!complete && humidity == 111U);
    Fake_Complete();
    CHECK(SHT30_Task(&context, 1UL, &complete, &humidity) == SHT30_BUSY);
    CHECK(context.state == SHT30_STATE_WAIT_CONVERSION);
    CHECK(I2C_Bus_IsFree());
    CHECK(I2C_Bus_WriteStart(I2C_BUS_OWNER_MCP9808, 0x1CU, &anotherCommand, 1U) == I2C_BUS_OK);
    CHECK(SHT30_Task(&context, 16UL, &complete, &humidity) == SHT30_BUSY);
    CHECK(I2C_Bus_GetOwner() == I2C_BUS_OWNER_MCP9808);
    Fake_Complete();
    CHECK(I2C_Bus_Poll(I2C_BUS_OWNER_MCP9808) == I2C_BUS_OK);
    CHECK(SHT30_Task(&context, 17UL, &complete, &humidity) == SHT30_BUSY);
    CHECK(fakeReadLength == 6U && I2C_Bus_GetOwner() == I2C_BUS_OWNER_SHT30);
    Fake_Complete();
    CHECK(SHT30_Task(&context, 18UL, &complete, &humidity) == SHT30_OK);
    CHECK(complete && humidity == 500U && !SHT30_IsActive(&context));
    CHECK(I2C_Bus_IsFree());
    CHECK(g_i2cBusDebug.sht30.claimCount == 2UL);
    CHECK(g_i2cBusDebug.sht30.releaseCount == 2UL);
    CHECK(g_i2cBusDebug.ownerMismatchCount == 0UL);
    return 0;
}

static SHT30_Status_t Measure(SHT30_Context_t *context, uint16_t *humidity)
{
    bool complete;
    SHT30_Status_t status;
    SHT30_Initialize(context);
    status = SHT30_Start(context, 0x44U, 0UL, 100UL);
    if (status != SHT30_OK) { return status; }
    Fake_Complete();
    status = SHT30_Task(context, 1UL, &complete, humidity);
    if (status != SHT30_BUSY) { return status; }
    status = SHT30_Task(context, 17UL, &complete, humidity);
    if (status != SHT30_BUSY) { return status; }
    Fake_Complete();
    return SHT30_Task(context, 18UL, &complete, humidity);
}

static int TestShtFailures(void)
{
    SHT30_Context_t context;
    uint16_t humidity = 777U;
    bool complete;
    Fake_Reset();
    fakeShtFrame[2] ^= 1U;
    CHECK(Measure(&context, &humidity) == SHT30_ERROR_CRC && humidity == 777U);
    Fake_Reset();
    fakeShtFrame[5] ^= 1U;
    CHECK(Measure(&context, &humidity) == SHT30_ERROR_CRC && humidity == 777U);
    Fake_Reset();
    /* Published Sensirion CRC vector BEEF -> 92, a valid +85.5 C word. */
    fakeShtFrame[0] = 0xBEU; fakeShtFrame[1] = 0xEFU; fakeShtFrame[2] = 0x92U;
    CHECK(Measure(&context, &humidity) == SHT30_OK && humidity == 500U);
    Fake_Reset();
    fakeShtFrame[0] = 0U; fakeShtFrame[1] = 0U; fakeShtFrame[2] = 0x81U;
    CHECK(Measure(&context, &humidity) == SHT30_ERROR_RANGE);
    Fake_Reset();
    fakeShtPresent = false;
    CHECK(Measure(&context, &humidity) == SHT30_ERROR_I2C);
    Fake_Reset();
    SHT30_Initialize(&context);
    CHECK(SHT30_Start(&context, 0x46U, 0UL, 100UL) == SHT30_ERROR_PARAMETER);
    fakeAllowStart = false;
    CHECK(SHT30_Start(&context, 0x44U, 0UL, 100UL) == SHT30_ERROR_I2C);
    CHECK(I2C_Bus_IsFree());
    CHECK(g_i2cBusDebug.sht30.claimCount == g_i2cBusDebug.sht30.releaseCount);
    fakeAllowStart = true;
    CHECK(SHT30_Start(&context, 0x45U, 0UL, 100UL) == SHT30_OK);
    CHECK(SHT30_Task(&context, 100UL, &complete, &humidity) == SHT30_ERROR_TIMEOUT);
    CHECK(SHT30_IsActive(&context) && I2C_Bus_GetOwner() == I2C_BUS_OWNER_SHT30);
    CHECK(!I2C_Bus_DebugReset());
    CHECK(SHT30_Task(&context, 101UL, &complete, &humidity) == SHT30_BUSY);
    Fake_Complete();
    CHECK(SHT30_Task(&context, 102UL, &complete, &humidity) == SHT30_ERROR_TIMEOUT);
    CHECK(!complete && !SHT30_IsActive(&context) && I2C_Bus_IsFree());
    /* Completed hardware must not turn an old, unpolled request into a new
     * valid sample when the super-loop resumes after its deadline. */
    CHECK(SHT30_Start(&context, 0x44U, 200UL, 100UL) == SHT30_OK);
    Fake_Complete();
    CHECK(SHT30_Task(&context, 400UL, &complete, &humidity) == SHT30_ERROR_TIMEOUT);
    CHECK(!complete && !SHT30_IsActive(&context) && I2C_Bus_IsFree());
    return 0;
}

static int TestInputDebounceAndValidity(void)
{
    HomeInputsSnapshot_t snapshot;
    Fake_Reset();
    HomeInputs_Initialize(0UL);
    CHECK((ANSELA & 0x06U) == 0U && (ANSELA & 0xF9U) == 0xF9U);
    CHECK((TRISA & 0x06U) == 0x06U && (WPUA & 0x06U) == 0x06U);
    RunInputs(0UL, 99UL);
    HomeInputs_GetSnapshot(99UL, &snapshot);
    CHECK(!snapshot.rainValid && !snapshot.waterValid);
    CHECK(snapshot.humidityValid && snapshot.humidity10 == 500U);
    RunInputs(100UL, 200UL);
    HomeInputs_GetSnapshot(200UL, &snapshot);
    CHECK(snapshot.rainValid && !snapshot.rainWet && snapshot.waterValid && !snapshot.waterWet);
    PORTA &= (uint8_t)~0x02U;
    RunInputs(201UL, 240UL);
    PORTA |= 0x02U; /* Short wet pulse must not assert rain. */
    RunInputs(241UL, 250UL);
    HomeInputs_GetSnapshot(250UL, &snapshot);
    CHECK(!snapshot.rainWet);
    PORTA &= (uint8_t)~0x06U;
    RunInputs(251UL, 310UL);
    HomeInputs_GetSnapshot(310UL, &snapshot);
    CHECK(snapshot.rainWet && snapshot.waterWet);
    PORTA |= 0x06U;
    RunInputs(311UL, 510UL);
    HomeInputs_GetSnapshot(510UL, &snapshot);
    CHECK(snapshot.rainWet && snapshot.waterWet);
    RunInputs(511UL, 520UL);
    HomeInputs_GetSnapshot(520UL, &snapshot);
    CHECK(!snapshot.rainWet && !snapshot.waterWet);
    CHECK(snapshot.luxValid && snapshot.lux == 120UL);
    HomeInputs_GetSnapshot(4000UL, &snapshot);
    CHECK(!snapshot.humidityValid && !snapshot.luxValid && !snapshot.rainValid && !snapshot.waterValid);
    HomeInputs_GetSnapshot(0UL, NULL); /* Null output is harmless. */
    /* A long scheduler gap requires fresh debounce, not assumed stability. */
    RunInputs(4000UL, 4000UL);
    HomeInputs_GetSnapshot(4000UL, &snapshot);
    CHECK(!snapshot.rainValid && !snapshot.waterValid);
    return 0;
}

static int TestInputI2cErrorsAndSharing(void)
{
    HomeInputsSnapshot_t snapshot;
    VCNL4200_AsyncReadContext_t proximity;
    bool complete;
    uint16_t raw;
    Fake_Reset();
    HomeInputs_Initialize(0UL);
    RunInputs(0UL, 399UL);
    VCNL4200_AsyncReadInit(&proximity);
    fakeHold = true;
    CHECK(VCNL4200_ReadProximityRawAsyncStart(&proximity, 399UL, 100UL) == VCNL4200_OK);
    RunInputs(400UL, 410UL);
    CHECK(VCNL4200_AsyncReadIsActive(&proximity));
    CHECK(g_homeInputsDebug.luxBusyRetries > 0UL);
    CHECK(g_i2cBusDebug.ownerMismatchCount == 0UL);
    Fake_Complete();
    CHECK(VCNL4200_ReadProximityRawAsyncPoll(&proximity, 411UL, &complete, &raw) == VCNL4200_OK);
    fakeHold = false;
    RunInputs(411UL, 450UL);
    HomeInputs_GetSnapshot(450UL, &snapshot);
    CHECK(snapshot.luxValid && snapshot.lux == 120UL);
    fakeShtPresent = false;
    fakeVcnlPresent = false;
    RunInputs(451UL, 1200UL);
    HomeInputs_GetSnapshot(1200UL, &snapshot);
    CHECK(!snapshot.humidityValid && !snapshot.luxValid);
    CHECK(snapshot.humidity10 == 500U && snapshot.lux == 120UL);
    CHECK(g_homeInputsDebug.humidityErrors > 0UL && g_homeInputsDebug.luxErrors > 0UL);
    fakeShtPresent = true;
    fakeVcnlPresent = true;
    fakeAlsConfig = 0x0100U; /* 50ms, not the default 100ms. */
    RunInputs(1201UL, 2300UL);
    HomeInputs_GetSnapshot(2300UL, &snapshot);
    CHECK(snapshot.humidityValid && snapshot.luxValid && snapshot.lux == 240UL);
    fakeAlsConfig = 0x0141U; /* ALS shutdown must invalidate even if I2C works. */
    RunInputs(2301UL, 2900UL);
    HomeInputs_GetSnapshot(2900UL, &snapshot);
    CHECK(!snapshot.luxValid);
    CHECK(g_i2cBusDebug.ownerMismatchCount == 0UL);
    return 0;
}

static int TestTickWrapAndTimeoutDrain(void)
{
    HomeInputsSnapshot_t snapshot;
    uint32_t tick;
    Fake_Reset();
    fakeHold = true;
    HomeInputs_Initialize(0UL);
    RunInputs(0UL, 150UL);
    HomeInputs_GetSnapshot(150UL, &snapshot);
    CHECK(!snapshot.humidityValid && g_homeInputsDebug.humidityTimeouts == 1UL);
    CHECK(I2C_Bus_GetOwner() == I2C_BUS_OWNER_SHT30);
    fakeHold = false;
    RunInputs(151UL, 1200UL);
    HomeInputs_GetSnapshot(1200UL, &snapshot);
    CHECK(snapshot.humidityValid && g_homeInputsDebug.humidityTimeouts == 1UL);
    CHECK(g_i2cBusDebug.ownerMismatchCount == 0UL);
    Fake_Reset();
    HomeInputs_Initialize(0xFFFFFF00UL);
    PORTA &= (uint8_t)~0x06U;
    for (tick = 0UL; tick <= 700UL; tick++)
    {
        Fake_Tick(0xFFFFFF00UL + tick);
        HomeInputs_Task(0xFFFFFF00UL + tick);
    }
    HomeInputs_GetSnapshot(0xFFFFFF00UL + 700UL, &snapshot);
    CHECK(snapshot.humidityValid && snapshot.luxValid && snapshot.rainValid && snapshot.waterValid);
    CHECK(snapshot.rainWet && snapshot.waterWet);
    return 0;
}

int main(void)
{
    int result;
    result = TestShtLifecycle(); if (result != 0) { return result; }
    result = TestShtFailures(); if (result != 0) { return result; }
    result = TestInputDebounceAndValidity(); if (result != 0) { return result; }
    result = TestInputI2cErrorsAndSharing(); if (result != 0) { return result; }
    result = TestTickWrapAndTimeoutDrain(); if (result != 0) { return result; }
    return 0;
}
