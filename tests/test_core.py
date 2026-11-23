import json
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
    assert "Sassicaia" in tg.sent[0] and "Offri al massimo" in tg.sent[0]
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
    assert summary["scoperti"] == 5 and summary["live"] == 5 and summary["pagine_lotto"] == 5
    db = DB(cfg["db_path"])
    lynch = db.conn.execute("SELECT * FROM lots WHERE id=108491008").fetchone()
    assert lynch["vintage"] == 2008 and lynch["current_bid"] == 40 and lynch["estimate_low"] == 110
    assert lynch["discount"] > 0.3  # riferimento d'esempio 135 € + stima esperto
    assert (tmp_path / "site" / "index.html").exists()


def test_ingest_from_browser(tmp_path):
    from cwmon.server import ingest, pending_ids, _fallback_from_text
    cfg = load_config()
    cfg["_no_background"] = True
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


def test_clean_title_and_classify():
    from cwmon.server import clean_title, classify
    assert clean_title("2022 Catena Zapata Malbec Argentino - Mendoza - 3 Bottiglie (0,75 L)Offerta attuale250 €Mancano 20 ore") \
        == "2022 Catena Zapata Malbec Argentino - Mendoza - 3 Bottiglie (0,75 L)"
    assert clean_title("Jack Daniel's - McLaren Halo MK1 - 1 litre Offerta attuale 725 €") == "Jack Daniel's - McLaren Halo MK1 - 1 litre"
    assert classify("caol ila 25 years old 70cl", 720, False) == 437
    assert classify("Hennessy XO - Cognac - 70cl", 720, False) == 965
    assert classify("2023 Tenuta San Guido - Sassicaia - Bolgheri - 1 Magnum (1,5 L)", 720, True) == 443
    assert classify("2012 Dom Pérignon - Champagne Brut - 1 Bottiglia (0,75 L)", 720, True) == 961
    assert classify("qualsiasi", 443, False) == 443
    p = parse_title("2022 Catena Zapata Malbec Argentino - Mendoza - 3 Bottiglie (0,75 L)")
    assert p.bottles == 3 and p.bottle_eq == 3 and p.vintage == 2022 and p.ok


def test_settings_reference_and_csv(tmp_path):
    from cwmon.server import update_settings, add_reference, import_history_csv
    import shutil
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(Path(__file__).parent.parent / "config.yaml", root / "config.yaml")
    (root / "riferimenti.csv").write_text("vino,annata,prezzo_bottiglia,fonte,punteggio,note\n", encoding="utf-8")
    cfg = load_config(root / "config.yaml")
    cfg["db_path"] = str(root / "data" / "t.db")
    db = DB(cfg["db_path"])
    title = "2016 Bruno Giacosa, Falletto - Barolo - 1 Bottle (0.75L)"
    p = parse_title(title)
    db.upsert_listing({"id": 7, "title": title, "slug": "x", "category_id": 443, "image_url": None, "producer": p.producer,
                       "cuvee": p.cuvee, "appellation": p.appellation, "vintage": 2016, "nv": 0, "mixed": 0, "bottles": 1,
                       "bottle_eq": 1.0, "size_l": 0.75, "wine_name": p.wine_name, "wine_key": p.wine_key, "parse_ok": 1})
    db.update_live(7, {"current_bid": 90, "end_time": int(time.time()) + 3600, "final": 0})
    db.commit()
    s = update_settings(cfg, db, {"sconto_minimo": 0.3, "punteggio_minimo": 4.2, "budget_massimo": 500})
    assert s["sconto_minimo"] == 0.3 and s["punteggio_minimo"] == 4.2
    r = add_reference(cfg, db, {"lot_id": 7, "prezzo": "200", "punteggio": "JS 97"})
    assert r["sconto"] > 0.3 and r["valore"] == 200
    lot = db.conn.execute("SELECT * FROM lots WHERE id=7").fetchone()
    assert lot["market_per_bottle"] == 200 and lot["critic_score"] == "JS 97" and lot["value_source"] == "tuo valore"
    assert "Giacosa" in (root / "data" / "valori_inseriti.csv").read_text(encoding="utf-8")
    # il valore manuale vince anche su altre fonti (qui un riferimento CSV diverso) e si può correggere
    (root / "riferimenti.csv").write_text("Bruno Giacosa Falletto Barolo,2016,500,x,,\n", encoding="utf-8")  # senza intestazione
    add_reference(cfg, db, {"lot_id": 7, "prezzo": "180"})
    assert db.conn.execute("SELECT market_per_bottle FROM lots WHERE id=7").fetchone()[0] == 180
    res = import_history_csv(cfg, db, "titolo;prezzo_finale;data\n" + title + ";150;01/11/2026\nriga senza prezzo;;\n")
    assert res == {"importati": 1, "scartati": 1}
    assert len(db.sold_history()) == 1


