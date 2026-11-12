/* Native tests execute the production policy C against deterministic service fakes.
 * They do not model sensor electronics, interrupt timing or physical servo motion.
 */
#include "home_automation.h"
#include "smart_home_app.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static HomeInputsSnapshot_t input;
static bool tempHealthy, tempAvailable, potAvailable, proxHealthy, proxPresent, musicBusy;
static float temperature;
static uint32_t tempAt, potAt, proxAt;
static uint8_t potPercent, current[4], target[4], led, pixel[8][3];
static uint8_t rgb[3];
static uint32_t rgbPeriod;
static unsigned sounds;
static uint32_t clockMs;
MusicService_Debug_t g_musicServiceDebug;
static ButtonService_Event_t events[8];
static uint8_t eventCount, eventRead;
static unsigned legacyOutputCalls, pageButtonCalls;
static DisplayService_View_t submittedView;
static bool displayAwake;

void HomeInputs_GetSnapshot(uint32_t now, HomeInputsSnapshot_t *out) { (void)now; *out=input; }
bool TemperatureService_IsHealthy(void) { return tempHealthy; }
bool TemperatureService_IsValid(void) { return tempAvailable; }
uint32_t TemperatureService_GetLastUpdateMs(void) { return tempAt; }
uint32_t TemperatureService_GetSampleCount(void) { return 1; }
bool TemperatureService_GetCelsius(float *t) { *t=temperature; return tempAvailable; }
bool PotentiometerService_GetPercent(uint8_t *p) { *p=potPercent; return potAvailable; }
uint32_t PotentiometerService_GetLastUpdateMs(void) { return potAt; }
bool ProximityService_IsHealthy(void) { return proxHealthy; }
bool ProximityService_IsValid(void) { return proxHealthy; }
bool ProximityService_IsPresent(void) { return proxPresent; }
uint32_t ProximityService_GetLastUpdateMs(void) { return proxAt; }
uint8_t ServoService_GetCurrentAngle(ServoService_Device_t d) { return current[d]; }
uint8_t ServoService_GetTargetAngle(ServoService_Device_t d) { return target[d]; }
bool ServoService_IsMoving(ServoService_Device_t d) { return current[d]!=target[d]; }
void ServoService_SetTarget(ServoService_Device_t d,uint8_t a) { target[d]=a; }
void ServoService_SetMoveStep(ServoService_Device_t d,uint8_t s) { (void)d; (void)s; }
void ServoService_DoorOpen(void) { legacyOutputCalls++; }
void ServoService_DoorClose(void) { legacyOutputCalls++; }
void ServoService_WindowOpen(void) { legacyOutputCalls++; }
void ServoService_WindowClose(void) { legacyOutputCalls++; }
void ServoService_VentClose(void) { legacyOutputCalls++; }
void LEDService_Set(uint8_t mask,bool on) { if(on){led|=mask;}else{led&=(uint8_t)~mask;} }
void WS2812BService_SetBrightness(uint8_t brightness) { assert(brightness==100); }
void WS2812BService_SetPixel(uint8_t i,uint8_t r,uint8_t g,uint8_t b) { pixel[i][0]=r;pixel[i][1]=g;pixel[i][2]=b; }
void WS2812BService_Clear(void) { legacyOutputCalls++; }
void WS2812BService_RainbowBreathe(uint32_t p) { (void)p;legacyOutputCalls++; }
void RGBLEDService_Off(void) { memset(rgb,0,sizeof(rgb));rgbPeriod=0; }
void RGBLEDService_SetColor(uint8_t r,uint8_t g,uint8_t b) { rgb[0]=r;rgb[1]=g;rgb[2]=b;rgbPeriod=0; }
void RGBLEDService_Breathe(uint8_t r,uint8_t g,uint8_t b,uint32_t p) { RGBLEDService_SetColor(r,g,b);rgbPeriod=p; }
bool MusicService_IsPlaying(void) { return musicBusy; }
int MusicService_PlayMelody(const MusicService_MelodyEvent_t *n,uint16_t length,bool loop)
{ (void)n;(void)length;assert(!loop);sounds++;g_musicServiceDebug.playCount++;musicBusy=true;return 0; }
void MusicService_Stop(void) { musicBusy=false; }
void DisplayService_ViewClear(DisplayService_View_t *v) { memset(v,0,sizeof(*v)); }
bool DisplayService_ViewSetLine(DisplayService_View_t *v,uint8_t row,const char *s)
{ assert(row<8); strncpy_s(v->line[row],21,s,20);return true; }
void DisplayService_SetAwake(bool awake) { displayAwake=awake; }
bool DisplayService_SubmitView(const DisplayService_View_t *v) { submittedView=*v;return true; }
bool ButtonService_TakeEvent(ButtonService_Event_t *e)
{ if(eventRead>=eventCount){return false;}*e=events[eventRead++];return true; }
ProximityService_Event_t ProximityService_TakeEvent(void) { return PROXIMITY_EVENT_NONE; }
static void PageEnter(uint32_t now) { (void)now; }
static void PageExit(void) { }
static AppPage_Action_t PageTask(uint32_t now) { (void)now;return AppPage_NoAction(); }
static AppPage_Action_t PageButton(const ButtonService_Event_t *event)
{ (void)event;pageButtonCalls++;return AppPage_NoAction(); }
static void PageBuild(DisplayService_View_t *v) { DisplayService_ViewClear(v); }
const AppPage_Interface_t g_welcomePage = { PageEnter,PageExit,PageTask,PageButton,PageBuild };
const AppPage_Interface_t g_temperaturePage = { PageEnter,PageExit,PageTask,PageButton,PageBuild };
const AppPage_Interface_t g_environmentPage = { PageEnter,PageExit,PageTask,PageButton,PageBuild };
const AppPage_Interface_t g_menuPage = { PageEnter,PageExit,PageTask,PageButton,PageBuild };
const AppPage_Interface_t g_musicPage = { PageEnter,PageExit,PageTask,PageButton,PageBuild };

