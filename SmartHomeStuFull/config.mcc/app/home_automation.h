#ifndef HOME_AUTOMATION_H
#define HOME_AUTOMATION_H

#include <stdbool.h>
#include <stdint.h>
#include "home_inputs.h"
#include "button_service.h"
#include "display_service.h"

typedef enum {
    HOME_SCENE_HOME = 0, HOME_SCENE_AWAY, HOME_SCENE_LONG_AWAY,
    HOME_SCENE_SLEEP, HOME_SCENE_MOVIE, HOME_SCENE_KTV
} HomeScene_t;
typedef enum {
    HOME_TIMER_IDLE = 0, HOME_TIMER_RUNNING, HOME_TIMER_PAUSED, HOME_TIMER_DONE
} HomeTimer_t;
typedef enum {
    HOME_LIGHT_WARM = 0, HOME_LIGHT_RAINBOW, HOME_LIGHT_PULSE, HOME_LIGHT_PARTY
} HomeLightEffect_t;

/* All positions are SOFTWARE COMMAND feedback, never physical limit switches.
 * door/window: 1 only when the close command has settled (!IsMoving).
 * doorTarget/windowTarget/curtain/vent: open % (0..90 deg).
 * Room/position overrides expire after 60 s. Manual AC is persistent until
 * auto is selected or an away scene is entered.
 */
typedef struct {
    HomeInputsSnapshot_t inputs;
    bool tempValid;
    int16_t temp10;
    uint8_t door, window, doorTarget, windowTarget, curtain, vent;
    uint8_t living, bedroom, hall;
    HomeLightEffect_t lightEffect;
    uint8_t ktvBrightness;
    bool loadKeep, loadSwitch, cooling, demand, muted;
    HomeScene_t scene;
    bool windowManual;
    uint32_t windowManualMs;
    HomeTimer_t timer;
    uint32_t timerSeconds;
    uint8_t comfort; /* 0 unknown, 1 dry, 2 comfortable, 3 humid. */
    int16_t setpoint10;
    bool doorManual, curtainManual, livingManual, bedroomManual, hallManual;
    uint32_t doorManualMs, curtainManualMs, livingManualMs, bedroomManualMs, hallManualMs;
    bool demandManual, awayCheckOk, nightActive, waterAlarm;
} HomeAutomation_State_t;

void HomeAutomation_Initialize(uint32_t nowMs);
void HomeAutomation_Task(uint32_t nowMs);
const HomeAutomation_State_t *HomeAutomation_GetState(void);
bool HomeAutomation_Command(const char *action, const char *value,
                            uint32_t nowMs, const char **reason);
const char *HomeAutomation_SceneName(HomeScene_t scene);
const char *HomeAutomation_TimerName(HomeTimer_t timer);

/* Router consumes each event once, then delegates when the local overlay is open. */
void HomeAutomation_HandleButton(const ButtonService_Event_t *event, uint32_t nowMs);
void HomeAutomation_BuildView(DisplayService_View_t *view);
bool HomeAutomation_ApplyNotice(DisplayService_View_t *view, uint32_t nowMs);
void HomeAutomation_DismissNotice(void);

#endif
