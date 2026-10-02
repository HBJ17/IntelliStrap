// Reporting to the backend over HTTPS with a small offline queue.
#pragma once
#include <Arduino.h>

namespace net {

void begin(const String& backendUrl, const String& deviceId, const String& token);

// Non-blocking: keeps Wi-Fi up, registers if needed, and flushes the queue with backoff.
void loop();

// Queue an event; payloadJson is a JSON object such as {"state":"LOW","gap":12.4}.
void postEvent(const char* type, const String& payloadJson);

bool connected();
int rssi();

// Set when the backend returned a "recalibrate" command; cleared by the caller.
bool takeRecalibrateCommand();

}  // namespace net