def test_vivino_parse_and_match():
    from cwmon.vivino import parse_search_html, best_match
    html = """<div class="card"><div class="wine-card__content">
      <span class="wine-card__name"><a href="/tenuta-san-guido-sassicaia/w/1093?year=2015"><span class="bold">Tenuta San Guido Sassicaia 2015</span></a></span>
      <div class="wine-card__region">Bolgheri Sassicaia, Italia</div>
      <div class="average__number">4,7</div><p class="text-micro">(8.163 valutazioni)</p><span>€ 329,00</span></div></div>
      <div class="card"><a href="/x/w/55?year=2012">Altro vino 2012</a><div class="average__number">3,9</div><p>(120 ratings)</p></div>"""
    hits = parse_search_html(html)
    assert len(hits) == 2
    h = hits[0]
    assert h.rating == 4.7 and h.count == 8163 and h.year == 2015 and h.price == 329 and h.currency == "EUR"
    p = parse_title("2015 Tenuta San Guido, Sassicaia - Bolgheri - 1 Bottle (0.75L)")
    lot = {"wine_name": p.wine_name, "vintage": 2015, "producer": p.producer, "cuvee": p.cuvee, "appellation": p.appellation}
    assert best_match(lot, hits).rating == 4.7


def test_vivino_name_cleanup():
    from cwmon.vivino import parse_search_html
    html = """<div class="card"><a href="/tenuta-san-guido-sassicaia/w/1093?year=2015">Tenuta San Guido Sassicaia 2015
      Bolgheri Sassicaia , Italia <span class="average__number">4,6</span> ( 7998 Voti ) 569,52 € Bolgheri Sassicaia , Italia</a></div>"""
    h = parse_search_html(html)[0]
    assert h.name.startswith("Tenuta San Guido Sassicaia 2015") and "Voti" not in h.name
    assert h.rating == 4.6 and h.count == 7998 and h.price == 569.52


# Formato reale dell'endpoint live (novembre 2026)
REAL_OPEN = {"highest_bidder_token": "x", "winner_token": None, "current_bid_amount": {"EUR": 1450, "USD": 1607},
             "bidding_start_time": "2026-11-13T11:00:00Z", "bidding_end_time": "2099-11-23T19:58:30Z",
             "reserve_price_met": True, "favorite_count": 65, "closed": False, "id": 108323823}
REAL_SOLD = {"highest_bidder_token": "a", "winner_token": "a", "current_bid_amount": {"EUR": 82},
             "bidding_end_time": "2026-11-22T19:15:35Z", "reserve_price_met": None, "closed": True, "id": 108568047}
REAL_UNSOLD = {"highest_bidder_token": "b", "winner_token": None, "current_bid_amount": {"EUR": 3000},
               "bidding_end_time": "2026-11-22T20:01:00Z", "reserve_price_met": False, "closed": True, "id": 108515700}


