// Persistent settings in NVS (ESP32 Preferences).
#pragma once
#include <Arduino.h>

struct StoredConfig {
  String ssid;
  String password;
  String backendUrl;
  String token;
};

namespace storage {
void begin();
StoredConfig load();
bool hasWifi();
void saveWifi(const String& ssid, const String& password, const String& backendUrl);
void saveToken(const String& token);
void clearToken();

bool hasBaseline();
float loadBaseline();
void saveBaseline(float baseline);

void factoryReset();  // wipes Wi-Fi, backend URL, token and baseline
}  // namespace storage
