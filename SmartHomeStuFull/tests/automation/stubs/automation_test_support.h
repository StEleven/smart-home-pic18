#ifndef AUTOMATION_TEST_SUPPORT_H
#define AUTOMATION_TEST_SUPPORT_H
#include <stdbool.h>
#include <stdint.h>
typedef struct { bool humidityValid; uint16_t humidity10; bool luxValid; uint32_t lux;
    bool rainValid; bool rainWet; bool waterValid; bool waterWet; } HomeInputsSnapshot_t;
void HomeInputs_GetSnapshot(uint32_t nowMs, HomeInputsSnapshot_t *out);
typedef enum { BUTTON_ID_NONE=0, BUTTON_ID_SW1, BUTTON_ID_SW2, BUTTON_ID_SW3,
    BUTTON_ID_JOY_UP, BUTTON_ID_JOY_DOWN, BUTTON_ID_JOY_LEFT, BUTTON_ID_JOY_RIGHT,
    BUTTON_ID_JOY_PUSH, BUTTON_ID_COUNT } ButtonService_ButtonId_t;
typedef enum { BUTTON_EVENT_NONE=0, BUTTON_EVENT_PRESS, BUTTON_EVENT_RELEASE,
    BUTTON_EVENT_SHORT_PRESS, BUTTON_EVENT_LONG_PRESS } ButtonService_EventType_t;
typedef struct { ButtonService_ButtonId_t button; ButtonService_EventType_t type; } ButtonService_Event_t;
bool ButtonService_TakeEvent(ButtonService_Event_t *event);
typedef struct { char line[8][21]; } DisplayService_View_t;
void DisplayService_ViewClear(DisplayService_View_t *view);
bool DisplayService_ViewSetLine(DisplayService_View_t *view, uint8_t line, const char *text);
void DisplayService_SetAwake(bool awake);
bool DisplayService_SubmitView(const DisplayService_View_t *view);
bool TemperatureService_IsHealthy(void);
bool TemperatureService_IsValid(void);
uint32_t TemperatureService_GetLastUpdateMs(void);
uint32_t TemperatureService_GetSampleCount(void);
bool TemperatureService_GetCelsius(float *temperature);
bool PotentiometerService_GetPercent(uint8_t *percent);
uint32_t PotentiometerService_GetLastUpdateMs(void);
bool ProximityService_IsHealthy(void);
bool ProximityService_IsValid(void);
bool ProximityService_IsPresent(void);
uint32_t ProximityService_GetLastUpdateMs(void);
typedef enum { PROXIMITY_EVENT_NONE=0, PROXIMITY_EVENT_PERSON_ENTER, PROXIMITY_EVENT_PERSON_LEAVE } ProximityService_Event_t;
ProximityService_Event_t ProximityService_TakeEvent(void);
typedef enum { SERVO_SERVICE_DEVICE_DOOR=0, SERVO_SERVICE_DEVICE_WINDOW,
    SERVO_SERVICE_DEVICE_VENT, SERVO_SERVICE_DEVICE_CURTAIN, SERVO_SERVICE_DEVICE_COUNT } ServoService_Device_t;
uint8_t ServoService_GetCurrentAngle(ServoService_Device_t device);
uint8_t ServoService_GetTargetAngle(ServoService_Device_t device);
bool ServoService_IsMoving(ServoService_Device_t device);
void ServoService_SetTarget(ServoService_Device_t device, uint8_t angle);
void ServoService_SetMoveStep(ServoService_Device_t device, uint8_t step);
void ServoService_DoorOpen(void);
void ServoService_DoorClose(void);
void ServoService_WindowOpen(void);
void ServoService_WindowClose(void);
void ServoService_VentClose(void);
#define LED_SERVICE_LED0_MASK 0x01U
#define LED_SERVICE_LED1_MASK 0x02U
#define LED_SERVICE_LED2_MASK 0x04U
#define LED_SERVICE_LED3_MASK 0x08U
#define LED_SERVICE_LED4_MASK 0x10U
#define LED_SERVICE_LED5_MASK 0x20U
void LEDService_Set(uint8_t mask, bool on);
void WS2812BService_SetBrightness(uint8_t brightness);
void WS2812BService_SetPixel(uint8_t pixel, uint8_t red, uint8_t green, uint8_t blue);
void WS2812BService_Clear(void);
void WS2812BService_RainbowBreathe(uint32_t period);
void RGBLEDService_Off(void);
void RGBLEDService_SetColor(uint8_t r, uint8_t g, uint8_t b);
void RGBLEDService_Breathe(uint8_t r, uint8_t g, uint8_t b, uint32_t period);
typedef struct { uint16_t frequencyHz, durationMs; } MusicService_MelodyEvent_t;
typedef struct { uint32_t playCount; } MusicService_Debug_t;
extern MusicService_Debug_t g_musicServiceDebug;
#define MUSIC_SERVICE_OK 0
bool MusicService_IsPlaying(void);
int MusicService_PlayMelody(const MusicService_MelodyEvent_t *notes, uint16_t length, bool loop);
void MusicService_Stop(void);
#endif