def test_real_live_format():
    o = parse_live_item(REAL_OPEN)
    assert o["current_bid"] == 1450 and o["final"] == 0 and o["reserve_met"] == 1 and o["end_time"] > time.time()
    s = parse_live_item(REAL_SOLD)
    assert s["final"] == 1 and s["sold"] == 1 and s["current_bid"] == 82
    u = parse_live_item(REAL_UNSOLD)
    assert u["final"] == 1 and u["sold"] == 0


def test_litri_and_normalize_existing(tmp_path):
    from cwmon.server import clean_title, normalize_existing
    t = clean_title("1937 Louis Jadot - Pommard - 1 Bottiglia (0,75 litri) Offerta finale 82 € Offerte chiuse")
    assert t == "1937 Louis Jadot - Pommard - 1 Bottiglia (0,75 litri)"
    p = parse_title(t)
    assert p.bottles == 1 and p.bottle_eq == 1.0 and p.vintage == 1937 and p.ok
    db = DB(str(tmp_path / "n.db"))
    for lid, title, slug in [(1, "jack daniel s mclaren halo mk1 1 litre", "jack-daniel-s-mclaren-halo-mk1-1-litre"),
                             (2, "2023 Domaine de Baronarques Chardonnay - Languedoc - 6 Bottiglie (0,75 L)Offerta attuale145 €Mancano 21 ore", "")]:
        db.upsert_listing({"id": lid, "title": title, "slug": slug, "category_id": 720, "image_url": None, "producer": "",
                           "cuvee": "", "appellation": "", "vintage": None, "nv": 0, "mixed": 0, "bottles": 0,
                           "bottle_eq": 0, "size_l": None, "wine_name": "", "wine_key": "", "parse_ok": 0})
    db.commit()
    assert normalize_existing(db) == 2
    jd = db.conn.execute("SELECT * FROM lots WHERE id=1").fetchone()
    bq = db.conn.execute("SELECT * FROM lots WHERE id=2").fetchone()
    assert jd["category_id"] == 437
    assert bq["title"] == "2023 Domaine de Baronarques Chardonnay - Languedoc - 6 Bottiglie (0,75 L)"
    assert bq["category_id"] == 443 and bq["bottles"] == 6 and bq["parse_ok"] == 1


@pytest.mark.parametrize("title,exp", [
    ("2023 Domaine de Baronarques Chardonnay - Languedoc - 6 Bottiglie (0,75 L)", "bianco"),
    ("2016 Caymus, Cabernet Sauvignon - Napa Valley - 1 Bottle (0.75L)", "rosso"),
    ("2017 Cantine Ferrari, Perlè Bianco - Trentino Alto Adige Blanc de Blancs - 3 Bottiglie (0,75 L)", "spumante"),
    ("2000 Château d'Yquem - Sauternes - 1 Bottle (0.75L)", "dolce"),
    ("2016 Domaine Ott, Clos Mireille Rosé - Côtes de Provence - 6 Bottles (0.75L)", "rosato"),
    ("2015 Domaine de Chevalier - Pessac-Léognan - 1 Bottle (0.75L)", "rosso"),
    ("2019 Foo - Vin de France - 1 Bottle (0.75L)", ""),
])
def test_wine_type(title, exp):
    from cwmon.parser import wine_type
    assert wine_type(title) == exp


def test_country_shipping(tmp_path):
    from cwmon.monitor import effective_costs
    from cwmon.server import update_settings
    cfg = load_config()
    cfg["db_path"] = str(tmp_path / "c.db")
    cfg["dashboard"]["cartella"] = str(tmp_path / "site")
    db = DB(cfg["db_path"])
    assert effective_costs(cfg, db)["paese"] == "italia"
    out = update_settings(cfg, db, {"paese": "spagna", "spedizione": {"spagna": {"lotto": 35, "extra_bottiglia": 3}}})
    c = effective_costs(cfg, db)
    assert c["paese"] == "spagna" and c["spedizione_lotto"] == 35 and c["spedizione_extra_bottiglia"] == 3
    assert c["spedizione"]["italia"]["lotto"] == 25 and out["costi"]["paese"] == "spagna"
    total, per = lot_cost(100, 2.0, 2, c)
    assert total == pytest.approx(100 * 1.09 + 3 + 35 + 3)