static const HomeAutomation_State_t *State(void) { return HomeAutomation_GetState(); }
static void Fresh(uint32_t now) { clockMs=now;tempAt=potAt=proxAt=now; }
static void Tick(uint32_t now) { Fresh(now);HomeAutomation_Task(now); }
static void Settle(void) { memcpy(current,target,sizeof(current)); }
static void Init(uint32_t now)
{
    memset(&input,0,sizeof(input));memset(current,0,sizeof(current));memset(target,0,sizeof(target));
    memset(pixel,0,sizeof(pixel));led=0;sounds=0;
    g_musicServiceDebug.playCount=0;
    eventCount=eventRead=0;legacyOutputCalls=pageButtonCalls=0;
    input.humidityValid=true;input.humidity10=450;input.luxValid=true;input.lux=50;
    input.rainValid=true;input.waterValid=true;
    tempHealthy=tempAvailable=proxHealthy=proxPresent=true;potAvailable=false;musicBusy=false;
    temperature=31.0f;potPercent=0;Fresh(now);HomeAutomation_Initialize(now);
}
static void Cmd(const char *action,const char *value)
{ const char *reason;assert(HomeAutomation_Command(action,value,clockMs,&reason));assert(strcmp(reason,"OK")==0); }
static void Denied(const char *action,const char *value,const char *expected)
{ const char *reason;assert(!HomeAutomation_Command(action,value,clockMs,&reason));assert(strcmp(reason,expected)==0); }

static void RainAndCooling(void)
{
    Init(100);
    assert(State()->windowTarget==100 && !State()->cooling);
    Settle();
    potAvailable=true;potPercent=0;Tick(110);assert(State()->windowTarget==0 && !State()->cooling);
    Settle();Tick(120);assert(State()->window==1 && State()->cooling && target[2]==90);
    Cmd("window","open");assert(!State()->cooling && State()->windowTarget==100 && target[2]==0);
    input.rainWet=true;Tick(130);assert(State()->windowTarget==0 && !State()->windowManual && State()->windowManualMs==0);
    Denied("window","open","RAIN");
    input.rainValid=false;input.rainWet=false;Tick(140);assert(State()->windowTarget==0);
    Denied("window","open","INPUT_UNAVAILABLE");
    input.rainValid=true;Tick(150);assert(State()->windowTarget==0 && !State()->windowManual);
    Cmd("window","auto");Settle();Tick(160);assert(State()->cooling);
    tempHealthy=false;Tick(170);assert(!State()->tempValid && !State()->cooling && target[2]==0);
    tempHealthy=true;Fresh(4000);tempAt=0;HomeAutomation_Task(4000);assert(!State()->tempValid && !State()->cooling);
    puts("PASS rain priority, unknown input, moving-window interlock, stale temperature");
}

