// Interface between the networking wrapper and the EXISTING SmartBand detection block.
//
// The detection block (mutual-capacitance read, adaptive baseline, hysteresis and the 5-count
// confirmation) is NOT modified. detection.cpp only exposes it through these functions.
#pragma once

void  detectionBegin();                 // pin / ADC setup from the original setup()
void  detectionUpdate();                // one pass of the original loop() body (~30 ms)
void  calibrateEmpty();                 // the original calibrateEmpty()
bool  detectionIsLow();                 // confirmed state after the 5-count confirmation
float detectionBaseline();              // current adaptive baseline
float detectionGap();                   // current gap
void  detectionRestoreBaseline(float);  // start from a baseline loaded from flash instead of re-learning
