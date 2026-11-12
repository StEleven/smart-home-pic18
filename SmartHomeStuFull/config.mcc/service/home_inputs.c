/** @file home_inputs.c
 * Input Services run short steps from the super-loop. No delay, wait loop or
 * forced I2C release is used. VCNL4200 ALS shares its existing software owner
 * with ProximityService; only a successfully started local context is polled.
 */
#include <stddef.h>
#include <xc.h>
#include "extension_config.h"
#include "home_inputs.h"
#include "sht30.h"
#include "vcnl4200.h"

#ifndef HOME_SHT30_ADDRESS
#define HOME_SHT30_ADDRESS 0x44U
#endif
#ifndef HOME_RAIN_PIN_MASK
#define HOME_RAIN_PIN_MASK (1U << 1)
#endif
#ifndef HOME_WATER_PIN_MASK
#define HOME_WATER_PIN_MASK (1U << 2)
#endif
#ifndef HOME_RAIN_ACTIVE_LOW
#define HOME_RAIN_ACTIVE_LOW 1
#endif
#ifndef HOME_WATER_ACTIVE_LOW
#define HOME_WATER_ACTIVE_LOW 1
#endif
#ifndef HOME_INPUT_SAMPLE_MS
#define HOME_INPUT_SAMPLE_MS 10UL
#endif
#ifndef HOME_INPUT_STARTUP_MS
#define HOME_INPUT_STARTUP_MS 100UL
#endif
#ifndef HOME_INPUT_WET_CONFIRM_MS
#define HOME_INPUT_WET_CONFIRM_MS 50UL
#endif
#ifndef HOME_INPUT_DRY_CONFIRM_MS
#define HOME_INPUT_DRY_CONFIRM_MS 200UL
#endif
#ifndef HOME_INPUT_DIGITAL_STALE_MS
#define HOME_INPUT_DIGITAL_STALE_MS 100UL
#endif
#ifndef HOME_HUMIDITY_SAMPLE_MS
#define HOME_HUMIDITY_SAMPLE_MS 1000UL
#endif
#ifndef HOME_HUMIDITY_STALE_MS
#define HOME_HUMIDITY_STALE_MS 3000UL
#endif
#ifndef HOME_LUX_SAMPLE_MS
#define HOME_LUX_SAMPLE_MS 500UL
#endif
#ifndef HOME_LUX_STALE_MS
#define HOME_LUX_STALE_MS 2000UL
#endif
#ifndef HOME_INPUT_I2C_TIMEOUT_MS
#define HOME_INPUT_I2C_TIMEOUT_MS 100UL
#endif
#ifndef HOME_INPUT_BUS_RETRY_MS
#define HOME_INPUT_BUS_RETRY_MS 5UL
#endif

typedef struct
{
    bool candidateKnown;
    bool candidateWet;
    bool valid;
    bool wet;
    uint32_t candidateSinceMs;
} HomeInputsDigital_t;

typedef enum
{
    HOME_LUX_IDLE = 0,
    HOME_LUX_WAIT_CONFIG,
    HOME_LUX_START_DATA,
    HOME_LUX_WAIT_DATA
} HomeInputsLuxState_t;

static SHT30_Context_t humidityContext;
static VCNL4200_AsyncReadContext_t luxContext;
static HomeInputsLuxState_t luxState;
static bool luxTimedOut;
static uint8_t luxIntegration;
static HomeInputsDigital_t rainInput;
static HomeInputsDigital_t waterInput;
static uint32_t initializedMs;
static uint32_t digitalNextMs;
static uint32_t digitalLastMs;
static bool digitalSampled;
static uint32_t humidityNextMs;
static uint32_t luxNextMs;
static bool humidityHealthy;
static bool luxHealthy;
static uint16_t humidityValue10;
static uint32_t luxValue;

volatile HomeInputsDebug_t g_homeInputsDebug;

static bool HomeInputs_TimeReached(uint32_t nowMs, uint32_t targetMs)
{
    return ((int32_t)(nowMs - targetMs) >= 0);
}