static void IndependentManuals(void)
{
    Init(1000);temperature=25;Tick(1000);
    Cmd("window","open");Tick(2000);Cmd("living","80");
    Tick(61001);assert(!State()->windowManual && State()->livingManual && State()->living==80);
    assert(State()->windowTarget==0 && State()->livingManualMs==999);
    Tick(62001);assert(!State()->livingManual && State()->living!=80);
    Cmd("demand","1");Tick(63000);Cmd("hall","20");
    Tick(122002);assert(State()->demandManual && State()->hallManual);
    Tick(123001);assert(!State()->hallManual);
    Init(0xFFFFFF00UL);Cmd("window","open");Tick((uint32_t)(0xFFFFFF00UL+59999UL));
    assert(State()->windowManual);Tick((uint32_t)(0xFFFFFF00UL+60000UL));assert(!State()->windowManual);
    puts("PASS independent override expiry, demand override, millisecond wraparound");
}

static void AwayModes(void)
{
    Init(100);Cmd("scene","away");assert(!State()->loadSwitch && State()->living==0);
    assert(State()->windowTarget==100 && target[3]==90);
    Cmd("load_switch","1");Cmd("living","50");assert(State()->loadSwitch && State()->living==50);
    Denied("door","open","AWAY");Denied("demand","1","AWAY");Settle();Tick(110);assert(!State()->cooling);
    Cmd("scene","long_away");assert(State()->windowTarget==0 && State()->doorTarget==0 && target[3]==0);
    Denied("window","open","LONG_AWAY");Denied("living","50","LONG_AWAY");
    Denied("load_switch","1","LONG_AWAY");
    Settle();Tick(120);assert(State()->awayCheckOk && State()->door==1 && State()->window==1);
    Tick(80000);assert(State()->scene==HOME_SCENE_LONG_AWAY && State()->windowTarget==0 && !State()->loadSwitch);
    Cmd("scene","home");assert(State()->doorTarget==100 && State()->windowTarget==100);
    Cmd("scene","sleep");assert(State()->windowTarget==0 && target[3]==0);
    Cmd("scene","movie");assert(State()->windowTarget==0 && target[3]==0);
    puts("PASS ordinary-away manual controls, long-away locks, scene-dependent ventilation/privacy");
}

static void LightCurtainComfort(void)
{
    Init(0);assert(State()->living==65 && State()->bedroom==65 && State()->hall==32);
    assert(pixel[0][0]==pixel[2][0] && pixel[3][0]==pixel[5][0] && pixel[6][0]<pixel[0][0]);
    input.lux=500;Tick(100);Tick(3099);assert(target[3]==90);
    Tick(3100);assert(target[3]==0);input.lux=400;Tick(4000);assert(target[3]==0);
    input.lux=300;Tick(4100);input.luxValid=false;Tick(5000);input.luxValid=true;Tick(6000);
    Tick(8999);assert(target[3]==0);Tick(9000);assert(target[3]==90);
    Cmd("curtain","close");Tick(9001);assert(State()->curtainManual);
    Cmd("scene","sleep");assert(!State()->curtainManual && State()->living==0 && State()->hall==0);
    Cmd("night","1");assert(State()->hall==10 && State()->bedroom==0);
    Cmd("timer_start","60");assert(State()->hall==10 && State()->bedroom==0);
    Tick(39001);assert(!State()->nightActive && State()->hall==0);
    input.humidity10=399;Tick(39002);assert(State()->comfort==1);
    input.humidity10=400;Tick(39003);assert(State()->comfort==2);
    input.humidity10=600;Tick(39004);assert(State()->comfort==2);
    input.humidity10=601;Tick(39005);assert(State()->comfort==3);
    input.humidityValid=false;Tick(39006);assert(State()->comfort==0);
    puts("PASS zoned light ownership, ALS curtain stability/hysteresis, night path, humidity boundaries");
}

