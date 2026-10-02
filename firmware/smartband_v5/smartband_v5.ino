// SmartBand v5 — capacitive food-level strap (ESP32-C3 SuperMini + LM358).
//
// This sketch wraps the original detection block (detection.cpp, unchanged) with:
//  - first-boot Wi-Fi provisioning (no hard-coded Wi-Fi password),
//  - per-device registration and a token stored in flash,
//  - baseline persistence in NVS (no re-learning after a reboot on a full jar),
//  - event reporting over HTTPS with an offline queue, heartbeat and throttled drift events,
//  - the local buzzer and recalibration button, which keep working with Wi-Fi down.
#include <WiFi.h>

#include "config.h"
#include "detection.h"
#include "net.h"
#include "provisioning.h"
#include "storage.h"

namespace {

String deviceId;
bool lastLow = false;
float lastSentBaseline = 0.0f;
unsigned long lastHeartbeat = 0, lastDrift = 0, buttonDownAt = 0;
bool buttonWasDown = false;

String makeDeviceId() {
  WiFi.mode(WIFI_STA);
  String mac = WiFi.macAddress();  // "A1:B2:C3:D4:E5:F6"
  mac.replace(":", "");
  mac.toUpperCase();
  return "sb-" + mac;
}

String num(float v) { return String(v, 2); }

void beep(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_BUZZER, HIGH);
    delay(120);
    digitalWrite(PIN_BUZZER, LOW);
    delay(120);
  }
}

void recalibrate() {
  calibrateEmpty();
  float baseline = detectionBaseline();
  storage::saveBaseline(baseline);
  lastSentBaseline = baseline;
  lastDrift = millis();
  net::postEvent("recalibration", "{\"baseline\":" + num(baseline) + "}");
  Serial.printf("[strap] recalibrated, baseline %.2f\n", baseline);
  beep(1);
}

void handleButton() {
  bool down = digitalRead(PIN_BUTTON) == LOW;
  if (down && !buttonWasDown) buttonDownAt = millis();
  if (down && millis() - buttonDownAt > FACTORY_RESET_HOLD_MS) {
    Serial.println("[strap] factory reset: clearing Wi-Fi, token and baseline");
    beep(3);
    storage::factoryReset();
    ESP.restart();
  }
  if (!down && buttonWasDown && millis() - buttonDownAt > 50) recalibrate();  // short press
  buttonWasDown = down;
}

void reportState() {
  bool low = detectionIsLow();
  if (low == lastLow) return;
  lastLow = low;
  if (low) beep(2);  // local alert, independent of Wi-Fi
  net::postEvent("state_change", String("{\"state\":\"") + (low ? "LOW" : "OK") + "\",\"gap\":" +
                                     num(detectionGap()) + ",\"baseline\":" + num(detectionBaseline()) + "}");
}

void reportDriftAndHeartbeat() {
  unsigned long now = millis();
  float baseline = detectionBaseline();
  bool bigMove = fabsf(baseline - lastSentBaseline) > DRIFT_THRESHOLD;
  if (bigMove || (now - lastDrift > DRIFT_INTERVAL_MS && baseline != lastSentBaseline)) {
    storage::saveBaseline(baseline);  // throttled flash writes
    lastSentBaseline = baseline;
    lastDrift = now;
    net::postEvent("baseline_drift", "{\"baseline\":" + num(baseline) + "}");
  }
  if (now - lastHeartbeat > HEARTBEAT_INTERVAL_MS) {
    lastHeartbeat = now;
    net::postEvent("heartbeat", "{\"gap\":" + num(detectionGap()) + ",\"baseline\":" + num(baseline) +
                                    ",\"rssi\":" + String(net::rssi()) + ",\"uptime_s\":" + String(now / 1000) + "}");
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  storage::begin();
  deviceId = makeDeviceId();
  Serial.printf("[strap] %s booting\n", deviceId.c_str());

  if (!storage::hasWifi()) provisioning::runSetupPortal(DEFAULT_BACKEND_URL);  // reboots when done

  detectionBegin();
  if (storage::hasBaseline()) {
    lastSentBaseline = storage::loadBaseline();
    detectionRestoreBaseline(lastSentBaseline);  // full jar after reboot: do NOT re-learn
    Serial.printf("[strap] baseline %.2f loaded from flash\n", lastSentBaseline);
  } else {
    recalibrate();  // first-ever boot only
  }
  lastLow = detectionIsLow();
  lastDrift = millis();

  StoredConfig cfg = storage::load();
  net::begin(cfg.backendUrl, deviceId, cfg.token);
  lastHeartbeat = millis() - HEARTBEAT_INTERVAL_MS;  // first heartbeat right away
}

void loop() {
  detectionUpdate();
  handleButton();
  reportState();
  reportDriftAndHeartbeat();
  net::loop();
  if (net::takeRecalibrateCommand()) recalibrate();
}
