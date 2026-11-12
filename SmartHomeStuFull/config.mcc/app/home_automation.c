/** Standalone board policy. Runs without Presence or a connected host.
 * Inputs are real sensor snapshots; positions are software command feedback.
 */
#include "home_automation.h"
#include "temperature_service.h"
#include "potentiometer_service.h"
#include "proximity_service.h"
#include "servo_service.h"
#include "led_service.h"
#include "ws2812b_service.h"
#include "rgb_led_service.h"
#include "music_service.h"
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define HOME_MANUAL_MS           60000UL
#define HOME_TEMP_MAX_AGE_MS      3000UL
#define HOME_POT_MAX_AGE_MS       1000UL
#define HOME_PRESENCE_MAX_AGE_MS  1000UL
#define HOME_CURTAIN_STABLE_MS    3000UL
/* Default demonstration thresholds within VCNL4200's configured 100 ms range. */
#define HOME_CURTAIN_CLOSE_LUX      500UL
#define HOME_CURTAIN_OPEN_LUX       300UL
#define HOME_NIGHT_MS            30000UL
#define HOME_AWAY_CHECK_MS        3000UL
#define HOME_ALARM_PERIOD_MS     10000UL

typedef struct { bool active; uint8_t value; uint32_t untilMs; } Manual_t;
typedef enum {
    CONTROL_SCENE = 0, CONTROL_WINDOW, CONTROL_DOOR, CONTROL_CURTAIN,
    CONTROL_LIVING, CONTROL_BEDROOM, CONTROL_HALL, CONTROL_LOAD,
    CONTROL_DEMAND, CONTROL_TIMER, CONTROL_NIGHT, CONTROL_EFFECT,
    CONTROL_KTV_LEVEL, CONTROL_COUNT
} LocalControl_t;

static HomeAutomation_State_t home;
static Manual_t manualDoor, manualWindow, manualCurtain;
static Manual_t manualLiving, manualBedroom, manualHall, manualDemand;
static bool autoDemand, curtainShaded, curtainCandidate, curtainWaiting;
static uint32_t curtainCandidateMs, previousTaskMs, timerRemainingMs;
static bool previousWaterWet, awayAlarmSent, timerReminder;
static bool waterSoundOwned;
static uint32_t waterSoundPlayCount;
static uint32_t nextWaterSoundMs, awayCheckStartMs, nightUntilMs;
static uint8_t previousRGB, localControl;
static uint32_t lightEffectStartMs;
static uint32_t studyStartMs;
static uint32_t localTimerSetting;
static const char *localResult;
static char noticeText[21U], noticeDetail[21U];
static uint32_t noticeUntilMs;
static bool noticeReady, noticeCooling, noticeLoad;
static HomeScene_t noticeScene;
static HomeTimer_t noticeTimer;

static const MusicService_MelodyEvent_t alarmNotes[] = {
    { 880U, 120U }, { 0U, 70U }, { 880U, 120U }
};
static const MusicService_MelodyEvent_t timerNotes[] = {
    { 660U, 100U }, { 880U, 150U }
};

static bool Reached(uint32_t nowMs, uint32_t targetMs)
{ return ((int32_t)(nowMs - targetMs) >= 0); }

static bool IsAway(void)
{ return ((home.scene == HOME_SCENE_AWAY) || (home.scene == HOME_SCENE_LONG_AWAY)); }

static bool IsQuiet(void)
{ return ((home.scene == HOME_SCENE_SLEEP) || (home.scene == HOME_SCENE_MOVIE)); }

static void CopyNotice(char *destination, const char *source)
{
    uint8_t i = 0U;
    do {
        destination[i] = source[i];
        if (destination[i] == '\0') { return; }
    } while (++i < 20U);
    destination[20U] = '\0';
}

static void Notice(const char *text, const char *detail, uint32_t nowMs)
{
    /* Host command strings belong to the reused RX buffer, so own our snapshot. */
    CopyNotice(noticeText, text); CopyNotice(noticeDetail, detail);
    noticeUntilMs = nowMs + 3000UL;
}

static void EffectNotice(uint32_t nowMs)
{
    Notice(home.lightEffect == HOME_LIGHT_RAINBOW ? "RAINBOW FLOW" :
        home.lightEffect == HOME_LIGHT_PULSE ? "COLOR PULSE" :
        home.lightEffect == HOME_LIGHT_PARTY ? "PARTY BEAT" : "LIGHTS ON", "KTV LIGHT EFFECT", nowMs);
}

static void TimerNotice(uint32_t nowMs)
{
    Notice(home.timer == HOME_TIMER_RUNNING ? "STUDY STARTED" :
        home.timer == HOME_TIMER_PAUSED ? "STUDY PAUSED" : "STUDY ENDED", "STUDY TIMER", nowMs);
}

static void UpdateNotices(uint32_t nowMs)
{
    if (noticeReady) {
        if (home.scene != noticeScene) {
            Notice(home.scene == HOME_SCENE_KTV ? "KTV MODE" : "SCENE",
                HomeAutomation_SceneName(home.scene), nowMs);
        } else if (home.timer != noticeTimer) { TimerNotice(nowMs); }
        else if (home.cooling != noticeCooling) {
            Notice(home.cooling ? "AIR CONDITIONER ON" : "AIR CONDITIONER OFF", "AIR CONDITIONER", nowMs);
        } else if (home.loadSwitch != noticeLoad) {
            Notice(home.loadSwitch ? "TV ON" : "TV OFF", "SWITCHABLE APPLIANCE", nowMs);
        }
    }
    noticeReady = true; noticeScene = home.scene; noticeTimer = home.timer;
    noticeCooling = home.cooling; noticeLoad = home.loadSwitch;
}

void HomeAutomation_DismissNotice(void) { noticeText[0U] = '\0'; }