static void WaterAndTimer(void)
{
    Init(100);Denied("mute","1","NO_WATER_ALARM");
    musicBusy=true;input.waterWet=true;Tick(200);assert(State()->waterAlarm && sounds==0);
    musicBusy=false;Tick(201);assert(sounds==1);Tick(202);assert(sounds==1);
    Cmd("mute","1");assert(State()->muted && State()->waterAlarm && !musicBusy);
    input.waterValid=false;input.waterWet=false;Tick(300);assert(State()->waterAlarm && State()->muted);
    Cmd("mute","1");input.waterValid=true;Tick(400);assert(!State()->waterAlarm && !State()->muted);
    input.waterWet=true;Tick(500);assert(State()->waterAlarm && !State()->muted);
    g_musicServiceDebug.playCount++;musicBusy=true;Cmd("mute","1");assert(musicBusy);
    input.waterWet=false;Tick(600);musicBusy=false;Cmd("timer_start","3");Tick(1600);
    assert(State()->timerSeconds==2);Cmd("timer_pause","1");Tick(16000);assert(State()->timerSeconds==2);
    Cmd("timer_resume","1");Tick(17999);assert(State()->timer==HOME_TIMER_RUNNING);
    Tick(18000);assert(State()->timer==HOME_TIMER_DONE && State()->timerSeconds==0);
    Cmd("timer_stop","1");assert(State()->timer==HOME_TIMER_IDLE);
    Denied("timer_resume","1","TIMER_STATE");Denied("timer_start","0","INVALID_VALUE");
    Denied("timer_start","86401","INVALID_VALUE");Denied("timer_start","99999999999999","INVALID_VALUE");
    Denied("living","-1","INVALID_VALUE");Denied("living","101","INVALID_VALUE");
    Denied("anything","1","UNSUPPORTED");
    Cmd("scene","sleep");sounds=0;musicBusy=false;Cmd("timer_start","1");Tick(19000);assert(sounds==0);
    Init(0xFFFFFF00UL);Cmd("timer_start","2");Tick((uint32_t)(0xFFFFFF00UL+2000UL));
    assert(State()->timer==HOME_TIMER_DONE);
    puts("PASS water latch/mute/recovery, music non-interruption, timer pause/resume/range/wrap/quiet");
}

static void SetpointAndLocal(void)
{
    ButtonService_Event_t e;
    DisplayService_View_t view;
    Init(100);assert(State()->setpoint10==315);
    potAvailable=true;potPercent=0;temperature=20.4f;Tick(101);assert(State()->setpoint10==200 && !State()->demand);
    temperature=20.5f;Tick(102);assert(State()->demand);
    temperature=19.6f;Tick(103);assert(State()->demand);
    temperature=19.5f;Tick(104);assert(!State()->demand);
    potPercent=100;Tick(105);assert(State()->setpoint10==320);
    potAvailable=false;Tick(106);assert(State()->setpoint10==315);
    e.type=BUTTON_EVENT_SHORT_PRESS;e.button=BUTTON_ID_JOY_UP;
    HomeAutomation_HandleButton(&e,clockMs);assert(State()->scene==HOME_SCENE_AWAY);
    HomeAutomation_BuildView(&view);assert(strstr(view.line[0],"away")!=NULL);
    e.button=BUTTON_ID_JOY_RIGHT;HomeAutomation_HandleButton(&e,clockMs);
    e.button=BUTTON_ID_JOY_UP;HomeAutomation_HandleButton(&e,clockMs);assert(State()->windowManual);
    e.type=BUTTON_EVENT_LONG_PRESS;e.button=BUTTON_ID_JOY_PUSH;HomeAutomation_HandleButton(&e,clockMs);
    assert(!State()->windowManual);
    proxPresent=false;Tick(107);assert(State()->doorTarget==0 && !(led&1));
    puts("PASS knob setpoint and cooling hysteresis, standalone local input/view, absent-person operation");
}

