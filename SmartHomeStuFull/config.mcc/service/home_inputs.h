/** @file home_inputs.h
 * Real humidity, ambient-light and digital wet inputs. Valid flags describe
 * recent successful acquisition, never a substituted / simulated value.
 */
#ifndef HOME_INPUTS_H
#define HOME_INPUTS_H

#include <stdbool.h>
#include <stdint.h>

typedef struct
{
    bool humidityValid;
    uint16_t humidity10;
    bool luxValid;
    uint32_t lux;
    bool rainValid;
    bool rainWet;
    bool waterValid;
    bool waterWet;
} HomeInputsSnapshot_t;

typedef struct
{
    uint32_t humiditySamples;
    uint32_t humidityErrors;
    uint32_t humidityTimeouts;
    uint32_t humidityBusyRetries;
    uint32_t humidityLastUpdateMs;
    uint8_t humidityStatus;
    uint32_t luxSamples;
    uint32_t luxErrors;
    uint32_t luxTimeouts;
    uint32_t luxBusyRetries;
    uint32_t luxLastUpdateMs;
    uint16_t luxConfig;
    uint16_t luxRaw;
    uint8_t luxStatus;
} HomeInputsDebug_t;

extern volatile HomeInputsDebug_t g_homeInputsDebug;

/** Call once at boot after SYSTEM_Initialize and before periodic Tasks.
 * RA1 / RA2 default to digital inputs with weak pull-ups; polarity and masks
 * are configurable in extension_config.h. A plain DO wire has no disconnect
 * diagnostic: valid means a recently sampled, debounced logic level only.
 */
void HomeInputs_Initialize(uint32_t nowMs);
void HomeInputs_Task(uint32_t nowMs);
void HomeInputs_GetSnapshot(uint32_t nowMs, HomeInputsSnapshot_t *out);

#endif
