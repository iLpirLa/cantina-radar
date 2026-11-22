import time
from pathlib import Path

import pytest

from cwmon.catawiki import parse_listing_html, parse_live_item, parse_estimate
from cwmon.config import load_config
from cwmon.db import DB
from cwmon.parser import parse_title
from cwmon.valuation import Valuator, Reference, lot_cost, max_bid_for

COSTS = {"commissione_pct": 0.09, "commissione_fissa": 3.0, "spedizione_lotto": 25.0, "spedizione_extra_bottiglia": 2.0}
FIX = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------------ parser
@pytest.mark.parametrize("title,vintage,producer,cuvee,app,bottles,eq,ok", [
    ("2008 Château Lynch Bages - Pauillac 5ème Grand Cru Classé - 1 Bottle (0.75L)", 2008, "Château Lynch Bages", "", "Pauillac 5ème Grand Cru Classé", 1, 1.0, True),
    ("2012 Fritz Haag, GK - Brauneberger Juffer Sonnenuhr - Mosel Auslese, Goldkapsel - 2 Bottles (0.75L)", 2012, "Fritz Haag", "GK", "Brauneberger Juffer Sonnenuhr", 2, 2.0, True),
    ("2015 Tenuta San Guido, Sassicaia - Bolgheri - 1 Magnum (1.5L)", 2015, "Tenuta San Guido", "Sassicaia", "Bolgheri", 1, 2.0, True),
    ("2016 Gaja - Barbaresco - 2 Bottles (0.75L) & 1 Magnum (1.5L)", 2016, "Gaja", "", "Barbaresco", 3, 4.0, True),
    ("2019 Weingut Weegmüller - Weissburgunder - Pfalz - 12 Bottles (0.75L)", 2019, "Weingut Weegmüller", "", "Weissburgunder", 12, 12.0, True),
    ("Domaine Vincent Paris ; Domaine Paul Jaboulet Ainé - Rhône - 4 Bottles (0.75L)", None, None, None, "Rhône", 4, 4.0, False),
    ("2010 & 2011 Château Margaux - Margaux - 2 Bottles (0.75L)", None, None, None, "Margaux", 2, 2.0, False),
    ("2000 Château d'Yquem - Sauternes 1er Cru Supérieur - 1 Half Bottle (0.375L)", 2000, "Château d'Yquem", "", "Sauternes 1er Cru Supérieur", 1, 0.5, True),
])
def test_parse_title(title, vintage, producer, cuvee, app, bottles, eq, ok):
    p = parse_title(title)
    assert p.vintage == vintage
    if producer is not None:
        assert p.producer == producer and p.cuvee == cuvee
    assert p.appellation == app
    assert p.bottles == bottles and p.bottle_eq == eq
    assert p.ok is ok


def test_nv_and_slug():
    p = parse_title("NV Bollinger, Special Cuvée - Champagne Brut - 6 Bottles (0.75L)")
    assert p.nv and p.vintage is None and p.ok
    s = parse_title("", slug="2008-chateau-lynch-bages-pauillac-5eme-grand-cru-classe-1-bottle-0-75l")
    assert s.vintage == 2008 and s.bottles == 1 and s.bottle_eq == 1.0 and s.ok


def test_same_wine_same_key():
    a = parse_title("2008 Château Lynch Bages - Pauillac 5ème Grand Cru Classé - 1 Bottle (0.75L)")
    b = parse_title("2010 Chateau Lynch-Bages - Pauillac Grand Cru Classé - 6 Bottles (0.75L)")
    assert a.wine_key == b.wine_key


# --------------------------------------------------------------- catawiki
def test_listing_html_fixture():
    lots = parse_listing_html((FIX / "categoria.html").read_text(encoding="utf-8"))
    by_id = {l["id"]: l for l in lots}
    assert 108491008 in by_id and 108385617 in by_id
    assert by_id[108491008]["title"].startswith("2008 Château Lynch Bages")
    assert "Current bid" not in by_id[108491008]["title"]
    assert by_id[108385617]["image_url"].endswith(".jpg")


@pytest.mark.parametrize("item", [
    {"id": 1, "liveLot": {"bid": {"EUR": 120, "USD": 1}, "biddingEndTime": int((time.time() + 3600) * 1000),
                          "reservePriceMet": True, "closeStatus": "open"}},
    {"id": 1, "current_bid_amount": "120", "bidding_end_time": "2099-01-01T20:00:00Z", "reserve_price_met": True},
])
def test_live_item_open(item):
    d = parse_live_item(item)
    assert d["id"] == 1 and d["current_bid"] == 120 and d["end_time"] and d["final"] == 0 and d["reserve_met"] == 1


