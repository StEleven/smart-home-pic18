#include "hardware_stubs.h"
/* Direct includes keep the tested implementation unchanged and expose static
 * schedule state for exact bounds / interleaving assertions. */
#include "device_driver/servo_driver.c"
#include "service/servo_service.c"

#define CHECK(condition) do { if (!(condition)) { return __LINE__; } } while (0)

volatile ServoTestInterruptBits PIE5bits;
static void (*timerCallback)(void);
static uint32_t elapsedTicks;
static uint16_t scheduledTicks;
static uint32_t lowAt[4];
static bool pins[4];
static bool snapshotArmed;
static uint8_t hookCalls, injectedCallbacks;

void Test_PinHigh(uint8_t index) { pins[index] = true; }
void Test_PinLow(uint8_t index)
{
    if (pins[index]) { lowAt[index] = elapsedTicks; }
    pins[index] = false;
}
void TMR3_PeriodSet(uint16_t value) { (void)value; }
void TMR3_CounterSet(uint16_t value)
{
    scheduledTicks = (uint16_t)(65536UL - value);
}
void TMR3_OverflowCallbackRegister(void (*callback)(void)) { timerCallback = callback; }
void TMR3_OverflowInterruptEnable(void) { PIE5bits.TMR3IE = 1U; }
void TMR3_OverflowInterruptDisable(void) { PIE5bits.TMR3IE = 0U; }
void TMR3_Start(void) { }
void Test_SnapshotHook(void)
{
    hookCalls++;
    if (snapshotArmed && PIE5bits.TMR3IE)
    {
        snapshotArmed = false;
        injectedCallbacks++;
        /* Reach a frame boundary, where pending becomes active. */
        servoEventIndex = (uint8_t)(servoSchedules[servoActiveSchedule].eventCount - 1U);
        ServoDriver_TimerCallback();
    }
}

static void ResetTrace(void)
{
    uint8_t i;
    elapsedTicks = 0UL; scheduledTicks = 0U;
    snapshotArmed = false; hookCalls = injectedCallbacks = 0U;
    PIE5bits.TMR3IE = 0U;
    for (i = 0U; i < 4U; i++) { pins[i] = false; lowAt[i] = 0UL; }
}

static int TestFourChannelsAndBounds(void)
{
    uint8_t index, event;
    uint32_t sum;
    ServoDriver_Schedule_t *schedule;
    ResetTrace();
    ServoDriver_Initialize();
    ServoDriver_SetAngle(SERVO_DRIVER_ID_1, 0U);
    ServoDriver_SetAngle(SERVO_DRIVER_ID_2, 60U);
    ServoDriver_SetAngle(SERVO_DRIVER_ID_3, 120U);
    ServoDriver_SetAngle(SERVO_DRIVER_ID_4, 180U);
    schedule = &servoSchedules[servoPendingSchedule];
    CHECK(SERVO_DRIVER_COUNT == 4U && schedule->eventCount == 5U);
    sum = 0UL;
    for (event = 0U; event < schedule->eventCount; event++)
    {
        CHECK(schedule->events[event].delayTicks > 0U);
        sum += schedule->events[event].delayTicks;
    }
    CHECK(sum == 40000UL);
    servoEventIndex = (uint8_t)(servoSchedules[servoActiveSchedule].eventCount - 1U);
    timerCallback(); /* Apply pending at a frame boundary. */
    elapsedTicks = 0UL;
    for (event = 0U; event < 4U; event++)
    {
        elapsedTicks += scheduledTicks;
        timerCallback();
    }
    CHECK(lowAt[0] == 1000UL && lowAt[1] == 2333UL);
    CHECK(lowAt[2] == 3666UL && lowAt[3] == 5000UL);
    CHECK(scheduledTicks == 35000U);
    elapsedTicks += scheduledTicks;
    timerCallback();
    CHECK(elapsedTicks == 40000UL);
    for (index = 0U; index < 4U; index++) { CHECK(pins[index]); }
    /* Equal pulse widths must coalesce into one falling-edge event. */
    for (index = 0U; index < 4U; index++)
    {
        ServoDriver_SetAngle((ServoDriver_Id_t)index, 90U);
    }
    schedule = &servoSchedules[servoPendingSchedule];
    CHECK(schedule->eventCount == 2U && schedule->events[0].lowMask == 0x0FU);
    CHECK(schedule->events[0].delayTicks == 3000U && schedule->events[1].delayTicks == 37000U);
    ServoDriver_SetAngle(SERVO_DRIVER_ID_4, 255U);
    CHECK(ServoDriver_GetAngle(SERVO_DRIVER_ID_4) == 180U);
    return 0;
}

static int TestAtomicSnapshot(void)
{
    uint8_t freeSchedule;
    ResetTrace();
    ServoDriver_Initialize();
    ServoDriver_SetAngle(SERVO_DRIVER_ID_1, 0U);
    CHECK(servoActiveSchedule != servoPendingSchedule);
    snapshotArmed = true;
    freeSchedule = ServoDriver_GetFreeSchedule();
    CHECK(hookCalls > 0U); /* Test seam must be inside the real snapshot. */
    CHECK(injectedCallbacks == 0U);
    CHECK(freeSchedule != servoActiveSchedule && freeSchedule != servoPendingSchedule);
    CHECK(PIE5bits.TMR3IE == 1U);
    PIE5bits.TMR3IE = 0U;
    (void)ServoDriver_GetFreeSchedule();
    CHECK(PIE5bits.TMR3IE == 0U); /* Preserve a previously disabled interrupt. */
    return 0;
}

static int TestLargeStepsAndSoftwareState(void)
{
    ResetTrace();
    ServoService_Initialize(0UL);
    ServoService_SetImmediate(SERVO_SERVICE_DEVICE_CURTAIN, 180U);
    ServoService_SetMoveStep(SERVO_SERVICE_DEVICE_CURTAIN, 100U);
    ServoService_SetTarget(SERVO_SERVICE_DEVICE_CURTAIN, 170U);
    ServoService_Task(0UL);
    CHECK(ServoService_GetCurrentAngle(SERVO_SERVICE_DEVICE_CURTAIN) == 170U);
    CHECK(!ServoService_IsMoving(SERVO_SERVICE_DEVICE_CURTAIN));
    ServoService_SetMoveStep(SERVO_SERVICE_DEVICE_WINDOW, 3U);
    ServoService_WindowOpen();
    CHECK(ServoService_GetTargetAngle(SERVO_SERVICE_DEVICE_WINDOW) == 90U);
    CHECK(ServoService_GetCurrentAngle(SERVO_SERVICE_DEVICE_WINDOW) == 0U);
    CHECK(ServoService_IsMoving(SERVO_SERVICE_DEVICE_WINDOW));
    ServoService_Task(20UL);
    CHECK(ServoService_GetCurrentAngle(SERVO_SERVICE_DEVICE_WINDOW) == 3U);
    CHECK(ServoService_GetWindowState() == SERVO_SERVICE_WINDOW_OPEN);
    return 0;
}

int main(void)
{
    int result;
    result = TestFourChannelsAndBounds(); if (result) { return result; }
    result = TestAtomicSnapshot(); if (result) { return result; }
    result = TestLargeStepsAndSoftwareState(); if (result) { return result; }
    return 0;
}
