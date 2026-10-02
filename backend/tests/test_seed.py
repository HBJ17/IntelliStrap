import json

from app import seed as seed_module
from app.models import Item, Owner, Strap


def test_seed_creates_demo_data(tmp_path, monkeypatch, session):
    monkeypatch.setattr(seed_module, "FAKE_STRAP_STORE", tmp_path / "store.json")
    monkeypatch.setattr(seed_module.db, "init_db", lambda: None)
    assert seed_module.seed() is True
    assert seed_module.seed() is False  # idempotent

    owner = session.query(Owner).one()
    assert owner.list_threshold_inr == 400 and owner.shop.opted_in
    prices = {i.name: i.price_inr for i in session.query(Item)}
    assert prices["Rice"] == 60 and len(prices) == 6
    [strap] = session.query(Strap).all()  # a single demo jar
    assert strap.owner_id == owner.id and strap.item.name == "Rice"
    store = json.loads((tmp_path / "store.json").read_text())
    assert set(store) == {strap.device_id}
