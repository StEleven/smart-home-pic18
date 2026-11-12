/* Production host_serial.c executes unchanged; only UART and automation APIs
 * are replaced. Freestanding helpers avoid any host C runtime dependency. */
#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>
#include "host_serial.h"
#include "home_automation.h"
#include "mcc_generated_files/uart/uart1.h"

void *memset(void *dest, int value, size_t length)
{
    unsigned char *out = dest;
    while (length--) { *out++ = (unsigned char)value; }
    return dest;
}
size_t strlen(const char *str) { size_t n=0; while (str[n]) { n++; } return n; }
char *strcpy(char *dest, const char *source)
{
    char *out = dest;
    while ((*dest++ = *source++) != '\0') { }
    return out;
}
int strcmp(const char *a, const char *b)
{
    while (*a && (*a == *b)) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}
int strncmp(const char *a, const char *b, size_t length)
{
    while (length && *a && (*a == *b)) { a++; b++; length--; }
    return length ? (unsigned char)*a - (unsigned char)*b : 0;
}
char *strchr(const char *str, int ch)
{
    do { if (*str == ch) { return (char *)str; } } while (*str++);
    return NULL;
}

volatile SerialTestErrorBits U1ERRIRbits;
volatile SerialTestPriorityBits IPR4bits;
volatile SerialTestEnableBits PIE4bits;
static HomeAutomation_State_t testState;
static uint32_t commandCalls;
static uint8_t uartRx[4096];
static uint16_t uartRxLength, uartRxPosition;
static char uartTx[65536];
static uint32_t uartTxLength;
static bool txReady;

bool UART1_IsTxReady(void) { return txReady; }
bool UART1_IsRxReady(void) { return uartRxPosition < uartRxLength; }
uint8_t UART1_Read(void) { return uartRx[uartRxPosition++]; }
void UART1_Write(uint8_t byte)
{
    if (uartTxLength < sizeof(uartTx)-1U) { uartTx[uartTxLength++] = (char)byte; }
    uartTx[uartTxLength] = '\0';
}
const HomeAutomation_State_t *HomeAutomation_GetState(void) { return &testState; }
bool HomeAutomation_Command(const char *action, const char *value,
                            uint32_t nowMs, const char **reason)
{
    (void)nowMs;
    if (!strcmp(action,"light_effect")) {
        testState.lightEffect = !strcmp(value,"rainbow") ? HOME_LIGHT_RAINBOW :
            !strcmp(value,"pulse") ? HOME_LIGHT_PULSE : !strcmp(value,"party") ? HOME_LIGHT_PARTY : HOME_LIGHT_WARM;
    } else if (!strcmp(action,"demand")) {
        testState.demandManual = strcmp(value,"auto") != 0;
        testState.demand = !strcmp(value,"1");
    } else if (!strcmp(action,"ktv_brightness")) {
        uint8_t level = 0U;
        while (*value >= '0' && *value <= '9') { level = (uint8_t)(level * 10U + (uint8_t)(*value++ - '0')); }
        testState.ktvBrightness = level;
    }
    commandCalls++;
    *reason = "OK";
    return true;
}
const char *HomeAutomation_SceneName(HomeScene_t scene)
{
    static const char *names[] = {"home", "away", "long_away", "sleep", "movie", "ktv"};
    return names[(unsigned int)scene < 6U ? scene : 0U];
}
const char *HomeAutomation_TimerName(HomeTimer_t timer)
{
    static const char *names[] = {"idle", "running", "paused", "done"};
    return names[(unsigned int)timer < 4U ? timer : 0U];
}

void Test_Reset(uint32_t nowMs)
{
    memset(&testState, 0, sizeof testState);
    testState.tempValid = true; testState.temp10 = -123;
    testState.inputs.humidityValid = true; testState.inputs.humidity10 = 500U;
    testState.inputs.luxValid = true; testState.inputs.lux = 120UL;
    testState.inputs.rainValid = true; testState.inputs.waterValid = true;
    testState.door = 1U; testState.window = 1U; testState.setpoint10 = 315;
    testState.comfort = 2U; testState.awayCheckOk = true;
    testState.ktvBrightness = 50U;
    commandCalls = 0UL;
    uartRxPosition = uartRxLength = 0U;
    uartTxLength = 0UL; uartTx[0] = '\0'; txReady = true;
    U1ERRIRbits.RXFOIF = U1ERRIRbits.FERIF = U1ERRIRbits.PERIF = 0U;
    HostSerial_Initialize(nowMs);
}
void Test_Input(const char *data, uint32_t length)
{
    uint32_t index;
    uartRxLength = uartRxPosition = 0U;
    for (index = 0; index < length && index < sizeof uartRx; index++)
    {
        uartRx[uartRxLength++] = (uint8_t)data[index];
    }
    while (UART1_IsRxReady()) { HostSerial_RxISR(); }
}
void Test_Task(uint32_t nowMs) { HostSerial_Task(nowMs); }
const char *Test_Output(void) { return uartTx; }
void Test_ClearOutput(void) { uartTxLength = 0UL; uartTx[0] = '\0'; }
uint32_t Test_CommandCalls(void) { return commandCalls; }
uint32_t Test_RxOverflows(void) { return g_hostSerialDebug.rxOverflows; }
uint32_t Test_Rejects(void) { return g_hostSerialDebug.rejectedFrames; }
void Test_SetTxReady(uint32_t ready) { txReady = (ready != 0UL); }
void Test_UnknownInputs(void)
{
    testState.tempValid = false;
    testState.inputs.humidityValid = false; testState.inputs.luxValid = false;
    testState.inputs.rainValid = false; testState.inputs.waterValid = false;
}
