/* SH1 transport: bounded ISR RX ring, incremental TX, no printf/heap/wait loops.
 * Parsing and business commands run only in the cooperative main loop.
 */
#include "host_serial.h"
#include "extension_config.h"
#include "home_automation.h"
#include "mcc_generated_files/uart/uart1.h"
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

#define RX_RING_SIZE 256U
#define RX_LINE_SIZE 256U
#define TX_SIZE 900U
#define MAX_FIELDS 5U

volatile HostSerialDebug_t g_hostSerialDebug;
static volatile uint8_t rxRing[RX_RING_SIZE];
static volatile uint8_t rxHead, rxTail, rxLost;
static char rxLine[RX_LINE_SIZE];
static uint16_t rxLength;
static bool rxDiscard, lineReady;
static char tx[TX_SIZE];
static uint16_t txLength, txPosition;
static bool txBad, connected, wantCaps, wantState;
static char boot[65];
static char client[33];
static uint32_t seq, nextStateMs, loops, lastCommandId;
static bool haveLastCommand, lastAccepted;
static char lastAction[33], lastValue[65];
static const char *lastReason;

static bool Reached(uint32_t now, uint32_t target) {
    return (int32_t)(now - target) >= 0;
}
static void PutChar(char ch) {
    if (txLength < TX_SIZE - 1U) tx[txLength++] = ch;
    else txBad = true;
}
static void Put(const char *text) { while (*text) PutChar(*text++); }
static void Number(uint32_t value) {
    char digits[10]; uint8_t n = 0;
    do { digits[n++] = (char)('0' + value % 10UL); value /= 10UL; } while (value);
    while (n) PutChar(digits[--n]);
}
static void SignedNumber(int32_t value) {
    if (value < 0) { PutChar('-'); Number((uint32_t)(-(value + 1)) + 1UL); }
    else Number((uint32_t)value);
}
static void Begin(const char *kind) {
    txLength = txPosition = 0U; txBad = false; Put("SH1|"); Put(kind);
}
static void Field(const char *key, const char *value) {
    PutChar('|'); Put(key); PutChar('='); Put(value);
}
static void Numeric(const char *key, uint32_t value) {
    PutChar('|'); Put(key); PutChar('='); Number(value);
}
static void Finish(void) {
    PutChar('\n');
    if (txBad) { txLength = txPosition = 0; g_hostSerialDebug.txOverflows++; }
}
static void FlushTx(void) {
    uint8_t budget = 32U;
    while (budget-- && txPosition < txLength && UART1_IsTxReady())
        UART1_Write((uint8_t)tx[txPosition++]);
    if (txPosition == txLength) txLength = txPosition = 0;
}
static void Caps(void) {
    Begin("CAPS"); Field("boot", boot); Field("firmware", HOME_FIRMWARE_VERSION);
    Field("caps", "scene,door,window,curtain,lights,loads,mute,timer,demand,night,session,light_effect,ktv,demand_hold");
    if (*client) Field("client", client);
    Finish();
}
static void Ack(const char *id, bool accepted, const char *reason, const char *cmdClient) {
    Begin("ACK"); Field("boot", boot); Field("id", id);
    if (cmdClient) Field("client", cmdClient);
    Field("result", accepted ? "ok" : "rejected");
    Field("reason", reason ? reason : "INVALID_VALUE"); Finish();
}
static void Error(const char *code) {
    Begin("ERR"); Field("boot", connected ? boot : "unbound"); Field("code", code); Finish();
}
static void State(uint32_t nowMs) {
    const HomeAutomation_State_t *s = HomeAutomation_GetState();
    Begin("STATE"); Field("boot", boot); Numeric("seq", ++seq); Numeric("uptime", nowMs / 1000UL);
    Put("|temp="); if (s->tempValid) SignedNumber(s->temp10); else Put("?");
    if (s->inputs.humidityValid) Numeric("humid", s->inputs.humidity10); else Field("humid", "?");
    if (s->inputs.luxValid) Numeric("lux", s->inputs.lux); else Field("lux", "?");
    if (s->inputs.rainValid) Numeric("rain", s->inputs.rainWet); else Field("rain", "?");
    if (s->inputs.waterValid) Numeric("water", s->inputs.waterWet); else Field("water", "?");
    Numeric("door", s->door); Numeric("window", s->window);
    Numeric("door_target", s->doorTarget); Numeric("window_target", s->windowTarget);
    Numeric("curtain", s->curtain); Numeric("vent", s->vent);
    Numeric("living", s->living); Numeric("bedroom", s->bedroom); Numeric("hall", s->hall);
    Field("light_effect", s->lightEffect == HOME_LIGHT_RAINBOW ? "rainbow" :
        s->lightEffect == HOME_LIGHT_PULSE ? "pulse" : s->lightEffect == HOME_LIGHT_PARTY ? "party" : "warm");
    Numeric("ktv_brightness", s->ktvBrightness);
    Field("demand_mode", s->demandManual ? (s->demand ? "on" : "off") : "auto");
    Numeric("load_keep", s->loadKeep); Numeric("load_switch", s->loadSwitch);
    Numeric("cooling", s->cooling);
    if (s->tempValid || s->demandManual) Numeric("demand", s->demand); else Field("demand", "?");
    Field("scene", HomeAutomation_SceneName(s->scene));
    Field("control", s->windowManual ? "manual" : "auto"); Numeric("manual_ms", s->windowManualMs);
    Field("timer", HomeAutomation_TimerName(s->timer)); Numeric("timer_s", s->timerSeconds);
    Numeric("muted", s->muted); Field("state_source", "commanded");
    Numeric("comfort", s->comfort); Numeric("setpoint10", (uint16_t)s->setpoint10);
    Numeric("alarm", s->waterAlarm);
    Numeric("away_check_ok", s->awayCheckOk);
    Numeric("door_manual_ms", s->doorManualMs); Numeric("curtain_manual_ms", s->curtainManualMs);
    Numeric("living_manual_ms", s->livingManualMs); Numeric("bedroom_manual_ms", s->bedroomManualMs);
    Numeric("hall_manual_ms", s->hallManualMs); Numeric("night", s->nightActive);
    Finish(); if (!txBad) g_hostSerialDebug.sentStates++;
}
static bool Unsigned(const char *str, uint32_t *result) {
    uint32_t n = 0; uint8_t digit;
    if (!str || !*str) return false;
    while (*str) {
        if (*str < '0' || *str > '9') return false;
        digit = (uint8_t)(*str++ - '0');
        if (n > (0xFFFFFFFFUL - digit) / 10UL) return false;
        n = n * 10UL + digit;
    }
    *result = n; return true;
}
static bool Nonce(const char *str) {
    uint8_t n = 0;
    while (*str) {
        char c = *str++;
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'))) return false;
        if (++n > 32U) return false;
    }
    return n == 32U;
}
static void ProcessLine(uint32_t nowMs) {
    char *keys[MAX_FIELDS], *values[MAX_FIELDS];
    char *kind, *next, *p, *equals;
    const char *id = NULL, *cmdBoot = NULL, *action = NULL, *value = NULL, *nonce = NULL, *cmdClient = NULL;
    const char *reason = "UNSUPPORTED";
    uint8_t count = 0, i, j; uint32_t number; bool ok;
    g_hostSerialDebug.receivedFrames++;
    if (strncmp(rxLine, "SH1|", 4U)) goto malformed;
    kind = rxLine + 4; next = strchr(kind, '|');
    if (next) *next++ = '\0';
    while (next) {
        if (count == MAX_FIELDS) goto malformed;
        p = next; next = strchr(p, '|'); if (next) *next++ = '\0';
        equals = strchr(p, '='); if (!equals || equals == p || !equals[1]) goto malformed;
        *equals++ = '\0'; if (strchr(equals, '=')) goto malformed;
        if (*p < 'a' || *p > 'z' || strlen(p) > 32U) goto malformed;
        for (i = 0; p[i]; ++i)
            if (!((p[i] >= 'a' && p[i] <= 'z') || (p[i] >= '0' && p[i] <= '9') || p[i] == '_')) goto malformed;
        for (j = 0; j < count; ++j) if (!strcmp(keys[j], p)) goto malformed;
        keys[count] = p; values[count++] = equals;
    }
    for (i = 0; i < count; ++i) {
        if (!strcmp(keys[i], "boot")) cmdBoot = values[i];
        else if (!strcmp(keys[i], "id")) id = values[i];
        else if (!strcmp(keys[i], "action")) action = values[i];
        else if (!strcmp(keys[i], "value")) value = values[i];
        else if (!strcmp(keys[i], "nonce")) nonce = values[i];
        else if (!strcmp(keys[i], "client")) cmdClient = values[i];
        else goto malformed;
    }
    if (!strcmp(kind, "HELLO")) {
        if (count > 1U || (count == 1U && !nonce) || (nonce && !Nonce(nonce))) goto malformed;
        if (!connected) {
            if (nonce) strcpy(boot, nonce);
            else {
                /* Legacy clients lack a nonce. Current paired host always supplies one. */
                txLength = txPosition = 0; txBad = false;
                Put("pic-"); Number(nowMs); PutChar('-'); Number(loops);
                tx[txLength] = '\0'; strcpy(boot, tx); txLength = txPosition = 0;
            }
            connected = true; seq = 0;
        }
        /* A repeated handshake cannot make a command execute twice. A new
         * nonce starts a client session; delayed old-session commands reject. */
        if (nonce && strcmp(client, nonce)) {
            strcpy(client, nonce); haveLastCommand = false;
        }
        wantCaps = wantState = true; return;
    }
    if (!connected) { Error("HANDSHAKE_REQUIRED"); return; }
    if (!strcmp(kind, "GET") && count == 0U) { wantState = true; return; }
    if (strcmp(kind, "CMD") || count != (*client ? 5U : 4U) || !cmdBoot || !id || !action || !value) goto malformed;
    if (strlen(id) > 10U || !Unsigned(id, &number) || strlen(action) > 32U || strlen(value) > 64U) goto malformed;
    if (*client && (!cmdClient || !Nonce(cmdClient))) goto malformed;
    if (strcmp(cmdBoot, boot)) { Ack(id, false, "BOOT_MISMATCH", cmdClient); return; }
    if (*client && strcmp(cmdClient, client)) { Ack(id, false, "CLIENT_MISMATCH", cmdClient); return; }
    if (haveLastCommand && lastCommandId == number) {
        if (strcmp(lastAction, action) || strcmp(lastValue, value)) { Ack(id, false, "ID_REUSE", cmdClient); return; }
        g_hostSerialDebug.duplicateCommands++; Ack(id, lastAccepted, lastReason, cmdClient); wantState = true; return;
    }
    ok = HomeAutomation_Command(action, value, nowMs, &reason);
    lastCommandId = number; strcpy(lastAction, action); strcpy(lastValue, value);
    lastAccepted = ok; lastReason = reason; haveLastCommand = true;
    g_hostSerialDebug.commands++; Ack(id, ok, reason, cmdClient); wantState = true; return;
malformed:
    g_hostSerialDebug.rejectedFrames++; Error("MALFORMED_FRAME");
}

