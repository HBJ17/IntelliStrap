// Board: classic ESP32 DevKit (FQBN esp32:esp32:esp32). Fill in the 3 placeholders below before flashing.
// SmartBand v6 - v4 sketch (sensor logic UNCHANGED) + reporting to the IntelliStrap backend.
// Everything marked 'added in v6' is new; the rest is the v4 file as it was.
// SmartBand v4 - v3 sensor logic (UNCHANGED) + self-hosted WiFi dashboard
// The ESP32 runs its own web page. Open its IP address in any browser on the
// same WiFi. The dashboard only READS the state your sensor code already
// computes - it does not touch the detection logic in any way.

#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <HTTPClient.h>   // added in v6

// ================== FILL THESE IN ==================
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
// ===================================================

// ============ BACKEND (added in v6) ============
const char* BACKEND_URL      = "http://YOUR_PC_IP:8000";  // PC running uvicorn, same Wi-Fi
const char* PROVISION_SECRET = "change-me";                 // must equal DEVICE_PROVISION_SECRET in .env
// ===============================================

WebServer server(80);
Preferences prefs;

// ============================================================
//  SENSOR LOGIC BELOW - IDENTICAL TO v3, DO NOT CHANGE
// ============================================================
const int TX_PIN     = 25;
const int RX_PIN     = 34;
const int BUZZER_PIN = 26;

int SETTLE_US = 4;
int SAMPLES   = 400;

const float FOOD_ON_GAP    = 60.0;
const float FOOD_OFF_GAP   = 40.0;
const int   CONFIRM_COUNT  = 5;
const float BASELINE_ALPHA = 0.002;

const unsigned long BEEP_ON_MS  = 200;
const unsigned long BEEP_OFF_MS = 600;

float smoothed = 0;
float baseline = 0;
bool  foodAboveLine = false;
int   agree = 0;

unsigned long beepTimer = 0;
bool beepState = false;

long readCoupling() {
  long sum = 0;
  for (int i = 0; i < SAMPLES; i++) {
    digitalWrite(TX_PIN, HIGH);
    delayMicroseconds(SETTLE_US);
    int hi = analogRead(RX_PIN);
    digitalWrite(TX_PIN, LOW);
    delayMicroseconds(SETTLE_US);
    int lo = analogRead(RX_PIN);
    sum += (hi - lo);
  }
  return sum / SAMPLES;
}

void updateBuzzer() {
  if (foodAboveLine) {
    digitalWrite(BUZZER_PIN, LOW);
    beepState = false;
    return;
  }
  unsigned long now = millis();
  if (beepState && now - beepTimer >= BEEP_ON_MS) {
    beepState = false; beepTimer = now; digitalWrite(BUZZER_PIN, LOW);
  } else if (!beepState && now - beepTimer >= BEEP_OFF_MS) {
    beepState = true;  beepTimer = now; digitalWrite(BUZZER_PIN, HIGH);
  }
}

void calibrateEmpty() {
  Serial.println("Calibrating... keep the jar EMPTY.");
  float sum = 0;
  int n = 50;
  for (int i = 0; i < n; i++) { sum += readCoupling(); delay(30); }
  baseline = sum / n;
  smoothed = baseline;
  foodAboveLine = false;
  agree = 0;
  Serial.print("Empty baseline learned: ");
  Serial.println(baseline);
}
// ============================================================
//  END of unchanged sensor logic
// ============================================================

// ---- values copied out for the dashboard (do not affect logic) ----
float gGap = 0;
String jarName = "Jar 1";
volatile bool recalRequested = false;

