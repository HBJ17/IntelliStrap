#include "net.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include "config.h"
#include "storage.h"

namespace {

const size_t QUEUE_SIZE = 20;
const unsigned long BACKOFF_MIN_MS = 2000;
const unsigned long BACKOFF_MAX_MS = 60000;
const unsigned long WIFI_RETRY_MS = 15000;

struct QueuedEvent {
  String type;
  String payload;
};

QueuedEvent queue[QUEUE_SIZE];
size_t qHead = 0, qCount = 0;

String gUrl, gDeviceId, gToken;
unsigned long nextAttemptAt = 0, backoffMs = BACKOFF_MIN_MS, lastWifiAttempt = 0;
bool recalibratePending = false;

bool enqueue(const char* type, const String& payload) {
  if (qCount == QUEUE_SIZE) {
    // Full: drop the oldest heartbeat/drift first so state changes and recalibrations survive.
    size_t victim = qHead;
    for (size_t i = 0; i < qCount; i++) {
      size_t idx = (qHead + i) % QUEUE_SIZE;
      if (queue[idx].type == "heartbeat" || queue[idx].type == "baseline_drift") { victim = idx; break; }
    }
    for (size_t idx = victim; idx != (qHead + qCount - 1) % QUEUE_SIZE; idx = (idx + 1) % QUEUE_SIZE) {
      queue[idx] = queue[(idx + 1) % QUEUE_SIZE];
    }
    qCount--;
  }
  queue[(qHead + qCount) % QUEUE_SIZE] = QueuedEvent{String(type), payload};
  qCount++;
  return true;
}

bool caConfigured() {
  return strstr(BACKEND_CA_CERT, "-----BEGIN CERTIFICATE-----") != nullptr && strstr(BACKEND_CA_CERT, "...") == nullptr;
}

// Minimal extraction of "key":"value" from a flat JSON response.
String jsonString(const String& body, const char* key) {
  String needle = String("\"") + key + "\":\"";
  int start = body.indexOf(needle);
  if (start < 0) return "";
  start += needle.length();
  int end = body.indexOf('"', start);
  return end < 0 ? "" : body.substring(start, end);
}

// Returns the HTTP status (negative on transport errors) and fills `response`.
int request(const char* method, const String& path, const String& body, String& response) {
  String url = gUrl + path;
  HTTPClient http;
  WiFiClientSecure secure;
  WiFiClient plain;
  bool ok;
  if (url.startsWith("https://")) {
    if (!caConfigured()) {
      Serial.println("[net] BACKEND_CA_CERT is not set in config.h; refusing unverified TLS");
      return -1;
    }
    secure.setCACert(BACKEND_CA_CERT);
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(plain, url);  // development only
  }
  if (!ok) return -1;
  http.setTimeout(8000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Id", gDeviceId);
  if (gToken.length()) http.addHeader("Authorization", "Bearer " + gToken);
  int code = strcmp(method, "GET") == 0 ? http.GET() : http.POST(body);
  if (code > 0) response = http.getString();
  http.end();
  return code;
}

void handleCommands(const String& response) {
  if (response.indexOf("\"recalibrate\"") >= 0) recalibratePending = true;
}

bool registerDevice() {
  String response;
  String body = "{\"device_id\":\"" + gDeviceId + "\",\"provision_secret\":\"" PROVISION_SECRET "\"}";
  int code = request("POST", "/api/device/register", body, response);
  if (code != 200) {
    Serial.printf("[net] register failed (%d)\n", code);
    return false;
  }
  gToken = jsonString(response, "device_token");
  if (gToken.isEmpty()) return false;
  storage::saveToken(gToken);
  String claim = jsonString(response, "claim_code");
  Serial.println("========================================");
  Serial.printf(" SmartBand %s registered\n", gDeviceId.c_str());
  Serial.printf(" CLAIM CODE: %s\n", claim.length() ? claim.c_str() : "(already claimed)");
  Serial.println("========================================");
  return true;
}

void scheduleRetry() {
  nextAttemptAt = millis() + backoffMs;
  backoffMs = min(backoffMs * 2, BACKOFF_MAX_MS);
}

}  // namespace

namespace net {

void begin(const String& backendUrl, const String& deviceId, const String& token) {
  gUrl = backendUrl;
  gDeviceId = deviceId;
  gToken = token;
  StoredConfig cfg = storage::load();
  WiFi.mode(WIFI_STA);
  WiFi.begin(cfg.ssid.c_str(), cfg.password.c_str());
  lastWifiAttempt = millis();
}

bool connected() { return WiFi.status() == WL_CONNECTED; }
int rssi() { return connected() ? WiFi.RSSI() : 0; }

void postEvent(const char* type, const String& payloadJson) { enqueue(type, payloadJson); }

bool takeRecalibrateCommand() {
  bool pending = recalibratePending;
  recalibratePending = false;
  return pending;
}

void loop() {
  if (!connected()) {
    if (millis() - lastWifiAttempt > WIFI_RETRY_MS) {
      WiFi.reconnect();
      lastWifiAttempt = millis();
    }
    return;
  }
  if ((long)(millis() - nextAttemptAt) < 0) return;

  if (gToken.isEmpty()) {
    if (registerDevice()) backoffMs = BACKOFF_MIN_MS; else scheduleRetry();
    return;
  }
  if (qCount == 0) return;

  QueuedEvent& ev = queue[qHead];
  String body = "{\"type\":\"" + ev.type + "\",\"payload\":" + ev.payload + "}";
  String response;
  int code = request("POST", "/api/device/events", body, response);
  if (code == 200) {
    qHead = (qHead + 1) % QUEUE_SIZE;
    qCount--;
    backoffMs = BACKOFF_MIN_MS;
    nextAttemptAt = 0;
    handleCommands(response);
  } else if (code == 401) {
    Serial.println("[net] token rejected; registering again");
    gToken = "";
    storage::clearToken();
  } else if (code == 422) {
    Serial.printf("[net] backend rejected %s event; dropping it\n", ev.type.c_str());
    qHead = (qHead + 1) % QUEUE_SIZE;
    qCount--;
  } else {
    Serial.printf("[net] post failed (%d); retrying in %lus\n", code, backoffMs / 1000);
    scheduleRetry();
  }
}

}  // namespace net