bool HomeAutomation_ApplyNotice(DisplayService_View_t *view, uint32_t nowMs)
{
    char line[21U];
    if (!noticeText[0U] || Reached(nowMs, noticeUntilMs)) { HomeAutomation_DismissNotice(); return false; }
    if (view == NULL) { return false; }
    DisplayService_ViewClear(view);
    (void)DisplayService_ViewSetLine(view, 0U, "SMART HOME");
    (void)DisplayService_ViewSetLine(view, 2U, noticeText);
    (void)DisplayService_ViewSetLine(view, 5U, noticeDetail);
    if (home.scene == HOME_SCENE_KTV) {
        (void)snprintf(line, sizeof(line), "KTV MASTER: %u%%", (unsigned int)home.ktvBrightness);
    } else if (home.timer == HOME_TIMER_RUNNING || home.timer == HOME_TIMER_PAUSED) {
        (void)snprintf(line, sizeof(line), "STUDY %02lu:%02lu", (unsigned long)(home.timerSeconds / 60UL),
            (unsigned long)(home.timerSeconds % 60UL));
    } else { (void)snprintf(line, sizeof(line), "AC:%s TV:%s ICE:ON", home.cooling ? "ON" : "OFF", home.loadSwitch ? "ON" : "OFF"); }
    (void)DisplayService_ViewSetLine(view, 6U, line);
    (void)DisplayService_ViewSetLine(view, 7U, "3s RETURN TO PAGE");
    return true;
}

static uint8_t OpenPercent(ServoService_Device_t device)
{
    uint16_t angle = ServoService_GetCurrentAngle(device);
    if (angle >= 90U) { return 100U; }
    return (uint8_t)((angle * 100U + 45U) / 90U);
}

static void SetServo(ServoService_Device_t device, uint8_t percent)
{
    uint8_t angle = (uint8_t)(((uint16_t)percent * 90U + 50U) / 100U);
    if (ServoService_GetTargetAngle(device) != angle) {
        ServoService_SetTarget(device, angle);
    }
}

static bool SoftwareClosed(ServoService_Device_t device)
{
    return ((ServoService_GetCurrentAngle(device) == 0U) &&
            (ServoService_GetTargetAngle(device) == 0U) && !ServoService_IsMoving(device));
}

static uint32_t ManualRemaining(Manual_t *manual, uint32_t nowMs)
{
    if (manual->active && Reached(nowMs, manual->untilMs)) { manual->active = false; }
    return manual->active ? (manual->untilMs - nowMs) : 0UL;
}

static void SetManual(Manual_t *manual, uint8_t value, uint32_t nowMs)
{
    manual->active = true;
    manual->value = value;
    manual->untilMs = nowMs + HOME_MANUAL_MS;
}

static void ClearManuals(void)
{
    manualDoor.active = manualWindow.active = manualCurtain.active = false;
    manualLiving.active = manualBedroom.active = manualHall.active = false;
}

static void UpdateTimer(uint32_t nowMs)
{
    uint32_t elapsed = nowMs - previousTaskMs;
    previousTaskMs = nowMs;
    if (home.timer == HOME_TIMER_RUNNING) {
        if (elapsed >= timerRemainingMs) {
            timerRemainingMs = 0UL;
            home.timer = HOME_TIMER_DONE;
            timerReminder = true;
        } else { timerRemainingMs -= elapsed; }
    }
    home.timerSeconds = (timerRemainingMs + 999UL) / 1000UL;
}

static void UpdateInputs(uint32_t nowMs)
{
    float temperature = 0.0f;
    uint8_t pot;
    HomeInputs_GetSnapshot(nowMs, &home.inputs);
    home.tempValid = TemperatureService_IsHealthy() &&
        ((uint32_t)(nowMs - TemperatureService_GetLastUpdateMs()) <= HOME_TEMP_MAX_AGE_MS) &&
        TemperatureService_GetCelsius(&temperature);
    if (home.tempValid) {
        home.temp10 = (int16_t)(temperature * 10.0f + ((temperature >= 0.0f) ? 0.5f : -0.5f));
    }
    home.setpoint10 = 315;
    if (((uint32_t)(nowMs - PotentiometerService_GetLastUpdateMs()) <= HOME_POT_MAX_AGE_MS) &&
        PotentiometerService_GetPercent(&pot)) {
        home.setpoint10 = (int16_t)(200U + ((uint16_t)pot * 120U + 50U) / 100U);
    }
    home.comfort = !home.inputs.humidityValid ? 0U :
        ((home.inputs.humidity10 < 400U) ? 1U : ((home.inputs.humidity10 > 600U) ? 3U : 2U));
}

static void UpdateCurtain(uint32_t nowMs)
{
    bool candidate = curtainShaded;
    if (!home.inputs.luxValid) { curtainWaiting = false; return; }
    if (home.inputs.lux >= HOME_CURTAIN_CLOSE_LUX) { candidate = true; }
    else if (home.inputs.lux <= HOME_CURTAIN_OPEN_LUX) { candidate = false; }
    if (candidate == curtainShaded) { curtainWaiting = false; return; }
    if (!curtainWaiting || (candidate != curtainCandidate)) {
        curtainCandidate = candidate;
        curtainCandidateMs = nowMs;
        curtainWaiting = true;
    } else if ((uint32_t)(nowMs - curtainCandidateMs) >= HOME_CURTAIN_STABLE_MS) {
        curtainShaded = candidate;
        curtainWaiting = false;
    }
}

static void UpdateRGB(void)
{
    uint8_t rgb;
    /* Hand-warming demo: green <24.0 C, amber >=24.0 C, red >=24.8 C.
     * A 0.2 C falling hysteresis keeps boundary noise from changing colours. */
    if (!home.tempValid) { rgb = 0U; }
    else if (home.temp10 >= 248 || ((previousRGB == 3U) && (home.temp10 > 246))) { rgb = 3U; }
    else if (home.temp10 >= 240 || ((previousRGB >= 2U) && (previousRGB <= 3U) &&
                                  (home.temp10 > 238))) { rgb = 2U; }
    else { rgb = 1U; }
    if (rgb == previousRGB) { return; }
    previousRGB = rgb;
    if (rgb == 0U) { RGBLEDService_Off(); }
    else if (rgb == 1U) { RGBLEDService_SetColor(0U, 100U, 0U); }
    else if (rgb == 2U) { RGBLEDService_SetColor(100U, 65U, 0U); }
    else { RGBLEDService_Breathe(100U, 0U, 0U, 2000UL); }
}