// ---------------- Web page (HTML + CSS + JS) ----------------
const char PAGE[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartBand Pantry Monitor</title>
<style>
:root{
  --bg:#f4f6fb; --card:#ffffff; --text:#1c2333; --muted:#6b7488;
  --line:#e6e9f0; --ok:#16a34a; --ok-bg:#e7f7ed; --low:#e11d48; --low-bg:#fdeaef;
  --accent:#4f46e5; --shadow:0 10px 30px rgba(20,30,60,.08);
}
html[data-theme="dark"]{
  --bg:#0d1117; --card:#161b25; --text:#e8ecf5; --muted:#9aa4b8;
  --line:#242b38; --ok:#34d399; --ok-bg:#10261d; --low:#fb7185; --low-bg:#2a1420;
  --accent:#818cf8; --shadow:0 10px 30px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--text);transition:background .3s,color .3s;min-height:100vh}
.wrap{max-width:760px;margin:0 auto;padding:28px 18px 60px}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,var(--accent),#22d3ee);
  display:grid;place-items:center;color:#fff;font-weight:800;font-size:18px;box-shadow:var(--shadow)}
h1{font-size:20px;margin:0;font-weight:700;letter-spacing:.2px}
.sub{font-size:12px;color:var(--muted);margin-top:2px}
.toggle{border:1px solid var(--line);background:var(--card);color:var(--text);
  width:44px;height:44px;border-radius:12px;cursor:pointer;font-size:18px;box-shadow:var(--shadow)}
.grid{display:grid;gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:22px;
  box-shadow:var(--shadow);transition:border-color .3s,box-shadow .3s}
.card.low{border-color:var(--low)}
.card.ok{border-color:transparent}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px}
.name{display:flex;align-items:center;gap:8px;font-size:18px;font-weight:700}
.name input{font:inherit;font-weight:700;border:1px solid var(--line);background:var(--bg);
  color:var(--text);border-radius:8px;padding:4px 8px;width:150px}
.edit{border:none;background:transparent;color:var(--muted);cursor:pointer;font-size:15px;padding:4px;border-radius:6px}
.edit:hover{color:var(--accent)}
.pill{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;
  font-weight:700;font-size:14px}
.pill .dot{width:9px;height:9px;border-radius:50%}
.pill.ok{background:var(--ok-bg);color:var(--ok)}
.pill.ok .dot{background:var(--ok)}
.pill.low{background:var(--low-bg);color:var(--low)}
.pill.low .dot{background:var(--low);animation:pulse 1s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(225,29,72,.5)}70%{box-shadow:0 0 0 8px rgba(225,29,72,0)}100%{box-shadow:0 0 0 0 rgba(225,29,72,0)}}
.bar{height:14px;background:var(--bg);border:1px solid var(--line);border-radius:999px;
  overflow:hidden;margin:20px 0 10px}
.fill{height:100%;width:0%;border-radius:999px;transition:width .5s ease,background .4s}
.fill.ok{background:linear-gradient(90deg,#22c55e,#16a34a)}
.fill.low{background:linear-gradient(90deg,#fb923c,#e11d48)}
.meta{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-top:4px}
.actions{margin-top:18px;display:flex;gap:10px;flex-wrap:wrap}
.btn{border:1px solid var(--line);background:var(--bg);color:var(--text);padding:10px 16px;
  border-radius:12px;cursor:pointer;font-weight:600;font-size:14px}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.status{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);margin-top:18px}
.live{width:8px;height:8px;border-radius:50%;background:var(--ok)}
.live.off{background:var(--low)}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(80px);
  background:var(--card);border:1px solid var(--line);box-shadow:var(--shadow);color:var(--text);
  padding:12px 18px;border-radius:12px;font-size:14px;transition:transform .35s;z-index:9}
.toast.show{transform:translateX(-50%) translateY(0)}
</style></head><body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">SB</div>
      <div><h1>Pantry Monitor</h1><div class="sub">Live stock levels</div></div>
    </div>
    <button class="toggle" id="theme" title="Toggle theme">&#9790;</button>
  </header>
  <div class="grid" id="jars"></div>
  <div class="status"><span class="live" id="live"></span><span id="conn">Connecting...</span></div>
</div>
<div class="toast" id="toast"></div>

<script>
const jarsEl=document.getElementById('jars');
const connEl=document.getElementById('conn');
const liveEl=document.getElementById('live');
let editing=false;

// theme
const html=document.documentElement, tbtn=document.getElementById('theme');
function setTheme(t){html.setAttribute('data-theme',t);tbtn.innerHTML=(t==='dark')?'&#9728;':'&#9790;';localStorage.setItem('theme',t);}
setTheme(localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'));
tbtn.onclick=()=>setTheme(html.getAttribute('data-theme')==='dark'?'light':'dark');

function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');
  clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('show'),2600);}

function card(j,i){
  const low=j.low, cls=low?'low':'ok';
  return `<div class="card ${cls}" id="jar${i}">
    <div class="top">
      <div class="name">
        <span id="nm${i}">${j.name}</span>
        <button class="edit" onclick="editName(${i})" title="Rename">&#9998;</button>
      </div>
      <div class="pill ${cls}"><span class="dot"></span>${low?'LOW &mdash; REFILL':'STOCK OK'}</div>
    </div>
    <div class="bar"><div class="fill ${cls}" style="width:${j.fill}%"></div></div>
    <div class="meta"><span>Fill level</span><span>${j.fill}%</span></div>
    <div class="actions">
      <button class="btn" onclick="recal()">Recalibrate (empty jar)</button>
    </div>
  </div>`;
}

function render(d){
  if(editing) return;                 // don't redraw while renaming
  jarsEl.innerHTML=d.jars.map(card).join('');
}

function editName(i){
  editing=true;
  const span=document.getElementById('nm'+i), cur=span.textContent;
  span.outerHTML=`<input id="ni${i}" value="${cur}" maxlength="20">`;
  const inp=document.getElementById('ni'+i); inp.focus(); inp.select();
  const save=()=>{const v=inp.value.trim()||cur;
    fetch('/setname?name='+encodeURIComponent(v)).then(()=>{editing=false;toast('Name saved');});};
  inp.addEventListener('keydown',e=>{if(e.key==='Enter')save();if(e.key==='Escape'){editing=false;}});
  inp.addEventListener('blur',save);
}

function recal(){toast('Recalibrating... keep the jar empty');fetch('/recal');}

async function tick(){
  try{
    const r=await fetch('/status',{cache:'no-store'});
    const d=await r.json();
    render(d);
    connEl.textContent='Live  \u2022  Wi-Fi '+d.rssi+' dBm';
    liveEl.classList.remove('off');
  }catch(e){
    connEl.textContent='Reconnecting...';
    liveEl.classList.add('off');
  }
}
setInterval(tick,400); tick();
</script></body></html>
)rawliteral";