static void HomeInputs_ResetDigital(HomeInputsDigital_t *input)
{
    input->candidateKnown = false;
    input->candidateWet = false;
    input->valid = false;
    input->wet = false;
    input->candidateSinceMs = 0UL;
}

static void HomeInputs_UpdateDigital(HomeInputsDigital_t *input, bool wet,
                                     uint32_t nowMs)
{
    uint32_t confirmationMs;
    if ((!input->candidateKnown) || (input->candidateWet != wet))
    {
        input->candidateKnown = true;
        input->candidateWet = wet;
        input->candidateSinceMs = nowMs;
    }
    confirmationMs = wet ? HOME_INPUT_WET_CONFIRM_MS : HOME_INPUT_DRY_CONFIRM_MS;
    if (((uint32_t)(nowMs - initializedMs) >= HOME_INPUT_STARTUP_MS) &&
        ((uint32_t)(nowMs - input->candidateSinceMs) >= confirmationMs))
    {
        input->wet = wet;
        input->valid = true;
    }
}

static void HomeInputs_DigitalTask(uint32_t nowMs)
{
    uint8_t pins;
    bool rainWet;
    bool waterWet;
    if (!HomeInputs_TimeReached(nowMs, digitalNextMs)) { return; }
    if (digitalSampled &&
        ((uint32_t)(nowMs - digitalLastMs) > HOME_INPUT_DIGITAL_STALE_MS))
    {
        HomeInputs_ResetDigital(&rainInput);
        HomeInputs_ResetDigital(&waterInput);
    }
    pins = PORTA;
    rainWet = ((pins & HOME_RAIN_PIN_MASK) != 0U);
    waterWet = ((pins & HOME_WATER_PIN_MASK) != 0U);
#if HOME_RAIN_ACTIVE_LOW
    rainWet = !rainWet;
#endif
#if HOME_WATER_ACTIVE_LOW
    waterWet = !waterWet;
#endif
    HomeInputs_UpdateDigital(&rainInput, rainWet, nowMs);
    HomeInputs_UpdateDigital(&waterInput, waterWet, nowMs);
    digitalSampled = true;
    digitalLastMs = nowMs;
    digitalNextMs = nowMs + HOME_INPUT_SAMPLE_MS;
}

static void HomeInputs_HumidityTask(uint32_t nowMs)
{
    SHT30_Status_t status;
    uint16_t humidity10;
    bool complete;
    if (!SHT30_IsActive(&humidityContext))
    {
        if (!HomeInputs_TimeReached(nowMs, humidityNextMs)) { return; }
        status = SHT30_Start(&humidityContext, HOME_SHT30_ADDRESS, nowMs,
                             HOME_INPUT_I2C_TIMEOUT_MS);
        g_homeInputsDebug.humidityStatus = (uint8_t)status;
        if (status == SHT30_BUSY)
        {
            g_homeInputsDebug.humidityBusyRetries++;
            humidityNextMs = nowMs + HOME_INPUT_BUS_RETRY_MS;
        }
        else if (status != SHT30_OK)
        {
            humidityHealthy = false;
            g_homeInputsDebug.humidityErrors++;
            humidityNextMs = nowMs + HOME_HUMIDITY_SAMPLE_MS;
        }
        return;
    }
    status = SHT30_Task(&humidityContext, nowMs, &complete, &humidity10);
    g_homeInputsDebug.humidityStatus = (uint8_t)status;
    if (status == SHT30_BUSY) { return; }
    if (status != SHT30_OK)
    {
        humidityHealthy = false;
        if (status == SHT30_ERROR_TIMEOUT)
        {
            /* Count the diagnostic event once; the eventual drain is not a
             * second failed sample. The driver keeps the owner while busy. */
            if (SHT30_IsActive(&humidityContext))
            {
                g_homeInputsDebug.humidityTimeouts++;
                g_homeInputsDebug.humidityErrors++;
            }
            else if (!humidityContext.timeoutReported)
            {
                g_homeInputsDebug.humidityTimeouts++;
                g_homeInputsDebug.humidityErrors++;
            }
        }
        else { g_homeInputsDebug.humidityErrors++; }
    }
    else if (complete)
    {
        humidityValue10 = humidity10;
        humidityHealthy = true;
        g_homeInputsDebug.humiditySamples++;
        g_homeInputsDebug.humidityLastUpdateMs = nowMs;
    }
    if (!SHT30_IsActive(&humidityContext))
    {
        humidityNextMs = nowMs + HOME_HUMIDITY_SAMPLE_MS;
    }
}