static void RainbowPixel(uint8_t index, uint8_t phase, uint8_t level)
{
    uint8_t r, g, b, ramp;
    if (phase < 85U) {
        ramp = phase * 3U; r = 255U - ramp; g = ramp; b = 0U;
    } else if (phase < 170U) {
        ramp = (phase - 85U) * 3U; r = 0U; g = 255U - ramp; b = ramp;
    } else {
        ramp = (phase - 170U) * 3U; r = ramp; g = 0U; b = 255U - ramp;
    }
    WS2812BService_SetPixel(index, (uint8_t)((uint16_t)r * level / 100U),
        (uint8_t)((uint16_t)g * level / 100U), (uint8_t)((uint16_t)b * level / 100U));
}

static void UpdateLighting(bool present, uint32_t nowMs)
{
    uint8_t base = !home.inputs.luxValid ? 35U :
        ((home.inputs.lux < 100UL) ? 65U : ((home.inputs.lux < 500UL) ? 35U : 0U));
    uint8_t i, level, phase = 0U, beat = 0U, lead = 0U;
    uint16_t triangle = 0U;
    uint32_t elapsed = nowMs - lightEffectStartMs;
    bool study = home.scene != HOME_SCENE_KTV && !IsAway() &&
        (home.timer == HOME_TIMER_RUNNING || home.timer == HOME_TIMER_PAUSED);
    home.living = home.bedroom = home.hall = 0U;
    if (home.scene == HOME_SCENE_HOME && present) {
        home.living = base; home.bedroom = base; home.hall = base / 2U;
    } else if (home.scene == HOME_SCENE_KTV) {
        home.living = home.bedroom = home.hall = home.ktvBrightness;
    } else if (home.scene == HOME_SCENE_MOVIE) { home.living = 5U; }
    else if ((home.scene == HOME_SCENE_SLEEP) && home.nightActive) { home.hall = 10U; }
    if (home.scene != HOME_SCENE_LONG_AWAY && home.scene != HOME_SCENE_KTV) {
        if (manualLiving.active) { home.living = manualLiving.value; }
        if (manualBedroom.active) { home.bedroom = manualBedroom.value; }
        if (manualHall.active) { home.hall = manualHall.value; }
    }
    if (home.scene == HOME_SCENE_KTV) {
        if (home.lightEffect == HOME_LIGHT_PARTY) {
            beat = (uint8_t)(elapsed / 180UL);
            lead = (uint8_t)((beat * 5U) & 7U);
        } else { phase = (uint8_t)(elapsed / 24UL); }
        if (home.lightEffect == HOME_LIGHT_PULSE) {
            triangle = (uint16_t)(elapsed % 2400UL);
            if (triangle > 1200U) { triangle = 2400U - triangle; }
        }
    }
    /* KTV uses one master; no hidden brightness floors or room overrides. */
    for (i = 0U; i < 8U; i++) {
        if (study && i == 7U) { continue; }
        level = (i < 3U) ? home.living : ((i < 6U) ? home.bedroom : home.hall);
        if (home.scene == HOME_SCENE_KTV && home.lightEffect != HOME_LIGHT_WARM) {
            if (home.lightEffect == HOME_LIGHT_PULSE) {
                level = (uint8_t)((uint16_t)level * (10U + (uint32_t)triangle * 90UL / 1200UL) / 100U);
            } else if (home.lightEffect == HOME_LIGHT_PARTY) {
                if (i != lead && i != ((lead + 3U) & 7U) && i != ((lead + 5U) & 7U)) { level = 0U; }
            }
            RainbowPixel(i, home.lightEffect == HOME_LIGHT_PARTY ?
                (uint8_t)(beat * 53U + i * 71U) : (uint8_t)(phase + i * 32U), level);
        } else {
            WS2812BService_SetPixel(i, (uint8_t)((uint16_t)level * 255U / 100U),
                (uint8_t)((uint16_t)level * 210U / 100U),
                (uint8_t)((uint16_t)level * 150U / 100U));
        }
    }
    /* One dedicated study pixel, leaving the other seven room pixels untouched. */
    if (study) {
        triangle = (uint16_t)((nowMs - studyStartMs) % 4000UL);
        if (triangle > 2000U) { triangle = 4000U - triangle; }
        level = home.timer == HOME_TIMER_PAUSED ? 20U : (uint8_t)(10U + triangle / 40U);
        level = (uint8_t)((uint16_t)level * 255U / 100U);
        WS2812BService_SetPixel(7U, level, level, level);
    }
}

static void UpdateAlerts(uint32_t nowMs)
{
    bool water = home.inputs.waterValid && home.inputs.waterWet;
    if (waterSoundOwned && (!MusicService_IsPlaying() ||
        (g_musicServiceDebug.playCount != waterSoundPlayCount))) { waterSoundOwned = false; }
    if (water && !previousWaterWet) {
        home.muted = false;
        nextWaterSoundMs = nowMs;
    }
    /* A failed/unknown read must not silently clear an existing alarm or its mute. */
    if (home.inputs.waterValid && !home.inputs.waterWet) {
        if (waterSoundOwned) { MusicService_Stop(); waterSoundOwned = false; }
        home.muted = false;
        previousWaterWet = false;
    } else if (water) { previousWaterWet = true; }
    if (!MusicService_IsPlaying()) {
        if (previousWaterWet && !home.muted && Reached(nowMs, nextWaterSoundMs)) {
            if (!IsQuiet()) {
                if (MusicService_PlayMelody(alarmNotes, 3U, false) == MUSIC_SERVICE_OK) {
                    waterSoundOwned = true;
                    waterSoundPlayCount = g_musicServiceDebug.playCount;
                }
            }
            nextWaterSoundMs = nowMs + HOME_ALARM_PERIOD_MS;
        } else if (timerReminder) {
            if (!IsQuiet()) { (void)MusicService_PlayMelody(timerNotes, 2U, false); }
            timerReminder = false;
        } else if (IsAway() && !home.awayCheckOk && !awayAlarmSent &&
                   ((uint32_t)(nowMs - awayCheckStartMs) >= HOME_AWAY_CHECK_MS)) {
            (void)MusicService_PlayMelody(alarmNotes, 3U, false);
            awayAlarmSent = true;
        }
    }
    if (!IsAway() || home.awayCheckOk) { awayAlarmSent = false; }
    home.waterAlarm = previousWaterWet;
    LEDService_Set(LED_SERVICE_LED4_MASK, previousWaterWet);
    LEDService_Set(LED_SERVICE_LED5_MASK,
        (home.timer == HOME_TIMER_RUNNING) ||
        ((home.timer == HOME_TIMER_DONE) && (((nowMs / 500UL) & 1UL) != 0UL)));
}