def test_live_item_closed():
    d = parse_live_item({"id": 2, "bid": {"EUR": 80}, "bidding_end_time": int(time.time()) - 3600,
                         "close_status": "closed", "reserve_price_met": False, "reserve_price_set": True})
    assert d["final"] == 1 and d["sold"] == 0
    d = parse_live_item({"id": 3, "bid": {"EUR": 80}, "bidding_end_time": int(time.time()) - 3600, "close_status": "sold"})
    assert d["final"] == 1 and d["sold"] == 1


@pytest.mark.parametrize("html,exp", [
    ('{"expertEstimate":{"min":{"EUR":120},"max":{"EUR":150}}}', (120, 150)),
    ('{"estimate_min":120,"x":1,"estimate_max":150}', (120, 150)),
    ("<span>Expert&#x27;s estimate</span><b>€ 1.200 - € 1.500</b>", (1200, 1500)),
    ("Stima dell'esperto € 90 - € 110", (90, 110)),
    ("nessuna stima", (None, None)),
])
def test_estimate(html, exp):
    assert parse_estimate(html) == exp


# --------------------------------------------------------------- valutazione
def test_cost_and_max_bid_roundtrip():
    total, per = lot_cost(100, 1.0, 1, COSTS)
    assert total == pytest.approx(100 * 1.09 + 3 + 25)
    mb = max_bid_for(per, 1.0, 1, COSTS)
    assert mb == 100


def _lot(**kw):
    p = parse_title(kw.pop("title"))
    base = {"id": kw.pop("id", 1), "wine_key": p.wine_key, "wine_name": p.wine_name, "vintage": p.vintage, "nv": int(p.nv),
            "bottle_eq": p.bottle_eq, "bottles": p.bottles, "parse_ok": int(p.ok), "estimate_low": None,
            "estimate_high": None, "current_bid": 0}
    base.update(kw)
    return base


def test_valuation_reference_and_history():
    title = "2008 Château Lynch Bages - Pauillac 5ème Grand Cru Classé - 1 Bottle (0.75L)"
    hist = [dict(_lot(title=title, id=i, current_bid=b), end_time=0) for i, b in [(10, 120), (11, 125), (12, 118)]]
    refs = [Reference("Lynch Bages Pauillac", "lynch bages pauillac", 2008, 140.0, "ws")]
    v = Valuator(refs, hist, COSTS)
    s = v.score(_lot(title=title, current_bid=60), target_discount=0.25)
    assert s["confidence"] >= 0.85
    assert 125 < s["market_per_bottle"] < 145
    assert s["discount"] > 0.3
    # offerta massima coerente con la soglia
    _, per = lot_cost(s["max_bid"], 1.0, 1, COSTS)
    assert per <= s["market_per_bottle"] * 0.75 + 1.1


def test_valuation_wrong_vintage_reference_ignored():
    refs = [Reference("Lynch Bages", "lynch bages", 2005, 200.0, "ws")]
    v = Valuator(refs, [], COSTS)
    assert v.score(_lot(title="2008 Château Lynch Bages - Pauillac - 1 Bottle (0.75L)", current_bid=50), 0.25) is None


def test_mixed_lot_uses_estimate_only():
    v = Valuator([], [], COSTS)
    s = v.score(_lot(title="Domaine A ; Domaine B - Rhône - 4 Bottles (0.75L)", current_bid=50, estimate_low=100,
                     estimate_high=120), 0.25)
    assert s["value_source"] == "stima esperto"


# --------------------------------------------------------------- end-to-end
class FakeTG:
    enabled = True
    chat_id = "1"

    def __init__(self):
        self.sent = []

    def send(self, text, buttons=None, chat_id=None):
        self.sent.append(text)
        return {"ok": True}

    def updates(self, offset, timeout=0):
        return [{"update_id": 5, "message": {"chat": {"id": 1}, "text": "/soglia 40"}},
                {"update_id": 6, "message": {"chat": {"id": 999}, "text": "/pausa"}}]


def test_alert_flow(tmp_path):
    from cwmon import monitor
    cfg = load_config()
    cfg["db_path"] = str(tmp_path / "t.db")
    db = DB(cfg["db_path"])
    title = "2015 Tenuta San Guido, Sassicaia - Bolgheri - 1 Bottle (0.75L)"
    p = parse_title(title)
    row = {"id": 42, "title": title, "slug": "x", "category_id": 443, "image_url": None, "producer": p.producer,
           "cuvee": p.cuvee, "appellation": p.appellation, "vintage": p.vintage, "nv": 0, "mixed": 0, "bottles": 1,
           "bottle_eq": 1.0, "size_l": 0.75, "wine_name": p.wine_name, "wine_key": p.wine_key, "parse_ok": 1}
    db.upsert_listing(row)
    db.update_live(42, {"current_bid": 120, "end_time": int(time.time()) + 3600, "final": 0})
    db.commit()
    monitor.score_all(cfg, db)  # riferimento d'esempio Sassicaia 2015 = 330 €
    tg = FakeTG()
    assert monitor.send_alerts(cfg, db, tg) == 1
    assert "Sassicaia" in tg.sent[0] and "Offerta massima" in tg.sent[0]
    assert monitor.send_alerts(cfg, db, tg) == 0  # nessun duplicato
    # comandi: solo la chat autorizzata viene ascoltata
    monitor.handle_commands(cfg, db, tg)
    ov = db.get("overrides")
    assert ov["sconto_minimo"] == pytest.approx(0.40) and "pausa" not in ov
    assert db.get("tg_offset") == 7