static void HomeInputs_LuxFailed(uint32_t nowMs)
{
    luxHealthy = false;
    g_homeInputsDebug.luxErrors++;
    luxState = HOME_LUX_IDLE;
    luxNextMs = nowMs + HOME_LUX_SAMPLE_MS;
}

static void HomeInputs_LuxTask(uint32_t nowMs)
{
    VCNL4200_Status_t status;
    bool complete;
    uint16_t value;
    uint8_t reg;
    if ((luxState == HOME_LUX_IDLE) || (luxState == HOME_LUX_START_DATA))
    {
        if (!HomeInputs_TimeReached(nowMs, luxNextMs)) { return; }
        reg = (luxState == HOME_LUX_IDLE)
            ? VCNL4200_REG_ALS_CONF : VCNL4200_REG_ALS_DATA;
        status = VCNL4200_ReadRegister16AsyncStart(&luxContext, reg, nowMs,
                                                  HOME_INPUT_I2C_TIMEOUT_MS);
        g_homeInputsDebug.luxStatus = (uint8_t)status;
        if (status == VCNL4200_BUSY)
        {
            /* Proximity may own VCNL4200: do not poll its context or steal
             * its owner. Yield for a few milliseconds and retry our Start. */
            g_homeInputsDebug.luxBusyRetries++;
            luxNextMs = nowMs + HOME_INPUT_BUS_RETRY_MS;
            return;
        }
        if (status != VCNL4200_OK)
        {
            HomeInputs_LuxFailed(nowMs);
            return;
        }
        luxTimedOut = false;
        luxState = (luxState == HOME_LUX_IDLE)
            ? HOME_LUX_WAIT_CONFIG : HOME_LUX_WAIT_DATA;
        return;
    }

    status = VCNL4200_ReadRegister16AsyncPoll(&luxContext, nowMs, &complete, &value);
    g_homeInputsDebug.luxStatus = (uint8_t)status;
    if (status == VCNL4200_BUSY) { return; }
    if ((status == VCNL4200_ERROR_TIMEOUT) &&
        VCNL4200_AsyncReadIsActive(&luxContext))
    {
        luxHealthy = false;
        luxTimedOut = true;
        g_homeInputsDebug.luxTimeouts++;
        return;
    }
    if (VCNL4200_AsyncReadIsActive(&luxContext)) { return; }
    /* A paused super-loop can miss the BUSY timeout event. A completed old
     * transaction is still too old to become a newly timestamped sample. */
    if (!luxTimedOut &&
        ((uint32_t)(nowMs - luxContext.startMs) >= HOME_INPUT_I2C_TIMEOUT_MS))
    {
        luxTimedOut = true;
        g_homeInputsDebug.luxTimeouts++;
    }
    if ((status != VCNL4200_OK) || !complete || luxTimedOut)
    {
        HomeInputs_LuxFailed(nowMs);
        return;
    }
    if (luxState == HOME_LUX_WAIT_CONFIG)
    {
        g_homeInputsDebug.luxConfig = value;
        /* Vishay datasheet 84430 rev1.8: ALS_SD bit0, IT bits7:6;
         * high reserved byte must remain 01H. Read the real setting rather
         * than assuming that boot configuration succeeded (normally 100ms).
         * https://www.vishay.com/docs/84430/vcnl4200.pdf tables 2,3,14 */
        if (((value & 0x0001U) != 0U) || ((value & 0xFF00U) != 0x0100U))
        {
            HomeInputs_LuxFailed(nowMs);
            return;
        }
        luxIntegration = (uint8_t)((value >> 6) & 0x03U);
        luxState = HOME_LUX_START_DATA;
        luxNextMs = nowMs;
        return;
    }
    g_homeInputsDebug.luxRaw = value;
    /* 50/100/200/400ms: .024/.012/.006/.003 lx/count. Round to
     * integer lux, using 32-bit arithmetic before multiplying raw counts. */
    luxValue = (((uint32_t)value * (24UL >> luxIntegration)) + 500UL) / 1000UL;
    luxHealthy = true;
    g_homeInputsDebug.luxSamples++;
    g_homeInputsDebug.luxLastUpdateMs = nowMs;
    luxState = HOME_LUX_IDLE;
    luxNextMs = nowMs + HOME_LUX_SAMPLE_MS;
}