void HomeAutomation_Initialize(uint32_t nowMs)
{
    memset(&home, 0, sizeof(home));
    ClearManuals();
    manualDemand.active = false;
    home.scene = HOME_SCENE_HOME;
    home.loadKeep = home.loadSwitch = true;
    home.setpoint10 = 315;
    home.ktvBrightness = 50U;
    autoDemand = curtainShaded = curtainCandidate = curtainWaiting = false;
    previousWaterWet = awayAlarmSent = timerReminder = false;
    waterSoundOwned = false;
    previousTaskMs = awayCheckStartMs = nowMs;
    timerRemainingMs = 0UL;
    nightUntilMs = nowMs;
    previousRGB = 255U;
    lightEffectStartMs = nowMs;
    studyStartMs = nowMs;
    localControl = CONTROL_SCENE;
    localTimerSetting = 25UL * 60UL;
    localResult = "SELECT A DEVICE";
    noticeReady = false; HomeAutomation_DismissNotice();
    ServoService_SetMoveStep(SERVO_SERVICE_DEVICE_DOOR, 3U);
    ServoService_SetMoveStep(SERVO_SERVICE_DEVICE_WINDOW, 3U);
    ServoService_SetMoveStep(SERVO_SERVICE_DEVICE_VENT, 3U);
    ServoService_SetMoveStep(SERVO_SERVICE_DEVICE_CURTAIN, 3U);
    WS2812BService_SetBrightness(100U);
    HomeAutomation_Task(nowMs);
    Notice("FRIDGE POWER ON", "FRIDGE POWER: ON", nowMs);
}

void HomeAutomation_Task(uint32_t nowMs)
{
    bool present;
    uint8_t windowTarget, doorTarget, curtainTarget;
    UpdateTimer(nowMs);
    UpdateInputs(nowMs);
    if (!home.inputs.rainValid || home.inputs.rainWet || home.scene == HOME_SCENE_LONG_AWAY) {
        manualWindow.active = false;
    }
    home.doorManualMs = ManualRemaining(&manualDoor, nowMs);
    home.windowManualMs = ManualRemaining(&manualWindow, nowMs);
    home.curtainManualMs = ManualRemaining(&manualCurtain, nowMs);
    home.livingManualMs = ManualRemaining(&manualLiving, nowMs);
    home.bedroomManualMs = ManualRemaining(&manualBedroom, nowMs);
    home.hallManualMs = ManualRemaining(&manualHall, nowMs);
    home.doorManual = manualDoor.active; home.windowManual = manualWindow.active;
    home.curtainManual = manualCurtain.active; home.livingManual = manualLiving.active;
    home.bedroomManual = manualBedroom.active; home.hallManual = manualHall.active;
    home.demandManual = manualDemand.active;
    if (home.nightActive && Reached(nowMs, nightUntilMs)) { home.nightActive = false; }
    present = ProximityService_IsHealthy() && ProximityService_IsPresent() &&
        ((uint32_t)(nowMs - ProximityService_GetLastUpdateMs()) <= HOME_PRESENCE_MAX_AGE_MS);
    if (!home.tempValid) { autoDemand = false; }
    else if (home.temp10 >= home.setpoint10 + 5) { autoDemand = true; }
    else if (home.temp10 <= home.setpoint10 - 5) { autoDemand = false; }
    home.demand = manualDemand.active ? (manualDemand.value != 0U) : autoDemand;
    doorTarget = ((home.scene == HOME_SCENE_HOME) && present) ? 100U : 0U;
    if (manualDoor.active) { doorTarget = manualDoor.value; }
    if (IsAway()) { doorTarget = 0U; }
    windowTarget = (home.tempValid && (home.temp10 >= 300) && !home.demand &&
        ((home.scene == HOME_SCENE_HOME) || (home.scene == HOME_SCENE_AWAY))) ? 100U : 0U;
    if (manualWindow.active) { windowTarget = manualWindow.value; }
    /* Unknown rain input is a close/hold-safe state, never permission to open. */
    if (!home.inputs.rainValid || home.inputs.rainWet || home.scene == HOME_SCENE_LONG_AWAY) {
        windowTarget = 0U;
    }
    UpdateCurtain(nowMs);
    curtainTarget = (curtainShaded || IsQuiet() || (home.scene == HOME_SCENE_LONG_AWAY) ||
                     home.scene == HOME_SCENE_KTV) ? 0U : 100U;
    if (manualCurtain.active) { curtainTarget = manualCurtain.value; }
    SetServo(SERVO_SERVICE_DEVICE_DOOR, doorTarget);
    SetServo(SERVO_SERVICE_DEVICE_WINDOW, windowTarget);
    SetServo(SERVO_SERVICE_DEVICE_CURTAIN, curtainTarget);
    home.door = SoftwareClosed(SERVO_SERVICE_DEVICE_DOOR) ? 1U : 0U;
    home.window = SoftwareClosed(SERVO_SERVICE_DEVICE_WINDOW) ? 1U : 0U;
    home.doorTarget = doorTarget; home.windowTarget = windowTarget;
    home.curtain = OpenPercent(SERVO_SERVICE_DEVICE_CURTAIN);
    home.cooling = !IsAway() && (manualDemand.active ? (manualDemand.value != 0U) :
        (home.tempValid && home.demand && (home.window == 1U) && (windowTarget == 0U)));
    SetServo(SERVO_SERVICE_DEVICE_VENT, home.cooling ? 100U : 0U);
    home.vent = OpenPercent(SERVO_SERVICE_DEVICE_VENT);
    home.awayCheckOk = !IsAway() || ((home.door == 1U) &&
        ((home.scene != HOME_SCENE_LONG_AWAY) || (home.window == 1U)));
    if (home.scene == HOME_SCENE_LONG_AWAY) { home.loadSwitch = false; }
    home.loadKeep = true;
    UpdateLighting(present, nowMs);
    LEDService_Set(LED_SERVICE_LED0_MASK, present);
    LEDService_Set(LED_SERVICE_LED1_MASK, home.loadSwitch);
    LEDService_Set(LED_SERVICE_LED2_MASK, home.loadKeep);
    LEDService_Set(LED_SERVICE_LED3_MASK, home.cooling);
    UpdateAlerts(nowMs);
    UpdateRGB();
    UpdateNotices(nowMs);
}