@pytest.mark.parametrize("det,ship,fee", [
    ({"s": ["Spedizione verso Italia € 25,00 Consegna stimata 3-5 giorni"]}, {"italia": 25.0, "any": 25.0}, None),
    ({"s": ["Costi di spedizione € 32 da Spagna con corriere tracciato"]}, {"any": 32.0}, None),
    ({"s": ["Shipping to Italy € 19.50 · Shipping to Spain € 27"]}, {"italia": 19.5, "spagna": 27.0}, None),
    ({"s": ["Spedizione gratuita in tutta Europa"]}, {"any": 0.0}, None),
    ({"s": ["Commissione per la protezione acquirenti: 9% + € 3 sull'offerta finale"]}, {}, (0.09, 3.0)),
    ({"j": ['"buyer_protection_fee":{"percentage":9,"fixed_amount":{"EUR":3}}',
            '"shipping_costs":[{"country_code":"IT","amount":{"EUR":2500}},{"cents":true}]']}, {}, (0.09, 3.0)),
    ({"s": ["Nessuna informazione utile qui"]}, {}, None),
])
def test_parse_details(det, ship, fee):
    from cwmon.lotdetails import parse_details
    d = parse_details(det)
    for k, v in ship.items():
        assert d["ship"].get(k) == v
    if not ship:
        assert not d["ship"] or "j" in det
    if fee:
        assert d["fee_pct"] == pytest.approx(fee[0]) and d["fee_fixed"] == pytest.approx(fee[1])
    else:
        assert "fee_pct" not in d


def test_costs_for_lot():
    from cwmon.lotdetails import costs_for_lot
    base = dict(COSTS, paese="spagna")
    lot = {"ship_it": 20.0, "ship_es": 31.0, "ship_any": None, "fee_pct": 0.09, "fee_fixed": 3.0}
    c, ss, fs = costs_for_lot(base, lot)
    assert c["spedizione_lotto"] == 31.0 and c["spedizione_extra_bottiglia"] == 0 and ss == "catawiki" and fs == "catawiki"
    c, ss, fs = costs_for_lot(base, {"ship_it": None, "ship_es": None, "ship_any": None, "fee_pct": None, "fee_fixed": None})
    assert c["spedizione_lotto"] == 25.0 and ss == "stima" and fs == "standard"


@pytest.mark.parametrize("body,exp", [
    ('{"shipping_options":[{"country_code":"IT","price":{"EUR":18.5}},{"country_code":"ES","price":{"EUR":24}}]}',
     {"italia": 18.5, "spagna": 24.0}),
    ('{"shipping":{"destination":"IT","options":[{"carrier":"UPS","amount_cents":2200},{"carrier":"DHL","amount_cents":1950}]}}',
     {"italia": 19.5}),
    ('{"cost":{"amount":30,"currency":"EUR"},"insurance_cost":5}', {"any": 30.0}),
    ('{"free_shipping":true}', {"any": 0.0}),
    ('non json', {}),
])
def test_parse_shipping_json(body, exp):
    from cwmon.lotdetails import parse_shipping_json
    assert parse_shipping_json(body) == exp


def test_shipping_response_with_country_variant():
    from cwmon.lotdetails import parse_details
    d = parse_details({"k": [{"c": "IT", "b": '{"price": 21}'}, {"c": "ES", "b": '{"price": 28}'}]})
    assert d["ship"] == {"italia": 21.0, "spagna": 28.0}