static void RouterIsolation(void)
{
    uint8_t savedLed;
    Init(100);SmartHomeApp_Initialize(100);HomeAutomation_Initialize(100);
    Cmd("scene","long_away");proxPresent=false;proxHealthy=false;Tick(101);
    savedLed=led;legacyOutputCalls=0;
    events[0].button=BUTTON_ID_SW1;events[0].type=BUTTON_EVENT_LONG_PRESS;
    events[1].button=BUTTON_ID_JOY_UP;events[1].type=BUTTON_EVENT_SHORT_PRESS;
    eventCount=2;eventRead=0;SmartHomeApp_Task(101);
    assert(eventRead==2 && State()->scene==HOME_SCENE_SLEEP && displayAwake);
    assert(pageButtonCalls==0 && legacyOutputCalls==0 && savedLed==led);
    assert(strstr(submittedView.line[5],"sleep")!=NULL);
    eventCount=1;eventRead=0;events[0].button=BUTTON_ID_SW3;events[0].type=BUTTON_EVENT_SHORT_PRESS;
    SmartHomeApp_Task(102);assert(SmartHomeApp_GetScreen()==APP_PAGE_MENU && eventRead==1);
    eventRead=0;events[0].button=BUTTON_ID_JOY_UP;SmartHomeApp_Task(103);assert(pageButtonCalls==1);
    assert(legacyOutputCalls==0);
    eventRead=eventCount=0;SmartHomeApp_Task(104);assert(pageButtonCalls==1);
    puts("PASS production Router: away/no-presence local access, single event consumption, base-menu return, output isolation");
}

static void TemperatureDemo(void)
{
    Init(0);temperature=23.3f;Tick(1);
    assert(rgb[0]==0 && rgb[1]==100 && rgb[2]==0 && rgbPeriod==0);
    temperature=23.9f;Tick(2);assert(rgb[0]==0 && rgb[1]==100);
    temperature=24.0f;Tick(3);assert(rgb[0]==100 && rgb[1]==65 && rgbPeriod==0);
    temperature=23.9f;Tick(4);assert(rgb[0]==100 && rgb[1]==65);
    temperature=23.8f;Tick(5);assert(rgb[0]==0 && rgb[1]==100);
    temperature=24.8f;Tick(6);assert(rgb[0]==100 && rgb[1]==0 && rgb[2]==0 && rgbPeriod==2000);
    temperature=24.7f;Tick(7);assert(rgbPeriod==2000);
    temperature=24.6f;Tick(8);assert(rgb[1]==65 && rgbPeriod==0);
    temperature=25.3f;Tick(9);assert(rgbPeriod==2000);
    assert(!State()->demand); /* RGB demo thresholds do not change AC policy. */
    tempHealthy=false;Tick(10);assert(rgb[0]==0 && rgb[1]==0 && rgb[2]==0);
    tempHealthy=true;temperature=24.5f;Tick(11);assert(rgb[0]==100 && rgb[1]==65 && rgbPeriod==0);
    HomeAutomation_Task(6000);assert(rgb[0]==0 && rgb[1]==0 && rgb[2]==0);
    puts("PASS hand-warming RGB demo, both hysteresis boundaries, invalid/stale temperature, independent AC policy");
}