const HomeAutomation_State_t *HomeAutomation_GetState(void) { return &home; }

const char *HomeAutomation_SceneName(HomeScene_t scene)
{
    switch (scene) {
        case HOME_SCENE_AWAY: return "away";
        case HOME_SCENE_LONG_AWAY: return "long_away";
        case HOME_SCENE_SLEEP: return "sleep";
        case HOME_SCENE_MOVIE: return "movie";
        case HOME_SCENE_KTV: return "ktv";
        default: return "home";
    }
}

const char *HomeAutomation_TimerName(HomeTimer_t timer)
{
    switch (timer) {
        case HOME_TIMER_RUNNING: return "running";
        case HOME_TIMER_PAUSED: return "paused";
        case HOME_TIMER_DONE: return "done";
        default: return "idle";
    }
}

static bool Number(const char *text, uint32_t max, uint32_t *out)
{
    uint32_t value = 0UL;
    uint8_t digit;
    if ((text == NULL) || (*text == '\0')) { return false; }
    while (*text != '\0') {
        if ((*text < '0') || (*text > '9')) { return false; }
        digit = (uint8_t)(*text++ - '0');
        if ((value > max / 10UL) || ((value == max / 10UL) && (digit > max % 10UL))) {
            return false;
        }
        value = value * 10UL + digit;
    }
    *out = value;
    return true;
}

static bool Reject(const char **reason, const char *text)
{ if (reason != NULL) { *reason = text; } return false; }

