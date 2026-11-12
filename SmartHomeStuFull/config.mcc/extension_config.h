/* Project-owned configuration. MCC regeneration must not replace this file. */
#ifndef EXTENSION_CONFIG_H
#define EXTENSION_CONFIG_H

#ifndef SMART_HOME_EXTENSIONS_ENABLE
#define SMART_HOME_EXTENSIONS_ENABLE 1
#endif

/* Added modules use I2C1 (RB1 SCL/RB2 SDA) and the following GPIO defaults.
 * Original SERVO1/2/3 and all existing MCC peripherals are retained.
 * Change these definitions to match wiring; no pin is inferred from a sensor SKU.
 */
#define HOME_SHT30_ADDRESS       0x44U
#define HOME_RAIN_PIN_MASK       (1U << 1) /* RA1 */
#define HOME_WATER_PIN_MASK      (1U << 2) /* RA2 */
#define HOME_RAIN_ACTIVE_LOW     1
#define HOME_WATER_ACTIVE_LOW    1

#define HOME_CURTAIN_PIN_INIT() do { \
    ANSELAbits.ANSELA3 = 0; LATAbits.LATA3 = 0; \
    ODCONAbits.ODCA3 = 0; TRISAbits.TRISA3 = 0; RA3PPS = 0; \
} while (0)
#define HOME_CURTAIN_PIN_HIGH() (LATAbits.LATA3 = 1)
#define HOME_CURTAIN_PIN_LOW()  (LATAbits.LATA3 = 0)

#define HOME_SERIAL_STATE_PERIOD_MS 500UL
#define HOME_FIRMWARE_VERSION "smarthome-1.4"

#endif