static void RainbowDemo(void)
{
    uint8_t first[8][3], i, active;
    Init(0);proxPresent=false;input.lux=800;Tick(0);
    assert(State()->lightEffect==HOME_LIGHT_WARM && pixel[0][0]==0);
    Denied("light_effect","rainbow","SCENE");
    Cmd("scene","ktv");
    assert(State()->lightEffect==HOME_LIGHT_RAINBOW && State()->living==50 && State()->hall==50);
    assert(State()->doorTarget==0 && State()->windowTarget==0 && target[3]==0);
    Denied("living","20","SCENE");Denied("hall","auto","SCENE");
    for(i=0;i<8;i++) { assert(pixel[i][0] || pixel[i][1] || pixel[i][2]); }
    assert(memcmp(pixel[0],pixel[3],3)!=0 && memcmp(pixel[3],pixel[6],3)!=0);
    memcpy(first,pixel,sizeof(first));Tick(384);assert(memcmp(first,pixel,sizeof(first))!=0);
    Tick(6144);assert(memcmp(first,pixel,sizeof(first))==0);
    Denied("light_effect","invalid","INVALID_VALUE");assert(State()->lightEffect==HOME_LIGHT_RAINBOW);
    Cmd("ktv_brightness","20");assert(State()->living==20 && State()->bedroom==20 && State()->hall==20);
    for(i=0;i<8;i++) { assert(pixel[i][0]<=51 && pixel[i][1]<=51 && pixel[i][2]<=51); }
    Cmd("light_effect","pulse");assert(pixel[0][0]==5);
    Tick(7344);for(i=0;i<8;i++) { assert(pixel[i][0]<=51 && pixel[i][1]<=51 && pixel[i][2]<=51); }
    Cmd("light_effect","party");active=0;
    for(i=0;i<8;i++) { if(pixel[i][0] || pixel[i][1] || pixel[i][2]) { active++; } }
    assert(active==3);memcpy(first,pixel,sizeof(first));Tick(7524);assert(memcmp(first,pixel,sizeof(first))!=0);
    Cmd("ktv_brightness","0");Cmd("timer_start","60");
    for(i=0;i<8;i++) { assert(!(pixel[i][0] || pixel[i][1] || pixel[i][2])); }
    Cmd("light_effect","rainbow");Tick(7704);
    for(i=0;i<8;i++) { assert(!(pixel[i][0] || pixel[i][1] || pixel[i][2])); }
    Cmd("light_effect","pulse");Tick(7904);
    for(i=0;i<8;i++) { assert(!(pixel[i][0] || pixel[i][1] || pixel[i][2])); }
    Cmd("ktv_brightness","100");Cmd("light_effect","rainbow");assert(pixel[0][0]==255);
    Cmd("timer_stop","1");Cmd("scene","home");
    assert(State()->lightEffect==HOME_LIGHT_WARM);
    for(i=0;i<8;i++) { assert(!(pixel[i][0] || pixel[i][1] || pixel[i][2])); }
    Cmd("scene","ktv");assert(State()->ktvBrightness==100 && State()->living==100);
    Cmd("scene","away");for(i=0;i<8;i++) { assert(!(pixel[i][0] || pixel[i][1] || pixel[i][2])); }
    Cmd("scene","home");Cmd("living","100");
    assert(pixel[0][0]==255 && pixel[0][1]==210 && pixel[0][2]==150);
    assert(pixel[3][0]==0 && pixel[6][0]==0);
    Init(0xFFFFFF00UL);Cmd("scene","ktv");
    memcpy(first,pixel,sizeof(first));Tick(0xFFFFFFF0UL);assert(memcmp(first,pixel,sizeof(first))!=0);
    Tick(0x00001700UL);assert(memcmp(first,pixel,sizeof(first))==0);
    puts("PASS KTV three effects, one eight-pixel master, zero blackout, scene mechanisms, warm restore, clock wrap");
}

static void PersistentDemand(void)
{
    Init(0);temperature=23.3f;tempHealthy=false;Cmd("window","open");Cmd("demand","1");
    assert(State()->demandManual && State()->cooling && State()->windowTarget==100 && !State()->tempValid);
    Tick(120001);assert(State()->demandManual && State()->cooling);
    Cmd("window","open");assert(State()->cooling && State()->windowTarget==100);
    Cmd("scene","movie");Cmd("scene","sleep");Cmd("scene","ktv");
    assert(State()->demandManual && State()->cooling);
    Cmd("demand","0");tempHealthy=true;temperature=40;Tick(120002);
    assert(State()->demandManual && !State()->cooling && !State()->demand);
    Cmd("demand","auto");Settle();Tick(120003);assert(!State()->demandManual && State()->cooling);
    Cmd("window","open");assert(!State()->cooling);
    Cmd("demand","1");assert(State()->cooling);Cmd("scene","away");
    assert(!State()->demandManual && !State()->cooling);Denied("demand","1","AWAY");
    Cmd("scene","home");Cmd("demand","0");Cmd("scene","long_away");assert(!State()->demandManual);
    Init(0xFFFFFF00UL);Cmd("demand","1");Tick(120000UL);assert(State()->demandManual && State()->cooling);
    puts("PASS persistent manual AC on/off, force override, auto restore, away reset, non-away scene preservation, wrap");
}