bool HomeAutomation_Command(const char *action, const char *value,
                            uint32_t nowMs, const char **reason)
{
    uint32_t number;
    Manual_t *manual = NULL;
    HomeScene_t scene;
    if (reason != NULL) { *reason = "OK"; }
    if ((action == NULL) || (value == NULL)) { return Reject(reason, "INVALID_VALUE"); }
    HomeAutomation_Task(nowMs);
    if (strcmp(action, "scene") == 0) {
        for (scene = HOME_SCENE_HOME; scene <= HOME_SCENE_KTV; scene++) {
            if (strcmp(value, HomeAutomation_SceneName(scene)) == 0) { break; }
        }
        if (scene > HOME_SCENE_KTV) { return Reject(reason, "INVALID_VALUE"); }
        home.scene = scene;
        if (scene == HOME_SCENE_KTV) { localControl = CONTROL_EFFECT; }
        else if (localControl == CONTROL_EFFECT || localControl == CONTROL_KTV_LEVEL) { localControl = CONTROL_SCENE; }
        ClearManuals();
        if (IsAway()) { manualDemand.active = false; }
        home.lightEffect = scene == HOME_SCENE_KTV ? HOME_LIGHT_RAINBOW : HOME_LIGHT_WARM;
        lightEffectStartMs = nowMs;
        home.nightActive = false;
        home.loadSwitch = !IsAway() && (scene != HOME_SCENE_SLEEP);
        awayCheckStartMs = nowMs;
        awayAlarmSent = false;
        if (IsQuiet()) { MusicService_Stop(); }
    } else if (strcmp(action, "light_effect") == 0) {
        if (home.scene != HOME_SCENE_KTV) { return Reject(reason, "SCENE"); }
        if (strcmp(value, "warm") == 0) { home.lightEffect = HOME_LIGHT_WARM; }
        else if (strcmp(value, "rainbow") == 0) { home.lightEffect = HOME_LIGHT_RAINBOW; }
        else if (strcmp(value, "pulse") == 0) { home.lightEffect = HOME_LIGHT_PULSE; }
        else if (strcmp(value, "party") == 0) { home.lightEffect = HOME_LIGHT_PARTY; }
        else { return Reject(reason, "INVALID_VALUE"); }
        lightEffectStartMs = nowMs;
    } else if (strcmp(action, "ktv_brightness") == 0) {
        if (home.scene != HOME_SCENE_KTV) { return Reject(reason, "SCENE"); }
        if (!Number(value, 100UL, &number)) { return Reject(reason, "INVALID_VALUE"); }
        home.ktvBrightness = (uint8_t)number;
    } else if ((strcmp(action, "door") == 0) || (strcmp(action, "window") == 0) ||
               (strcmp(action, "curtain") == 0)) {
        manual = (strcmp(action, "door") == 0) ? &manualDoor :
            ((strcmp(action, "window") == 0) ? &manualWindow : &manualCurtain);
        if (strcmp(value, "auto") == 0) { manual->active = false; }
        else {
            if (strcmp(value, "open") == 0) { number = 100UL; }
            else if (strcmp(value, "close") == 0) { number = 0UL; }
            else { return Reject(reason, "INVALID_VALUE"); }
            if ((manual == &manualDoor) && (number != 0UL) && IsAway()) {
                return Reject(reason, (home.scene == HOME_SCENE_LONG_AWAY) ? "LONG_AWAY" : "AWAY");
            }
            if ((manual == &manualWindow) && (number != 0UL)) {
                if (home.scene == HOME_SCENE_LONG_AWAY) { return Reject(reason, "LONG_AWAY"); }
                if (!home.inputs.rainValid) { return Reject(reason, "INPUT_UNAVAILABLE"); }
                if (home.inputs.rainWet) { return Reject(reason, "RAIN"); }
            }
            SetManual(manual, (uint8_t)number, nowMs);
        }
    } else if ((strcmp(action, "living") == 0) || (strcmp(action, "bedroom") == 0) ||
               (strcmp(action, "hall") == 0) || (strcmp(action, "demand") == 0)) {
        manual = (strcmp(action, "living") == 0) ? &manualLiving :
            ((strcmp(action, "bedroom") == 0) ? &manualBedroom :
            ((strcmp(action, "hall") == 0) ? &manualHall : &manualDemand));
        if (manual != &manualDemand && home.scene == HOME_SCENE_KTV) { return Reject(reason, "SCENE"); }
        if (strcmp(value, "auto") == 0) { manual->active = false; }
        else {
            if (!Number(value, (manual == &manualDemand) ? 1UL : 100UL, &number)) {
                return Reject(reason, "INVALID_VALUE");
            }
            if ((manual != &manualDemand) && (home.scene == HOME_SCENE_LONG_AWAY) && (number != 0UL)) {
                return Reject(reason, "LONG_AWAY");
            }
            if (manual == &manualDemand) {
                if (number != 0UL && IsAway()) { return Reject(reason, "AWAY"); }
                manualDemand.active = true; manualDemand.value = (uint8_t)number;
            } else { SetManual(manual, (uint8_t)number, nowMs); }
        }
    } else if (strcmp(action, "load_switch") == 0) {
        if (!Number(value, 1UL, &number)) { return Reject(reason, "INVALID_VALUE"); }
        if ((home.scene == HOME_SCENE_LONG_AWAY) && (number != 0UL)) { return Reject(reason, "LONG_AWAY"); }
        home.loadSwitch = (number != 0UL);
    } else if (strcmp(action, "mute") == 0) {
        if (strcmp(value, "1") != 0) { return Reject(reason, "INVALID_VALUE"); }
        if (!home.waterAlarm) { return Reject(reason, "NO_WATER_ALARM"); }
        home.muted = true;
        if (waterSoundOwned) { MusicService_Stop(); waterSoundOwned = false; }
    } else if (strcmp(action, "night") == 0) {
        if ((strcmp(value, "1") != 0) || (home.scene != HOME_SCENE_SLEEP)) {
            return Reject(reason, "INVALID_VALUE");
        }
        home.nightActive = true;
        nightUntilMs = nowMs + HOME_NIGHT_MS;
    } else if (strcmp(action, "timer_start") == 0) {
        if (!Number(value, 86400UL, &number) || (number == 0UL)) {
            return Reject(reason, "INVALID_VALUE");
        }
        timerRemainingMs = number * 1000UL;
        studyStartMs = nowMs;
        home.timer = HOME_TIMER_RUNNING;
        timerReminder = false;
    } else if (strcmp(action, "timer_pause") == 0) {
        if (strcmp(value, "1") != 0) { return Reject(reason, "INVALID_VALUE"); }
        if (home.timer != HOME_TIMER_RUNNING) { return Reject(reason, "TIMER_STATE"); }
        home.timer = HOME_TIMER_PAUSED;
    } else if (strcmp(action, "timer_resume") == 0) {
        if (strcmp(value, "1") != 0) { return Reject(reason, "INVALID_VALUE"); }
        if (home.timer != HOME_TIMER_PAUSED) { return Reject(reason, "TIMER_STATE"); }
        home.timer = HOME_TIMER_RUNNING;
    } else if (strcmp(action, "timer_stop") == 0) {
        if (strcmp(value, "1") != 0) { return Reject(reason, "INVALID_VALUE"); }
        timerRemainingMs = 0UL;
        home.timer = HOME_TIMER_IDLE;
        timerReminder = false;
    } else { return Reject(reason, "UNSUPPORTED"); }
    HomeAutomation_Task(nowMs);
    if (strcmp(action, "light_effect") == 0) { EffectNotice(nowMs); }
    else if (strcmp(action, "ktv_brightness") == 0) {
        Notice(home.ktvBrightness ? "LIGHTS ON" : "LIGHTS OFF", "KTV MASTER BRIGHTNESS", nowMs);
    } else if (strcmp(action, "demand") == 0) {
        Notice(strcmp(value, "auto") == 0 ? "AUTO TEMPERATURE" : home.cooling ? "AIR CONDITIONER ON" : "AIR CONDITIONER OFF",
            home.demandManual ? "MANUAL AC HOLD" : "AUTOMATIC AC", nowMs);
    } else if (strcmp(action, "timer_resume") == 0) { Notice("STUDY RESUMED", "STUDY TIMER", nowMs); }
    else if (strcmp(action, "timer_start") == 0 || strcmp(action, "timer_pause") == 0 || strcmp(action, "timer_stop") == 0) { TimerNotice(nowMs); }
    else if (strcmp(action, "load_switch") == 0) { Notice(home.loadSwitch ? "TV ON" : "TV OFF", "FRIDGE POWER: ON", nowMs); }
    else if (strcmp(action, "door") == 0 || strcmp(action, "window") == 0 || strcmp(action, "curtain") == 0) {
        Notice(action, value, nowMs);
    }
    else if (strcmp(action, "living") == 0 || strcmp(action, "bedroom") == 0 || strcmp(action, "hall") == 0) { Notice("LIGHT", action, nowMs); }
    else if (strcmp(action, "mute") == 0) { Notice("MUTED", "WATER ALARM SILENCED", nowMs); }
    return true;
}

static void LocalCommand(const char *action, const char *value, uint32_t nowMs)
{
    const char *reason;
    localResult = HomeAutomation_Command(action, value, nowMs, &reason) ? "OK" : reason;
    if (strcmp(localResult, "OK") != 0) { Notice("HOLD", reason, nowMs); }
}

static void LocalTimerToggle(uint32_t nowMs)
{
    char value[12U];
    if (home.timer == HOME_TIMER_RUNNING) { LocalCommand("timer_pause", "1", nowMs); }
    else if (home.timer == HOME_TIMER_PAUSED) { LocalCommand("timer_resume", "1", nowMs); }
    else {
        (void)snprintf(value, sizeof(value), "%lu", (unsigned long)localTimerSetting);
        LocalCommand("timer_start", value, nowMs);
    }
}

static bool LocalAvailable(uint8_t control)
{
    if (home.scene == HOME_SCENE_KTV) {
        return control < CONTROL_LIVING || control > CONTROL_HALL;
    }
    return control != CONTROL_EFFECT && control != CONTROL_KTV_LEVEL;
}

