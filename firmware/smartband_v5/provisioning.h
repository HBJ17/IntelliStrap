// First-boot setup: temporary hotspot + captive form for Wi-Fi and backend URL.
#pragma once

namespace provisioning {
// Blocks until the owner submits the form, saves it to NVS and reboots.
[[noreturn]] void runSetupPortal(const char* defaultBackendUrl);
}