def test_collect_end_to_end(tmp_path, monkeypatch):
    """Ciclo completo con rete simulata: pagina categoria (fixture) + endpoint live + pagina lotto."""
    from cwmon import monitor
    from cwmon.catawiki import CatawikiClient

    html = (FIX / "categoria.html").read_text(encoding="utf-8")
    end = int(time.time()) + 2 * 3600

    class Resp:
        def __init__(self, text="", js=None, code=200):
            self.text, self._js, self.status_code = text, js, code

        def json(self):
            return self._js

    def fake_get(self, url, params=None, accept_json=False):
        self.requests_made += 1
        if "/c/" in url:
            return Resp(html if (params or {}).get("page", 1) == 1 else "<html></html>")
        if "lots/live" in url:
            ids = [int(i) for i in params["ids"].split(",")]
            return Resp(js={"lots": [{"id": i, "bid": {"EUR": 40}, "bidding_end_time": end * 1000,
                                      "close_status": "open"} for i in ids]})
        return Resp('{"expertEstimate":{"min":{"EUR":110},"max":{"EUR":140}}}')

    monkeypatch.setattr(CatawikiClient, "_get", fake_get)
    cfg = load_config()
    cfg["db_path"] = str(tmp_path / "e2e.db")
    cfg["catawiki"]["categories"] = [443]
    cfg["catawiki"]["days_ahead"] = 1
    cfg["dashboard"]["cartella"] = str(tmp_path / "site")
    summary = monitor.run_once(cfg)
    assert summary["scoperti"] == 3 and summary["live"] == 3 and summary["pagine_lotto"] == 3
    db = DB(cfg["db_path"])
    lynch = db.conn.execute("SELECT * FROM lots WHERE id=108491008").fetchone()
    assert lynch["vintage"] == 2008 and lynch["current_bid"] == 40 and lynch["estimate_low"] == 110
    assert lynch["discount"] > 0.3  # riferimento d'esempio 135 € + stima esperto
    assert (tmp_path / "site" / "index.html").exists()


def test_ingest_from_browser(tmp_path):
    from cwmon.server import ingest, pending_ids, _fallback_from_text
    cfg = load_config()
    cfg["db_path"] = str(tmp_path / "b.db")
    cfg["dashboard"]["cartella"] = str(tmp_path / "site")
    db = DB(cfg["db_path"])
    end = int(time.time()) + 3600
    payload = {
        "url": "https://www.catawiki.com/it/c/443-vino",
        "lots": [
            {"id": 1001, "slug": "x", "title": "2015 Tenuta San Guido, Sassicaia - Bolgheri - 1 Bottle (0.75L)", "img": "", "text": ""},
            {"id": 1002, "slug": "", "title": "2016 Gaja - Barbaresco - 1 Bottle (0.75L)",
             "text": "2016 Gaja - Barbaresco - 1 Bottle (0.75L) Offerta attuale € 1.150 2 ore 5 min"},
        ],
        "live": [{"id": 1001, "bid": {"EUR": 120}, "bidding_end_time": end * 1000, "close_status": "open"}],
        "live_status": 200,
    }
    res = ingest(cfg, db, payload)
    assert res["lotti"] == 2 and res["nuovi"] == 2 and res["con_offerta"] == 1 and res["occasioni"] == 1
    gaja = db.conn.execute("SELECT * FROM lots WHERE id=1002").fetchone()
    assert gaja["current_bid"] == 1150 and gaja["category_id"] == 443
    assert abs(gaja["end_time"] - (time.time() + 2 * 3600 + 300)) < 60
    assert set(pending_ids(db)) == {1001, 1002}
    assert (tmp_path / "site" / "index.html").exists()
    assert _fallback_from_text("Current bid € 45 1 day left", "") ["current_bid"] == 45


def test_bookmarklet_generation(tmp_path):
    import urllib.parse
    from cwmon.server import write_static
    cfg = load_config()
    cfg["dashboard"]["cartella"] = str(tmp_path / "site")
    site = write_static(cfg, 8000)
    html = (site / "installa.html").read_text(encoding="utf-8")
    assert "javascript:" in html and "__ORIGIN__" not in html and "__PAGES__" not in html
    assert (site / "ingest.html").exists()
