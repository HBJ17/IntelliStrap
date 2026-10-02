#include "provisioning.h"

#include <DNSServer.h>
#include <WebServer.h>
#include <WiFi.h>

#include "config.h"
#include "storage.h"

namespace {

String htmlEscape(const String& in) {
  String out;
  for (char c : in) {
    switch (c) {
      case '&': out += "&amp;"; break;
      case '<': out += "&lt;"; break;
      case '>': out += "&gt;"; break;
      case '"': out += "&quot;"; break;
      default: out += c;
    }
  }
  return out;
}

String formPage(const char* defaultUrl) {
  String page =
      "<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'>"
      "<title>IntelliStrap setup</title><style>body{font-family:sans-serif;max-width:360px;margin:24px auto;"
      "padding:0 16px}input{width:100%;padding:8px;margin:4px 0 12px;box-sizing:border-box}"
      "button{padding:10px 16px}</style></head><body><h2>IntelliStrap setup</h2>"
      "<form method=post action=/save>"
      "<label>Wi-Fi name<input name=ssid required maxlength=32></label>"
      "<label>Wi-Fi password<input name=pass type=password maxlength=64></label>"
      "<label>Backend URL<input name=url required value='";
  page += htmlEscape(defaultUrl);
  page += "'></label><button type=submit>Save and restart</button></form></body></html>";
  return page;
}

}  // namespace

namespace provisioning {

void runSetupPortal(const char* defaultBackendUrl) {
  WebServer server(80);
  DNSServer dns;

  String apName = "IntelliStrap-" + WiFi.macAddress().substring(12);
  apName.replace(":", "");
  WiFi.mode(WIFI_AP);
  WiFi.softAP(apName.c_str(), SETUP_AP_PASSWORD);
  dns.start(53, "*", WiFi.softAPIP());
  Serial.printf("[setup] join Wi-Fi \"%s\" (password %s) and open http://%s/\n", apName.c_str(),
                SETUP_AP_PASSWORD, WiFi.softAPIP().toString().c_str());

  bool saved = false;
  server.on("/", HTTP_GET, [&]() { server.send(200, "text/html", formPage(defaultBackendUrl)); });
  server.on("/save", HTTP_POST, [&]() {
    String ssid = server.arg("ssid");
    String url = server.arg("url");
    if (ssid.isEmpty() || !(url.startsWith("https://") || url.startsWith("http://"))) {
      server.send(400, "text/plain", "Wi-Fi name and an http(s) backend URL are required");
      return;
    }
    while (url.endsWith("/")) url.remove(url.length() - 1);
    storage::saveWifi(ssid, server.arg("pass"), url);
    storage::clearToken();
    server.send(200, "text/html", "<p>Saved. The strap restarts and joins your Wi-Fi.</p>");
    saved = true;
  });
  server.onNotFound([&]() {  // captive-portal redirect
    server.sendHeader("Location", String("http://") + WiFi.softAPIP().toString() + "/");
    server.send(302, "text/plain", "");
  });
  server.begin();

  while (!saved) {
    dns.processNextRequest();
    server.handleClient();
    delay(5);
  }
  delay(1500);
  ESP.restart();
  while (true) {}
}

}  // namespace provisioning