// ---------------- Web handlers ----------------
void handleRoot(){ server.send_P(200,"text/html",PAGE); }

void handleStatus(){
  bool low = !foodAboveLine;
  int fill = (int)(gGap / FOOD_ON_GAP * 100.0);
  if(fill<0) fill=0; if(fill>100) fill=100;
  String j = "{\"jars\":[{";
  j += "\"name\":\"" + jarName + "\",";
  j += "\"low\":" + String(low ? "true":"false") + ",";
  j += "\"gap\":" + String(gGap,1) + ",";
  j += "\"fill\":" + String(fill);
  j += "}],\"rssi\":" + String(WiFi.RSSI()) + "}";
  server.send(200,"application/json",j);
}

void handleSetName(){
  if(server.hasArg("name")){
    jarName = server.arg("name");
    prefs.putString("name0", jarName);
  }
  server.send(200,"text/plain","ok");
}

void handleRecal(){
  recalRequested = true;          // done in loop() so the page stays responsive
  server.send(200,"text/plain","ok");
}

// ---------------- Backend reporting (added in v6) ----------------
// Only READS the values the detection code already computes. It never changes them.
const unsigned long HEARTBEAT_MS = 3UL * 60UL * 1000UL;   // every 3 min
const unsigned long DRIFT_MS     = 15UL * 60UL * 1000UL;  // baseline drift, at most every 15 min
const unsigned long RETRY_MS     = 8000;                  // wait after a failed call

String devId, devToken;
bool  recalPending = false;      // a recalibration happened and is not reported yet
bool  heartbeatDue = true;       // first heartbeat right after registering
int   lastReportedState = -1;    // -1 unknown, 0 LOW, 1 OK
float lastSentBaseline = 0;
unsigned long tHeartbeat = 0, tDrift = 0, tNextTry = 0;

static String num(float v) { return String(v, 1); }

// Reads the string value of "key" from a flat JSON reply, or "" if missing / null.
static String jsonField(const String& s, const char* key) {
  String k = String("\"") + key + "\"";
  int i = s.indexOf(k);
  if (i < 0) return "";
  i = s.indexOf(':', i + k.length());
  if (i < 0) return "";
  int a = s.indexOf('"', i);
  if (a < 0) return "";
  int b = s.indexOf('"', a + 1);
  if (b < 0) return "";
  return s.substring(a + 1, b);
}

// Short timeouts so a slow or absent backend barely delays the sensor loop.
static int httpPost(const String& path, const String& body, String& resp, bool auth) {
  if (WiFi.status() != WL_CONNECTED) return -1;
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(1500);
  if (!http.begin(client, String(BACKEND_URL) + path)) return -1;
  http.addHeader("Content-Type", "application/json");
  if (auth) {
    http.addHeader("Authorization", "Bearer " + devToken);
    http.addHeader("X-Device-Id", devId);
  }
  int code = http.POST(body);
  resp = (code > 0) ? http.getString() : "";
  http.end();
  return code;
}

static bool registerDevice() {
  String resp;
  int code = httpPost("/api/device/register",
                      "{\"device_id\":\"" + devId + "\",\"provision_secret\":\"" + PROVISION_SECRET + "\"}",
                      resp, false);
  Serial.printf("[net] register -> %d\n", code);
  if (code != 200) return false;
  String tok = jsonField(resp, "device_token");
  if (tok.length() == 0) return false;
  devToken = tok;
  prefs.putString("tok", devToken);
  String claim = jsonField(resp, "claim_code");
  Serial.println(">> Registered as " + devId);
  if (claim.length()) Serial.println(">> CLAIM CODE: " + claim + "   (dashboard > Add strap)");
  else Serial.println(">> Already claimed by an owner.");
  return true;
}

