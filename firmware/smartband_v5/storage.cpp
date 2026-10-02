#include "storage.h"

#include <Preferences.h>

namespace {
Preferences prefs;
const char* NS = "smartband";
}

namespace storage {

void begin() { prefs.begin(NS, false); }

StoredConfig load() {
  StoredConfig c;
  c.ssid = prefs.getString("ssid", "");
  c.password = prefs.getString("pass", "");
  c.backendUrl = prefs.getString("url", "");
  c.token = prefs.getString("token", "");
  return c;
}

bool hasWifi() { return prefs.getString("ssid", "").length() > 0; }

void saveWifi(const String& ssid, const String& password, const String& backendUrl) {
  prefs.putString("ssid", ssid);
  prefs.putString("pass", password);
  prefs.putString("url", backendUrl);
}

void saveToken(const String& token) { prefs.putString("token", token); }
void clearToken() { prefs.remove("token"); }

bool hasBaseline() { return prefs.isKey("baseline"); }
float loadBaseline() { return prefs.getFloat("baseline", 0.0f); }
void saveBaseline(float baseline) { prefs.putFloat("baseline", baseline); }

void factoryReset() { prefs.clear(); }

}  // namespace storage