static void StudyPixel(void)
{
    uint8_t before[8][3], i;
    Init(0);proxPresent=false;input.lux=800;Tick(0);memcpy(before,pixel,sizeof(before));
    Cmd("timer_start","60");assert(pixel[7][0]==25 && pixel[7][1]==25 && pixel[7][2]==25);
    for(i=0;i<7;i++) { assert(memcmp(before[i],pixel[i],3)==0); }
    assert(target[3]==90);Tick(2000);assert(pixel[7][0]==153 && pixel[7][1]==153 && pixel[7][2]==153);
    Cmd("timer_pause","1");Tick(3000);assert(pixel[7][0]==51 && pixel[7][1]==51 && pixel[7][2]==51);
    Cmd("timer_resume","1");Tick(4000);assert(pixel[7][0]==25);
    Cmd("scene","away");assert(pixel[7][0]==0);Cmd("scene","home");assert(pixel[7][0]>0);
    Cmd("scene","ktv");Cmd("ktv_brightness","0");assert(pixel[7][0]==0);
    Cmd("scene","home");Cmd("timer_stop","1");assert(pixel[7][0]==0);
    Cmd("timer_start","1");Tick(5000);assert(State()->timer==HOME_TIMER_DONE && pixel[7][0]==0);
    Init(0xFFFFFF00UL);proxPresent=false;input.lux=800;Cmd("timer_start","60");
    Tick(0x000006D0UL);assert(pixel[7][0]==153);
    puts("PASS dedicated slow-white study pixel, pause/resume, restoration, no curtain command, KTV priority, wrap");
}