void HomeInputs_Initialize(uint32_t nowMs)
{
    uint8_t inputMask = (uint8_t)(HOME_RAIN_PIN_MASK | HOME_WATER_PIN_MASK);
    /* Keep MCC-generated files intact; configure only the two added pins. */
    ANSELA &= (uint8_t)~inputMask;
    TRISA |= inputMask;
    WPUA |= inputMask;
    HomeInputs_ResetDigital(&rainInput);
    HomeInputs_ResetDigital(&waterInput);
    SHT30_Initialize(&humidityContext);
    VCNL4200_AsyncReadInit(&luxContext);
    initializedMs = nowMs;
    digitalNextMs = nowMs;
    digitalLastMs = nowMs;
    digitalSampled = false;
    humidityNextMs = nowMs + 10UL;
    luxNextMs = nowMs + 400UL; /* First ALS integration has time to finish. */
    humidityHealthy = false;
    luxHealthy = false;
    humidityValue10 = 0U;
    luxValue = 0UL;
    luxState = HOME_LUX_IDLE;
    luxTimedOut = false;
    luxIntegration = 1U;
    g_homeInputsDebug.humiditySamples = 0UL;
    g_homeInputsDebug.humidityErrors = 0UL;
    g_homeInputsDebug.humidityTimeouts = 0UL;
    g_homeInputsDebug.humidityBusyRetries = 0UL;
    g_homeInputsDebug.humidityLastUpdateMs = 0UL;
    g_homeInputsDebug.humidityStatus = (uint8_t)SHT30_OK;
    g_homeInputsDebug.luxSamples = 0UL;
    g_homeInputsDebug.luxErrors = 0UL;
    g_homeInputsDebug.luxTimeouts = 0UL;
    g_homeInputsDebug.luxBusyRetries = 0UL;
    g_homeInputsDebug.luxLastUpdateMs = 0UL;
    g_homeInputsDebug.luxConfig = 0U;
    g_homeInputsDebug.luxRaw = 0U;
    g_homeInputsDebug.luxStatus = (uint8_t)VCNL4200_OK;
}

void HomeInputs_Task(uint32_t nowMs)
{
    HomeInputs_DigitalTask(nowMs);
    HomeInputs_HumidityTask(nowMs);
    HomeInputs_LuxTask(nowMs);
}

void HomeInputs_GetSnapshot(uint32_t nowMs, HomeInputsSnapshot_t *out)
{
    bool digitalFresh;
    if (out == NULL) { return; }
    digitalFresh = digitalSampled &&
        ((uint32_t)(nowMs - digitalLastMs) <= HOME_INPUT_DIGITAL_STALE_MS);
    out->humidityValid = humidityHealthy &&
        (g_homeInputsDebug.humiditySamples != 0UL) &&
        ((uint32_t)(nowMs - g_homeInputsDebug.humidityLastUpdateMs) <= HOME_HUMIDITY_STALE_MS);
    out->humidity10 = humidityValue10;
    out->luxValid = luxHealthy && (g_homeInputsDebug.luxSamples != 0UL) &&
        ((uint32_t)(nowMs - g_homeInputsDebug.luxLastUpdateMs) <= HOME_LUX_STALE_MS);
    out->lux = luxValue;
    out->rainValid = digitalFresh && rainInput.valid;
    out->rainWet = rainInput.wet;
    out->waterValid = digitalFresh && waterInput.valid;
    out->waterWet = waterInput.wet;
}
