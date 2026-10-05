// ============================================================================
//  SmartBand v5 detection block, copied UNCHANGED from code/SmartBand_v5_c3.ino
//  ("SENSOR LOGIC - IDENTICAL TO v4" and the "v4 detection, unchanged" loop block).
//  Only the thin accessors at the bottom are new.
// ============================================================================
#include <Arduino.h>
#include "detection.h"

// ---------------- Pins ----------------
const int TX_PIN     = 4;
const int RX_PIN     = 1;

// ============================================================
//  SENSOR LOGIC - IDENTICAL TO v4, DO NOT CHANGE
// ============================================================
int SETTLE_US = 4;
int SAMPLES   = 400;

const float FOOD_ON_GAP    = 60.0;
const float FOOD_OFF_GAP   = 40.0;
const int   CONFIRM_COUNT  = 5;
const float BASELINE_ALPHA = 0.002;

float smoothed = 0;
float baseline = 0;
bool  foodAboveLine = false;   // true = OK, false = LOW
int   agree = 0;

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

static float gGap = 0;

// --- accessors ---------------------------------------------------------------
void detectionBegin() {
  // pin / ADC setup from the original setup()
  pinMode(TX_PIN, OUTPUT);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
}

void detectionUpdate() {
  // ---- v4 detection, unchanged ----
  long raw = readCoupling();
  smoothed = 0.85 * smoothed + 0.15 * raw;
  float gap = baseline - smoothed;

  if (!foodAboveLine && gap > FOOD_ON_GAP) {
    if (++agree >= CONFIRM_COUNT) { foodAboveLine = true;  agree = 0; Serial.println(">> Food above line - OK"); }
  } else if (foodAboveLine && gap < FOOD_OFF_GAP) {
    if (++agree >= CONFIRM_COUNT) { foodAboveLine = false; agree = 0; Serial.println(">> Food below line - LOW"); }
  } else {
    agree = 0;
  }

  if (gap < FOOD_OFF_GAP) {
    baseline = baseline + BASELINE_ALPHA * (smoothed - baseline);
  }
  // ---- end unchanged block ----

  gGap = gap;
  delay(30);
}

bool detectionIsLow() {
  return !foodAboveLine;
}

float detectionBaseline() {
  return baseline;
}

float detectionGap() {
  return gGap;
}

void detectionRestoreBaseline(float value) {
  // as in the original setup(): load from flash, start from the real reading
  baseline = value;
  smoothed = (float)readCoupling();
  foodAboveLine = (baseline - smoothed) > FOOD_ON_GAP;
}