void HomeAutomation_HandleButton(const ButtonService_Event_t *event, uint32_t nowMs)
{
    char value[12U];
    const char *action;
    uint8_t percent;
    int8_t direction;
    if (event == NULL) { return; }
    if (event->button == BUTTON_ID_SW2) {
        if (event->type == BUTTON_EVENT_LONG_PRESS) { LocalCommand("timer_stop", "1", nowMs); }
        else if (event->type == BUTTON_EVENT_SHORT_PRESS) {
            if (home.waterAlarm) { LocalCommand("mute", "1", nowMs); }
            else { LocalTimerToggle(nowMs); }
        }
        return;
    }
    if (event->type == BUTTON_EVENT_LONG_PRESS) {
        if (event->button == BUTTON_ID_JOY_PUSH) {
            if (localControl == CONTROL_TIMER) { LocalCommand("timer_stop", "1", nowMs); }
            else if (localControl == CONTROL_EFFECT) { LocalCommand("light_effect", "rainbow", nowMs); }
            else if (localControl == CONTROL_KTV_LEVEL) { LocalCommand("ktv_brightness", "50", nowMs); }
            else if (((localControl >= CONTROL_WINDOW) && (localControl <= CONTROL_HALL)) ||
                     (localControl == CONTROL_DEMAND)) {
                action = (localControl == CONTROL_WINDOW) ? "window" :
                    ((localControl == CONTROL_DOOR) ? "door" :
                    ((localControl == CONTROL_CURTAIN) ? "curtain" :
                    ((localControl == CONTROL_LIVING) ? "living" :
                    ((localControl == CONTROL_BEDROOM) ? "bedroom" :
                    ((localControl == CONTROL_HALL) ? "hall" : "demand")))));
                LocalCommand(action, "auto", nowMs);
            }
        }
        return;
    }
    if (event->type != BUTTON_EVENT_SHORT_PRESS) { return; }
    if (event->button == BUTTON_ID_JOY_LEFT || event->button == BUTTON_ID_JOY_RIGHT) {
        HomeAutomation_DismissNotice();
        do {
            localControl = event->button == BUTTON_ID_JOY_LEFT ?
                ((localControl == 0U) ? CONTROL_COUNT - 1U : localControl - 1U) :
                (uint8_t)((localControl + 1U) % CONTROL_COUNT);
        } while (!LocalAvailable(localControl));
        localResult = "UP/DN SET PUSH ACT"; return;
    }
    direction = (event->button == BUTTON_ID_JOY_DOWN) ? -1 : 1;
    if ((event->button != BUTTON_ID_JOY_UP) && (event->button != BUTTON_ID_JOY_DOWN) &&
        (event->button != BUTTON_ID_JOY_PUSH)) { return; }
    if (localControl == CONTROL_SCENE) {
        percent = (uint8_t)home.scene;
        percent = (direction > 0) ? (uint8_t)((percent + 1U) % 6U) :
            ((percent == 0U) ? 5U : percent - 1U);
        LocalCommand("scene", HomeAutomation_SceneName((HomeScene_t)percent), nowMs);
    } else if ((localControl >= CONTROL_WINDOW) && (localControl <= CONTROL_CURTAIN)) {
        action = (localControl == CONTROL_WINDOW) ? "window" :
            ((localControl == CONTROL_DOOR) ? "door" : "curtain");
        percent = (localControl == CONTROL_WINDOW) ? home.windowTarget :
            ((localControl == CONTROL_DOOR) ? home.doorTarget : home.curtain);
        LocalCommand(action, (event->button == BUTTON_ID_JOY_PUSH) ?
            ((percent > 0U) ? "close" : "open") : ((direction > 0) ? "open" : "close"), nowMs);
    } else if (((localControl >= CONTROL_LIVING) && (localControl <= CONTROL_HALL)) || localControl == CONTROL_KTV_LEVEL) {
        action = (localControl == CONTROL_LIVING) ? "living" :
            ((localControl == CONTROL_BEDROOM) ? "bedroom" : "hall");
        if (home.scene == HOME_SCENE_KTV) { action = "ktv_brightness"; }
        percent = home.scene == HOME_SCENE_KTV ? home.ktvBrightness : (localControl == CONTROL_LIVING) ? home.living :
            ((localControl == CONTROL_BEDROOM) ? home.bedroom : home.hall);
        if (event->button == BUTTON_ID_JOY_PUSH) { percent = (percent > 0U) ? 0U : 50U; }
        else if (direction > 0) { percent = (percent >= 90U) ? 100U : percent + 10U; }
        else { percent = (percent <= 10U) ? 0U : percent - 10U; }
        (void)snprintf(value, sizeof(value), "%u", (unsigned int)percent);
        LocalCommand(action, value, nowMs);
    } else if (localControl == CONTROL_LOAD) {
        LocalCommand("load_switch", event->button == BUTTON_ID_JOY_PUSH ? (home.loadSwitch ? "0" : "1") : (direction > 0 ? "1" : "0"), nowMs);
    } else if (localControl == CONTROL_DEMAND) {
        LocalCommand("demand", event->button == BUTTON_ID_JOY_PUSH ? (home.cooling ? "0" : "1") : (direction > 0 ? "1" : "0"), nowMs);
    } else if (localControl == CONTROL_EFFECT) {
        percent = (uint8_t)home.lightEffect;
        percent = direction > 0 ? ((percent >= HOME_LIGHT_PARTY) ? HOME_LIGHT_RAINBOW : percent + 1U) :
            ((percent <= HOME_LIGHT_RAINBOW) ? HOME_LIGHT_PARTY : percent - 1U);
        LocalCommand("light_effect", percent == HOME_LIGHT_RAINBOW ? "rainbow" : percent == HOME_LIGHT_PULSE ? "pulse" : "party", nowMs);
    } else if (localControl == CONTROL_NIGHT) { LocalCommand("night", "1", nowMs); }
    else if (localControl == CONTROL_TIMER) {
        if (event->button == BUTTON_ID_JOY_PUSH) {
            LocalTimerToggle(nowMs);
        } else if ((home.timer != HOME_TIMER_RUNNING) && (home.timer != HOME_TIMER_PAUSED)) {
            if (direction > 0) { if (localTimerSetting <= 86340UL) { localTimerSetting += 60UL; } }
            else if (localTimerSetting > 60UL) { localTimerSetting -= 60UL; }
        }
    }
}