static bool postEvent(const char* type, const String& payload) {
  String resp;
  int code = httpPost("/api/device/events", "{\"type\":\"" + String(type) + "\",\"payload\":" + payload + "}", resp, true);
  Serial.printf("[net] %s -> %d\n", type, code);
  if (code == 401) { devToken = ""; prefs.remove("tok"); }   // token rejected: register again
  if (code >= 200 && code < 300) {
    if (resp.indexOf("recalibrate") >= 0) recalRequested = true;   // command from the dashboard
    return true;
  }
  return false;
}

void reporterBegin() {
  String mac = WiFi.macAddress();
  mac.replace(":", "");
  mac.toUpperCase();
  devId = "sb-" + mac;
  devToken = prefs.getString("tok", "");
  lastSentBaseline = baseline;
  Serial.println(">> Backend device id: " + devId);
  Serial.println(">> Backend URL: " + String(BACKEND_URL));
}

// Called once per loop. Does at most one network call, and none while waiting after a failure.
void reportTick() {
  unsigned long now = millis();
  if (now < tNextTry || WiFi.status() != WL_CONNECTED) return;

  if (devToken.length() == 0) {
    if (!registerDevice()) tNextTry = now + RETRY_MS;
    return;
  }
  if (recalPending) {
    if (postEvent("recalibration", "{\"baseline\":" + num(baseline) + "}")) {
      recalPending = false; lastSentBaseline = baseline; tDrift = now;
    } else tNextTry = now + RETRY_MS;
    return;
  }
  int cur = foodAboveLine ? 1 : 0;
  if (cur != lastReportedState) {
    String body = "{\"state\":\"" + String(cur ? "OK" : "LOW") + "\",\"gap\":" + num(gGap) +
                  ",\"baseline\":" + num(baseline) + "}";
    if (postEvent("state_change", body)) lastReportedState = cur; else tNextTry = now + RETRY_MS;
    return;
  }
  float moved = fabsf(baseline - lastSentBaseline);
  if ((moved >= 5.0f && now - tDrift >= 60000UL) || (now - tDrift >= DRIFT_MS && moved > 0.5f)) {
    if (postEvent("baseline_drift", "{\"baseline\":" + num(baseline) + "}")) lastSentBaseline = baseline;
    else tNextTry = now + RETRY_MS;
    tDrift = now;
    return;
  }
  if (heartbeatDue || now - tHeartbeat >= HEARTBEAT_MS) {
    String v = "{\"gap\":" + num(gGap) + ",\"baseline\":" + num(baseline) + ",\"rssi\":" + String(WiFi.RSSI()) +
               ",\"uptime_s\":" + String(now / 1000) + "}";
    if (postEvent("heartbeat", v)) { heartbeatDue = false; tHeartbeat = now; } else tNextTry = now + RETRY_MS;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(TX_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  delay(300);

  prefs.begin("smartband", false);
  jarName = prefs.getString("name0", "Jar 1");

  // WiFi
  Serial.print("Connecting to WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status()!=WL_CONNECTED && millis()-t0 < 15000){ delay(400); Serial.print("."); }
  Serial.println();
  if(WiFi.status()==WL_CONNECTED){
    Serial.print(">> Dashboard ready. Open this in your browser:  http://");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(">> WiFi failed - sensor + buzzer still work, dashboard offline.");
  }

  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/setname", handleSetName);
  server.on("/recal", handleRecal);
  server.begin();

  calibrateEmpty();   // keep the jar EMPTY at power-on
  recalPending = true;  // added in v6: report this first calibration
  reporterBegin();      // added in v6
}

void loop() {
  server.handleClient();

  if(recalRequested){ recalRequested=false; calibrateEmpty(); recalPending=true; }  // recalPending: added in v6

  // ---- v3 detection, unchanged ----
  long raw = readCoupling();
  smoothed = 0.85 * smoothed + 0.15 * raw;
  float gap = baseline - smoothed;

  if (!foodAboveLine && gap > FOOD_ON_GAP) {
    if (++agree >= CONFIRM_COUNT) { foodAboveLine = true;  agree = 0; Serial.println(">> Food above line - buzzer OFF"); }
  } else if (foodAboveLine && gap < FOOD_OFF_GAP) {
    if (++agree >= CONFIRM_COUNT) { foodAboveLine = false; agree = 0; Serial.println(">> Food below line - ALERT, buzzer ON"); }
  } else {
    agree = 0;
  }

  if (gap < FOOD_OFF_GAP) {
    baseline = baseline + BASELINE_ALPHA * (smoothed - baseline);
  }

  updateBuzzer();
  // ---- end unchanged block ----

  gGap = gap;          // copy out for the dashboard (read-only, no effect on logic)
  reportTick();        // added in v6: report to the backend (read-only)
  delay(30);
}
