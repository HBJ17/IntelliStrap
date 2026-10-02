"""Demo data: `python -m app.seed [--reset]`.

Creates one owner, one opted-in shop, a priced catalog and four straps pre-claimed to
Rice, Toor dal, Poha and Sago. Device tokens are written to the repo's .fake_straps.json
so tools/fake_strap.py can drive the seeded straps straight away.
"""
import argparse
import json

from . import clock, db
from .config import REPO_DIR
from .models import Base, Item, Owner, Shop, Strap, StrapState
from .security import hash_token, new_device_token

FAKE_STRAP_STORE = REPO_DIR / ".fake_straps.json"

CATALOG = [
    ("Rice", "kg", "1 kg", 60),
    ("Toor dal", "kg", "1 kg", 150),
    ("Poha", "kg", "1 kg", 90),
    ("Sago", "kg", "1 kg", 110),
    ("Sugar", "kg", "1 kg", 55),
    ("Tea", "g", "250 g", 120),
]

STRAPS = [
    ("sb-DEMO00000001", "Rice jar", "Rice"),
    ("sb-DEMO00000002", "Dal jar", "Toor dal"),
    ("sb-DEMO00000003", "Poha jar", "Poha"),
    ("sb-DEMO00000004", "Sago jar", "Sago"),
]


def seed(reset: bool = False) -> bool:
    db.init_db()
    if reset:
        engine = db.get_engine()
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                if table.name != "alembic_version":
                    conn.execute(table.delete())

    with db.session_scope() as session:
        if session.query(Owner).first() is not None:
            print("Database already has an owner; nothing to do (use --reset to start over).")
            return False

        shop = Shop(name="Sharma General Store", whatsapp_number="+910000000002", opted_in=True)
        owner = Owner(name="Demo Home", whatsapp_number="+910000000001", list_threshold_inr=400, shop=shop)
        session.add_all([shop, owner])
        items = {name: Item(name=name, unit=unit, pack_size=pack, price_inr=price)
                 for name, unit, pack, price in CATALOG}
        session.add_all(items.values())
        session.flush()

        now = clock.now()
        tokens: dict[str, str] = {}
        for device_id, display_name, item_name in STRAPS:
            token = new_device_token()
            tokens[device_id] = token
            session.add(Strap(
                device_id=device_id, owner_id=owner.id, display_name=display_name,
                item_id=items[item_name].id, device_token_hash=hash_token(token),
                state=StrapState.OK, state_since=now, baseline=800.0, gap=35.0, rssi=-55, last_seen=now,
            ))

    store = json.loads(FAKE_STRAP_STORE.read_text()) if FAKE_STRAP_STORE.exists() else {}
    for device_id, token in tokens.items():
        store[device_id] = {"device_token": token, "claim_code": None}
    FAKE_STRAP_STORE.write_text(json.dumps(store, indent=2))
    print(f"Seeded owner, shop, {len(CATALOG)} items and {len(STRAPS)} straps.")
    print(f"Device tokens for the demo straps saved to {FAKE_STRAP_STORE}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete all data first")
    seed(reset=parser.parse_args().reset)


if __name__ == "__main__":
    main()