void HomeAutomation_BuildView(DisplayService_View_t *view)
{
    char line[21U];
    const char *name;
    uint32_t manualMs = 0UL;
    if (view == NULL) { return; }
    DisplayService_ViewClear(view);
    (void)snprintf(line, sizeof(line), "HOME %-9s", HomeAutomation_SceneName(home.scene));
    (void)DisplayService_ViewSetLine(view, 0U, line);
    if (home.waterAlarm) { name = home.muted ? "WATER: WET MUTED" : "WATER: WET ALARM"; }
    else if (!home.inputs.waterValid) { name = "WATER: INPUT UNKNOWN"; }
    else if (!home.inputs.rainValid) { name = "RAIN UNKNOWN: SHUT"; }
    else if (home.inputs.rainWet) { name = "RAIN WET: WINDOW SHUT"; }
    else { name = home.awayCheckOk ? "SW CHECK: OK" : "SW CHECK: MOVING"; }
    (void)DisplayService_ViewSetLine(view, 1U, name);
    if (home.tempValid) {
        (void)snprintf(line, sizeof(line), "T:%s%u.%u SET:%d.%u", home.temp10 < 0 ? "-" : "",
            (unsigned int)((home.temp10 < 0 ? -home.temp10 : home.temp10) / 10),
            (unsigned int)((home.temp10 < 0 ? -home.temp10 : home.temp10) % 10),
            (int)(home.setpoint10 / 10), (unsigned int)(home.setpoint10 % 10));
    } else { (void)snprintf(line, sizeof(line), "TEMP UNKNOWN AC:%s", home.cooling ? "ON" : "OFF"); }
    (void)DisplayService_ViewSetLine(view, 2U, line);
    if (home.inputs.humidityValid) {
        (void)snprintf(line, sizeof(line), "RH:%u.%u%% %s", (unsigned int)(home.inputs.humidity10 / 10U),
            (unsigned int)(home.inputs.humidity10 % 10U), (home.comfort == 1U) ? "DRY" :
            ((home.comfort == 3U) ? "HUMID" : "OK"));
    } else { (void)snprintf(line, sizeof(line), "RH: SENSOR UNKNOWN"); }
    (void)DisplayService_ViewSetLine(view, 3U, line);
    switch (localControl) {
        case CONTROL_SCENE: (void)snprintf(line, sizeof(line), "SCENE %s", HomeAutomation_SceneName(home.scene)); break;
        case CONTROL_WINDOW: (void)snprintf(line, sizeof(line), "WINDOW %u%%", (unsigned int)home.windowTarget); manualMs = home.windowManualMs; break;
        case CONTROL_DOOR: (void)snprintf(line, sizeof(line), "DOOR %u%%", (unsigned int)home.doorTarget); manualMs = home.doorManualMs; break;
        case CONTROL_CURTAIN: (void)snprintf(line, sizeof(line), "CURTAIN %u%%", (unsigned int)home.curtain); manualMs = home.curtainManualMs; break;
        case CONTROL_LIVING: (void)snprintf(line, sizeof(line), "LIVING %u%%", (unsigned int)home.living); manualMs = home.livingManualMs; break;
        case CONTROL_BEDROOM: (void)snprintf(line, sizeof(line), "BEDROOM %u%%", (unsigned int)home.bedroom); manualMs = home.bedroomManualMs; break;
        case CONTROL_HALL: (void)snprintf(line, sizeof(line), "HALL %u%%", (unsigned int)home.hall); manualMs = home.hallManualMs; break;
        case CONTROL_LOAD: (void)snprintf(line, sizeof(line), "LOAD:%s KEEP:ON", home.loadSwitch ? "ON" : "OFF"); break;
        case CONTROL_DEMAND: (void)snprintf(line, sizeof(line), "AC %s:%s", home.demandManual ? "MANUAL" : "AUTO", home.cooling ? "ON" : "OFF"); break;
        case CONTROL_EFFECT: (void)snprintf(line, sizeof(line), "KTV EFFECT: %s", home.lightEffect == HOME_LIGHT_RAINBOW ? "RAINBOW" : home.lightEffect == HOME_LIGHT_PULSE ? "PULSE" : "PARTY"); break;
        case CONTROL_KTV_LEVEL: (void)snprintf(line, sizeof(line), "KTV ALL LIGHTS: %u%%", (unsigned int)home.ktvBrightness); break;
        case CONTROL_NIGHT: (void)snprintf(line, sizeof(line), "NIGHT:%s SLEEP ONLY", home.nightActive ? "ON" : "OFF"); break;
        default: (void)snprintf(line, sizeof(line), "TIMER %s %lus", HomeAutomation_TimerName(home.timer),
            (unsigned long)((home.timer == HOME_TIMER_IDLE || home.timer == HOME_TIMER_DONE) ? localTimerSetting : home.timerSeconds)); break;
    }
    (void)DisplayService_ViewSetLine(view, 4U, line);
    if (manualMs != 0UL) {
        (void)snprintf(line, sizeof(line), "MANUAL %lus HOLD:AUTO", (unsigned long)((manualMs + 999UL) / 1000UL));
    } else if (localControl == CONTROL_TIMER) { (void)snprintf(line, sizeof(line), "PUSH RUN/PAUSE HOLD:X"); }
    else if (localControl == CONTROL_EFFECT) { (void)snprintf(line, sizeof(line), "UP/DN EFFECT H:RESET"); }
    else if (localControl == CONTROL_KTV_LEVEL) { (void)snprintf(line, sizeof(line), "UP/DN +/-10 H:50%%"); }
    else if (localControl == CONTROL_DEMAND) { (void)snprintf(line, sizeof(line), "UP ON DN OFF H:AUTO"); }
    else { (void)snprintf(line, sizeof(line), "LR SELECT UD/PUSH SET"); }
    (void)DisplayService_ViewSetLine(view, 5U, line);
    (void)DisplayService_ViewSetLine(view, 6U, localResult);
    (void)DisplayService_ViewSetLine(view, 7U, "SW1 BACK SW2 STUDY");
}
