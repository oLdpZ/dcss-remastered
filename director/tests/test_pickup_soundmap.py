import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from router import Router

HERE = os.path.dirname(__file__)
SOUNDMAP_PATH = os.path.join(os.path.dirname(HERE), "soundmap.json")

PICKUP_TOKENS = [
    "evt__pickup_weapon", "evt__pickup_armour", "evt__pickup_missile",
    "evt__pickup_scroll", "evt__pickup_potion", "evt__pickup_ring",
    "evt__pickup_amulet", "evt__pickup_wand", "evt__pickup_book",
    "evt__pickup_staff", "evt__pickup_misc", "evt__pickup_talisman",
    "evt__pickup_gold",
]

def _load():
    with open(SOUNDMAP_PATH, encoding="utf-8") as f:
        return json.load(f)

def test_all_pickup_tokens_registered_as_item_sfx():
    r = Router(_load())
    for tok in PICKUP_TOKENS:
        acts = r.route(tok)
        assert len(acts) == 1, f"{tok} non instradato"
        assert acts[0]["op"] == "sfx", f"{tok} op={acts[0]['op']}"
        assert acts[0]["group"] == "item", f"{tok} group={acts[0]['group']}"

def test_generic_pickup_fallback_still_present():
    acts = Router(_load()).route("evt__pickup")
    assert len(acts) == 1 and acts[0]["op"] == "sfx"