void HostSerial_RxISR(void) {
    uint8_t budget = 8U, next, byte;
    if (U1ERRIRbits.RXFOIF) {
        U1ERRIRbits.RXFOIF = 0; rxLost = 1; g_hostSerialDebug.uartErrors++;
    }
    while (budget-- && UART1_IsRxReady()) {
        if (U1ERRIRbits.FERIF || U1ERRIRbits.PERIF) { rxLost = 1; g_hostSerialDebug.uartErrors++; }
        byte = UART1_Read(); next = (uint8_t)(rxHead + 1U);
        if (next == rxTail) { rxLost = 1; g_hostSerialDebug.rxOverflows++; }
        else { rxRing[rxHead] = byte; rxHead = next; }
    }
}
void HostSerial_Initialize(uint32_t nowMs) {
    memset((void *)&g_hostSerialDebug, 0, sizeof g_hostSerialDebug);
    rxHead = rxTail = rxLost = 0; rxLength = txLength = txPosition = 0;
    rxDiscard = lineReady = txBad = connected = wantCaps = wantState = haveLastCommand = false;
    seq = loops = 0; nextStateMs = nowMs; boot[0] = client[0] = '\0';
    /* 64 MHz / (4 * (138+1)) = 115107.9 baud, matching MCC 115200/8N1. */
    IPR4bits.U1RXIP = 0; PIE4bits.U1RXIE = 1;
}
void HostSerial_Task(uint32_t nowMs) {
    uint8_t budget = 64U, byte, rxInterruptEnabled;
    loops++; FlushTx();
    if (rxLost) {
        /* Buffered LF may predate the lost bytes. Drop the entire old ring;
         * only a subsequently received LF may terminate the damaged line. */
        rxInterruptEnabled = PIE4bits.U1RXIE; PIE4bits.U1RXIE = 0;
        rxTail = rxHead; rxLost = 0;
        PIE4bits.U1RXIE = rxInterruptEnabled;
        rxDiscard = true; rxLength = 0; lineReady = false;
    }
    while (budget-- && !lineReady && rxTail != rxHead) {
        byte = rxRing[rxTail]; rxTail = (uint8_t)(rxTail + 1U);
        if (rxDiscard) { if (byte == '\n') rxDiscard = false; continue; }
        if (byte == '\n') {
            if (rxLength && rxLine[rxLength - 1U] == '\r') rxLength--;
            rxLine[rxLength] = '\0'; lineReady = true; break;
        }
        if ((byte < 32U && byte != '\r') || byte > 126U || rxLength >= RX_LINE_SIZE - 1U) {
            rxDiscard = true; rxLength = 0; g_hostSerialDebug.rejectedFrames++; continue;
        }
        /* CR is permitted only immediately before LF; internal CR is invalid. */
        if (rxLength && rxLine[rxLength - 1U] == '\r') {
            rxDiscard = true; rxLength = 0; g_hostSerialDebug.rejectedFrames++; continue;
        }
        rxLine[rxLength++] = (char)byte;
    }
    if (lineReady && !txLength && !rxLost) { ProcessLine(nowMs); lineReady = false; rxLength = 0; }
    if (!txLength && wantCaps) { wantCaps = false; Caps(); }
    else if (!txLength && connected && (wantState || Reached(nowMs, nextStateMs))) {
        wantState = false; State(nowMs); nextStateMs = nowMs + HOME_SERIAL_STATE_PERIOD_MS;
    }
    FlushTx();
}