static void NoticeAndPhysicalControls(void)
{
    DisplayService_View_t view, original;
    ButtonService_Event_t event;
    char rxAction[12] = "window", rxValue[12] = "open";
    const char *reason;
    uint8_t i;
    Init(100);proxPresent=false;SmartHomeApp_Initialize(100);HomeAutomation_Initialize(100);
    HomeAutomation_BuildView(&view);original=view;
    assert(HomeAutomation_ApplyNotice(&view,100) && strcmp(view.line[2],"FRIDGE POWER ON")==0);
    view=original;assert(!HomeAutomation_ApplyNotice(&view,3100) && memcmp(&view,&original,sizeof(view))==0);
    Fresh(4000);Cmd("demand","1");HomeAutomation_BuildView(&view);
    assert(HomeAutomation_ApplyNotice(&view,4000) && strcmp(view.line[2],"AIR CONDITIONER ON")==0);
    Fresh(4100);Cmd("load_switch","0");HomeAutomation_BuildView(&view);
    assert(HomeAutomation_ApplyNotice(&view,4100) && strcmp(view.line[2],"TV OFF")==0);
    Fresh(4200);Cmd("timer_start","60");HomeAutomation_BuildView(&view);
    assert(HomeAutomation_ApplyNotice(&view,4200) && strcmp(view.line[2],"STUDY STARTED")==0);
    Fresh(4300);Cmd("timer_pause","1");HomeAutomation_BuildView(&view);
    assert(HomeAutomation_ApplyNotice(&view,4300) && strcmp(view.line[2],"STUDY PAUSED")==0);
    Fresh(4400);Cmd("timer_resume","1");HomeAutomation_BuildView(&view);
    assert(HomeAutomation_ApplyNotice(&view,4400) && strcmp(view.line[2],"STUDY RESUMED")==0);
    Fresh(4500);Cmd("scene","ktv");HomeAutomation_BuildView(&view);
    assert(HomeAutomation_ApplyNotice(&view,4500) && strcmp(view.line[2],"KTV MODE")==0);
    event.type=BUTTON_EVENT_SHORT_PRESS;event.button=BUTTON_ID_JOY_UP;
    HomeAutomation_HandleButton(&event,4500);assert(State()->lightEffect==HOME_LIGHT_PULSE);
    HomeAutomation_BuildView(&view);assert(HomeAutomation_ApplyNotice(&view,4500) && strcmp(view.line[2],"COLOR PULSE")==0);
    event.button=BUTTON_ID_JOY_PUSH;HomeAutomation_HandleButton(&event,4500);assert(State()->lightEffect==HOME_LIGHT_PARTY);
    event.button=BUTTON_ID_JOY_DOWN;HomeAutomation_HandleButton(&event,4500);assert(State()->lightEffect==HOME_LIGHT_PULSE);
    event.button=BUTTON_ID_JOY_RIGHT;HomeAutomation_HandleButton(&event,4500);
    HomeAutomation_BuildView(&view);assert(strstr(view.line[4],"KTV ALL LIGHTS")!=NULL);
    event.button=BUTTON_ID_JOY_DOWN;HomeAutomation_HandleButton(&event,4500);assert(State()->ktvBrightness==40);
    event.button=BUTTON_ID_JOY_PUSH;HomeAutomation_HandleButton(&event,4500);assert(State()->ktvBrightness==0);
    event.type=BUTTON_EVENT_LONG_PRESS;HomeAutomation_HandleButton(&event,4500);assert(State()->ktvBrightness==50);
    Cmd("scene","home");Cmd("timer_stop","1");
    assert(HomeAutomation_Command(rxAction,rxValue,4500,&reason));
    memset(rxAction,'X',sizeof(rxAction));memset(rxValue,'X',sizeof(rxValue));
    HomeAutomation_BuildView(&view);assert(HomeAutomation_ApplyNotice(&view,4500));
    assert(strcmp(view.line[2],"window")==0 && strcmp(view.line[5],"open")==0);
    event.type=BUTTON_EVENT_SHORT_PRESS;event.button=BUTTON_ID_SW2;
    HomeAutomation_HandleButton(&event,4500);assert(State()->timer==HOME_TIMER_RUNNING);
    HomeAutomation_HandleButton(&event,4500);assert(State()->timer==HOME_TIMER_PAUSED);
    HomeAutomation_HandleButton(&event,4500);assert(State()->timer==HOME_TIMER_RUNNING);
    input.waterWet=true;Tick(4501);assert(State()->waterAlarm);
    HomeAutomation_HandleButton(&event,4501);assert(State()->muted && State()->timer==HOME_TIMER_RUNNING);
    event.type=BUTTON_EVENT_LONG_PRESS;HomeAutomation_HandleButton(&event,4501);assert(State()->timer==HOME_TIMER_IDLE);
    input.waterWet=false;Tick(4502);
    events[0].button=BUTTON_ID_SW1;events[0].type=BUTTON_EVENT_SHORT_PRESS;eventCount=1;eventRead=0;
    SmartHomeApp_Task(4502);assert(eventRead==1);assert(strstr(submittedView.line[0],"HOME")!=NULL);
    events[0].button=BUTTON_ID_JOY_RIGHT;eventRead=0;SmartHomeApp_Task(4503);
    assert(strstr(submittedView.line[4],"WINDOW")!=NULL);
    events[0].button=BUTTON_ID_JOY_UP;eventRead=0;SmartHomeApp_Task(4504);assert(State()->windowManual && State()->windowTarget==100);
    events[0].button=BUTTON_ID_SW3;eventRead=0;SmartHomeApp_Task(4505);assert(SmartHomeApp_GetScreen()==APP_PAGE_MENU);
    events[0].button=BUTTON_ID_SW2;eventRead=0;SmartHomeApp_Task(4506);assert(State()->timer==HOME_TIMER_RUNNING);
    events[0].button=BUTTON_ID_SW3;eventRead=0;SmartHomeApp_Task(4507);
    assert(SmartHomeApp_GetScreen()==APP_PAGE_MENU && strcmp(submittedView.line[0],"SMART HOME")!=0);
    eventRead=eventCount=0;HomeAutomation_DismissNotice();SmartHomeApp_Task(7606);
    assert(SmartHomeApp_GetScreen()==APP_PAGE_MENU && strcmp(submittedView.line[0],"SMART HOME")!=0);
    Init(0xFFFFFF00UL);Cmd("demand","1");HomeAutomation_BuildView(&view);
    assert(HomeAutomation_ApplyNotice(&view,0x00000900UL));
    assert(!HomeAutomation_ApplyNotice(&view,0x00000AB8UL));
    Init(0);HomeAutomation_DismissNotice();
    event.type=BUTTON_EVENT_SHORT_PRESS;event.button=BUTTON_ID_JOY_LEFT;
    for(i=0;i<22;i++) { HomeAutomation_HandleButton(&event,0);HomeAutomation_BuildView(&view);assert(!strstr(view.line[4],"KTV")); }
    puts("PASS notices: 3-second expiry/wrap/latest message, page restoration, SW1 control access, SW2 study/mute, joystick KTV/master and menu");
}

int main(void)
{
    RainAndCooling();IndependentManuals();AwayModes();LightCurtainComfort();WaterAndTimer();SetpointAndLocal();RouterIsolation();TemperatureDemo();RainbowDemo();PersistentDemand();StudyPixel();NoticeAndPhysicalControls();
    puts("All production automation policy tests passed.");return 0;
}