def test_real_catawiki_shipping_format():
    from cwmon.lotdetails import parse_details
    body = json.dumps({"shipping": {"rates": [
        {"region_code": "es", "region_name": "Spain (Mainland & Balearic Islands)", "price": 4500.0, "currency_code": "EUR"},
        {"region_code": "it", "region_name": "Italy", "price": 4000.0, "currency_code": "EUR"},
        {"region_code": "pt", "region_name": "Portugal", "price": 3000.0, "currency_code": "EUR"}],
        "destination_country": {"country": {"name": "Italy", "short_code": "it"},
                                "shipping": {"currency_code": "EUR", "rate": 4000.0, "is_available": True}},
        "is_pickup_only": False}})
    d = parse_details({"k": [{"c": "", "b": body}], "s": ["Spedizione in Italia: € 99"]})
    assert d["ship"] == {"spagna": 45.0, "italia": 40.0}  # la risposta strutturata vince sul testo
    d2 = parse_details({"s": ["Spese di spedizione Spedizione in Italia: € 40 Altre destinazioni"]})
    assert d2["ship"]["italia"] == 40.0
    d3 = parse_details({"k": [{"b": json.dumps({"shipping": {"rates": [], "is_pickup_only": True}})}]})
    assert d3.get("solo_ritiro") is True


def _add_lot(db, lid, title, bid=60):
    p = parse_title(title)
    db.upsert_listing({"id": lid, "title": title, "slug": "", "category_id": 961, "image_url": None, "producer": p.producer,
                       "cuvee": p.cuvee, "appellation": p.appellation, "vintage": p.vintage, "nv": int(p.nv),
                       "mixed": int(p.mixed), "bottles": p.bottles, "bottle_eq": p.bottle_eq, "size_l": p.size_l,
                       "wine_name": p.wine_name, "wine_key": p.wine_key, "parse_ok": int(p.ok)})
    db.update_live(lid, {"current_bid": bid, "end_time": int(time.time()) + 3600, "final": 0})
    db.commit()


def test_mixed_lots_never_inherit_manual_values(tmp_path):
    from cwmon.server import add_reference, remove_reference
    from cwmon.monitor import score_all
    cfg = load_config()
    cfg["db_path"] = str(tmp_path / "m.db")
    cfg["dashboard"]["cartella"] = str(tmp_path / "site")
    db = DB(cfg["db_path"])
    _add_lot(db, 1, "Henriot, Brut Souverain - Champagne Brut - 1 Bottiglia (0,75 L)")
    _add_lot(db, 2, "Brut Henriot; Ruinart Pere & Fils - Champagne Brut - 4 Bottiglie (0,75 L)")
    _add_lot(db, 3, "Henriot, Brut Souverain - Champagne Brut - 6 Bottiglie (0,75 L)")
    add_reference(cfg, db, {"lot_id": 1, "prezzo": "36", "ogni_annata": True})
    get = lambda i: db.conn.execute("SELECT market_per_bottle, value_source FROM lots WHERE id=?", (i,)).fetchone()
    assert get(3)[0] == 36                      # stesso vino singolo: il valore vale
    assert get(2)[0] is None                    # lotto misto: nessun valore ereditato
    add_reference(cfg, db, {"lot_id": 2, "prezzo": "45", "ogni_annata": True})
    assert get(2)[0] == 45 and "solo questo lotto" in get(2)[1]
    assert get(1)[0] == 36 and get(3)[0] == 36  # il valore del misto non si propaga
    assert remove_reference(cfg, db, {"lot_id": 2})["rimossi"] == 1
    assert get(2)[0] is None
    # valori salvati con versioni precedenti su un lotto misto: vengono limitati a quel lotto
    mixed_key = db.conn.execute("SELECT wine_key FROM lots WHERE id=2").fetchone()[0]
    db.conn.execute("INSERT INTO manual_values(wine_key, vintage, wine_name, name, price, lot_id, updated_at) "
                    "VALUES(?, NULL, 'henriot brut souverain champagne brut', 'x', 99, 2, 0)", (mixed_key,))
    db.commit()
    score_all(cfg, db)
    assert get(3)[0] == 36 and get(2)[0] == 99
