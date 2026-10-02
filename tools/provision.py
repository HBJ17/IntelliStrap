#!/usr/bin/env python
"""Pre-register straps at the bench and print claim-code stickers.

    python tools/provision.py --mac A1:B2:C3:D4:E5:F6
    python tools/provision.py --mac A1B2C3D4E5F6 --mac 001122334455 --url https://smartband.example.com

Registering here fixes the strap's claim code. When the strap later registers itself on first
boot (with the same provisioning secret), the backend issues it a fresh token but keeps that
claim code, so the sticker stays valid. The token printed by this tool is discarded.
"""
import argparse
import re
import sys

import httpx

from fake_strap import env_value


def device_id_from_mac(mac: str) -> str:
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
    if len(hex_only) != 12:
        raise ValueError(f"not a MAC address: {mac}")
    return f"sb-{hex_only}"


def sticker(device_id: str, claim_code: str | None) -> str:
    code = claim_code or "(already claimed)"
    lines = ["SmartBand strap", f"ID:   {device_id}", f"CODE: {code}", "Claim at your SmartBand dashboard"]
    width = max(len(line) for line in lines) + 2
    border = "+" + "-" * width + "+"
    return "\n".join([border, *(f"| {line.ljust(width - 1)}|" for line in lines), border])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mac", action="append", default=[], help="strap MAC address (repeatable)")
    parser.add_argument("--id", action="append", default=[], help="device id instead of a MAC (repeatable)")
    parser.add_argument("--url", default=env_value("SMARTBAND_URL", "http://localhost:8000"))
    parser.add_argument("--secret", default=None, help="provisioning secret (default: DEVICE_PROVISION_SECRET)")
    args = parser.parse_args()

    try:
        device_ids = [device_id_from_mac(m) for m in args.mac] + args.id
    except ValueError as exc:
        sys.exit(str(exc))
    if not device_ids:
        parser.error("give at least one --mac or --id")
    secret = args.secret or env_value("DEVICE_PROVISION_SECRET", "change-me")

    for device_id in device_ids:
        r = httpx.post(f"{args.url.rstrip('/')}/api/device/register",
                       json={"device_id": device_id, "provision_secret": secret}, timeout=10)
        if r.status_code != 200:
            print(f"{device_id}: failed ({r.status_code} {r.text})", file=sys.stderr)
            continue
        print(sticker(device_id, r.json()["claim_code"]))
        print()


if __name__ == "__main__":
    main()
