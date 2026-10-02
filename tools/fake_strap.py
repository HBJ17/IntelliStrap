#!/usr/bin/env python
"""Behave like a SmartBand strap against the backend HTTP API.

    python tools/fake_strap.py register  --id sb-TEST00000001
    python tools/fake_strap.py low       --id sb-TEST00000001
    python tools/fake_strap.py ok        --id sb-TEST00000001
    python tools/fake_strap.py recal     --id sb-TEST00000001 --baseline 800
    python tools/fake_strap.py drift     --id sb-TEST00000001 --baseline 805
    python tools/fake_strap.py heartbeat --id sb-TEST00000001 --loop 60
    python tools/fake_strap.py commands  --id sb-TEST00000001

Device tokens are kept in .fake_straps.json (repo root by default). Like the real firmware,
a `recalibrate` command in any response is answered with a `recalibration` event.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STORE = REPO_DIR / ".fake_straps.json"


def env_value(name: str, default: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    env_file = REPO_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                value = value.split(" #")[0].strip()
                if value:
                    return value
    return default


class FakeStrap:
    def __init__(self, device_id: str, url: str, store: Path):
        self.device_id = device_id
        self.url = url.rstrip("/")
        self.store_path = store
        self.store = json.loads(store.read_text()) if store.exists() else {}
        self.baseline = 800.0
        self.started = time.time()

    def _save(self) -> None:
        self.store_path.write_text(json.dumps(self.store, indent=2))

    def _headers(self) -> dict:
        entry = self.store.get(self.device_id)
        if not entry:
            sys.exit(f"{self.device_id} is not registered yet; run `register` first.")
        return {"Authorization": f"Bearer {entry['device_token']}", "X-Device-Id": self.device_id}

    def register(self, secret: str) -> None:
        r = httpx.post(f"{self.url}/api/device/register",
                       json={"device_id": self.device_id, "provision_secret": secret}, timeout=10)
        r.raise_for_status()
        data = r.json()
        self.store[self.device_id] = data
        self._save()
        print(f"registered {self.device_id}; claim code: {data['claim_code'] or '(already claimed)'}")

    def send(self, event_type: str, payload: dict) -> dict:
        r = httpx.post(f"{self.url}/api/device/events", headers=self._headers(),
                       json={"type": event_type, "payload": payload}, timeout=10)
        if r.status_code >= 400:
            sys.exit(f"{r.status_code}: {r.text}")
        data = r.json()
        print(f"{event_type} {payload} -> stored={data['stored']} commands={data['commands']}")
        self.handle_commands(data["commands"])
        return data

    def handle_commands(self, commands: list[str]) -> None:
        if "recalibrate" in commands:
            print("command: recalibrate -> calibrateEmpty()")
            self.send("recalibration", {"baseline": self.baseline})

    def poll_commands(self) -> None:
        r = httpx.get(f"{self.url}/api/device/commands", headers=self._headers(), timeout=10)
        r.raise_for_status()
        commands = r.json()["commands"]
        print(f"commands: {commands}")
        self.handle_commands(commands)

    def heartbeat(self, gap: float, rssi: int) -> None:
        self.send("heartbeat", {"gap": gap, "baseline": self.baseline, "rssi": rssi,
                                "uptime_s": int(time.time() - self.started)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["register", "low", "ok", "recal", "drift", "heartbeat", "commands"])
    parser.add_argument("--id", required=True, help="device id, e.g. sb-TEST00000001")
    parser.add_argument("--url", default=env_value("SMARTBAND_URL", "http://localhost:8000"))
    parser.add_argument("--secret", default=None, help="provisioning secret (default: DEVICE_PROVISION_SECRET)")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--baseline", type=float, default=800.0)
    parser.add_argument("--gap", type=float, default=None)
    parser.add_argument("--rssi", type=int, default=-60)
    parser.add_argument("--loop", type=float, default=0, help="heartbeat: repeat every N seconds")
    args = parser.parse_args()

    strap = FakeStrap(args.id, args.url, args.store)
    strap.baseline = args.baseline

    if args.command == "register":
        strap.register(args.secret or env_value("DEVICE_PROVISION_SECRET", "change-me"))
    elif args.command == "low":
        strap.send("state_change", {"state": "LOW", "gap": args.gap if args.gap is not None else 8.0,
                                    "baseline": args.baseline})
    elif args.command == "ok":
        strap.send("state_change", {"state": "OK", "gap": args.gap if args.gap is not None else 35.0,
                                    "baseline": args.baseline})
    elif args.command == "recal":
        strap.send("recalibration", {"baseline": args.baseline})
    elif args.command == "drift":
        strap.send("baseline_drift", {"baseline": args.baseline})
    elif args.command == "commands":
        strap.poll_commands()
    elif args.command == "heartbeat":
        gap = args.gap if args.gap is not None else 35.0
        while True:
            strap.heartbeat(gap, args.rssi)
            if not args.loop:
                break
            time.sleep(args.loop)


if __name__ == "__main__":
    main()
