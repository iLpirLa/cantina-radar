"""Server locale: dashboard + importazione dei lotti inviati dal pulsante nel browser."""
from __future__ import annotations

import http.server
import json
import logging
import re
import time
import urllib.parse
from pathlib import Path

from .catawiki import parse_live_item, _num
from .db import DB
from .parser import parse_title

log = logging.getLogger(__name__)
WEB = Path(__file__).with_name("web")
MAX_BODY = 5_000_000

_BID_RE = re.compile(r"€\s?([\d.,]+)")
_LEFT_RE = [
    (re.compile(r"(\d+)\s*(?:d|days?|giorn[oi]|g)\b", re.I), 86400),
    (re.compile(r"(\d+)\s*(?:h|hours?|or[ae])\b", re.I), 3600),
    (re.compile(r"(\d+)\s*(?:m|min|mins|minutes?|minut[oi])\b", re.I), 60),
]


def _fallback_from_text(text: str, title: str) -> dict:
    """Se l'endpoint live non risponde, prova a leggere offerta e tempo residuo dal testo della scheda."""
    out: dict = {}
    rest = (text or "").replace(title, " ") if title else (text or "")
    m = _BID_RE.search(rest)
    if m:
        out["current_bid"] = _num(m.group(1))
    secs = 0
    for rx, mult in _LEFT_RE:
        mm = rx.search(rest)
        if mm:
            secs += int(mm.group(1)) * mult
    if secs:
        out["end_time"] = int(time.time()) + secs
    return out


_SIZE_TAIL_RE = re.compile(r"^(.*\(\s*[\d.,]+\s*(?:l|cl|ml)\s*\))", re.I | re.S)
_NOISE_RE = re.compile(r"\s*(?:Current bid|Final bid|Starting bid|Offerta attuale|Offerta finale|Offerta iniziale|"
                       r"Mancan[oa]|\d+\s*(?:hours?|days?)\s+left).*$", re.I | re.S)
_SPIRITS_RE = re.compile(r"\b(whisk(?:e)?y|scotch|bourbon|rye|single malt|malt|rum|rhum|cognac|armagnac|calvados|"
                         r"brandy|gin|vodka|tequila|mezcal|grappa|liqueur|liquore|amaro|absinthe|"
                         r"years? old|anni|jack daniel|johnnie walker|macallan|caol ila|lagavulin|ardbeg|"
                         r"laphroaig|glen\w*|yamazaki|hibiki|nikka)\b", re.I)


def clean_title(title: str) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    m = _SIZE_TAIL_RE.match(t)
    if m:
        return m.group(1).strip()
    return _NOISE_RE.sub("", t).strip(" -")


def classify(title: str, url_category: int | None, has_vintage: bool) -> int | None:
    """Assegna la sottocategoria quando la pagina è quella generale (720 = Vino e distillati)."""
    if url_category in (437, 965, 961, 971):
        return url_category
    if _SPIRITS_RE.search(title or "") and not re.search(r"\b(champagne|chateau|château|domaine|barolo|"
                                                        r"brunello|bordeaux|bourgogne)\b", title or "", re.I):
        return 437 if re.search(r"whisk|scotch|bourbon|malt|jack daniel|caol ila|lagavulin|ardbeg|laphroaig|glen|"
                                r"macallan|yamazaki|hibiki|nikka", title or "", re.I) else 965
    if re.search(r"champagne", title or "", re.I):
        return 961
    return 443 if (has_vintage or url_category in (None, 720)) else url_category


def ingest(cfg: dict, db: DB, payload: dict) -> dict:
    from .monitor import score_all, send_alerts, candidates
    from .dashboard import build
    from .telegram import Telegram

    lots = payload.get("lots") or []
    try:  # ultimo invio dal browser, utile per la diagnosi
        dbg = Path(cfg["db_path"]).parent / "ultimo_import.json"
        dbg.write_text(json.dumps(payload, ensure_ascii=False, indent=1)[:3_000_000], encoding="utf-8")
    except OSError:
        pass
    url = str(payload.get("url") or "")
    mcat = re.search(r"/c/(\d+)", url)
    category = int(mcat.group(1)) if mcat else None
    known = {r[0] for r in db.conn.execute("SELECT id FROM lots")}
    live = {}
    for item in payload.get("live") or []:
        if isinstance(item, dict):
            d = parse_live_item(item)
            if d.get("id"):
                live[d["id"]] = d

    nuovi = 0
    for l in lots:
        try:
            lot_id = int(l.get("id"))
        except (TypeError, ValueError):
            continue
        title, slug = clean_title(str(l.get("title") or ""))[:400], str(l.get("slug") or "")[:300]
        p = parse_title(title, slug)
        db.upsert_listing({
            "id": lot_id, "title": title or p.raw or slug.replace("-", " "), "slug": slug or None,
            "category_id": classify(title or slug.replace("-", " "), category, p.vintage is not None), "image_url": (str(l.get("img") or "")[:500] or None),
            "producer": p.producer, "cuvee": p.cuvee, "appellation": p.appellation, "vintage": p.vintage,
            "nv": int(p.nv), "mixed": int(p.mixed), "bottles": p.bottles, "bottle_eq": p.bottle_eq,
            "size_l": p.size_l, "wine_name": p.wine_name, "wine_key": p.wine_key, "parse_ok": int(p.ok),
        })
        if lot_id not in known:
            nuovi += 1
        if lot_id not in live:
            fb = _fallback_from_text(str(l.get("text") or ""), title)
            if fb:
                db.update_live(lot_id, fb)
    for lot_id, d in live.items():
        db.update_live(lot_id, d)
    db.commit()

    score_all(cfg, db)
    tg = Telegram(cfg["telegram"]["token"], cfg["telegram"]["chat_id"])
    avvisi = send_alerts(cfg, db, tg)
    db.set("last_run", {"quando": time.strftime("%d/%m %H:%M"), "lotti": len(lots), "fonte": "pulsante browser",
                        "live_status": payload.get("live_status")})
    build(cfg, db)
    res = {"lotti": len(lots), "nuovi": nuovi, "con_offerta": len(live), "occasioni": len(candidates(cfg, db)),
           "avvisi": avvisi, "live_status": payload.get("live_status")}
    if cfg.get("vivino", {}).get("attivo", True) and not cfg.get("_no_background"):
        from .vivino import enrich_in_background
        res["vivino"] = enrich_in_background(cfg)
    log.info("Importazione dal browser: %s", res)
    return res


SETTINGS_KEYS = {"sconto_minimo": (0.0, 0.95), "punteggio_minimo": (0.0, 5.0), "ore_alla_chiusura": (0.25, 240.0),
                 "budget_massimo": (0.0, 1_000_000.0), "affidabilita_minima": (0.0, 1.0)}


def update_settings(cfg: dict, db: DB, data: dict) -> dict:
    from .monitor import score_all, effective_alert_cfg
    from .dashboard import build
    ov = db.get("overrides", {}) or {}
    for k, (lo, hi) in SETTINGS_KEYS.items():
        if k in data and data[k] is not None:
            try:
                ov[k] = min(hi, max(lo, float(data[k])))
            except (TypeError, ValueError):
                pass
    if "pausa" in data:
        ov["pausa"] = bool(data["pausa"])
    db.set("overrides", ov)
    score_all(cfg, db)  # l'offerta massima dipende dallo sconto minimo
    build(cfg, db)
    a = effective_alert_cfg(cfg, db)
    return {k: a.get(k) for k in list(SETTINGS_KEYS) + ["pausa"]}


def add_reference(cfg: dict, db: DB, data: dict) -> dict:
    """Aggiunge un prezzo di riferimento (per bottiglia 0,75 L) a riferimenti.csv partendo da un lotto."""
    import csv
    from .monitor import score_all
    from .dashboard import build
    lot = db.conn.execute("SELECT * FROM lots WHERE id=?", (int(data.get("lot_id") or 0),)).fetchone()
    if not lot:
        raise ValueError("lotto non trovato")
    price = float(str(data.get("prezzo") or "").replace(",", ".").replace("€", "").strip())
    if not 1 <= price <= 1_000_000:
        raise ValueError("prezzo non valido")
    name = " ".join(x for x in (lot["producer"], lot["cuvee"], lot["appellation"]) if x).strip() or lot["title"]
    vintage = "" if data.get("ogni_annata") else (lot["vintage"] or "")
    score = str(data.get("punteggio") or "").strip()[:40]
    path = Path(cfg["_root"]) / cfg["valutazione"]["file_riferimenti"]
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["vino", "annata", "prezzo_bottiglia", "fonte", "punteggio", "note"])
        w.writerow([name, vintage, f"{price:g}", str(data.get("fonte") or "dashboard")[:40], score,
                    f"lotto {lot['id']}"])
    score_all(cfg, db)
    build(cfg, db)
    row = db.conn.execute("SELECT discount, market_per_bottle FROM lots WHERE id=?", (lot["id"],)).fetchone()
    return {"vino": name, "annata": vintage, "prezzo": price, "sconto": row["discount"]}


def import_history_csv(cfg: dict, db: DB, text: str) -> dict:
    """Importa vendite passate da CSV: titolo (stile Catawiki), prezzo_finale, [data gg/mm/aaaa]."""
    import csv
    import hashlib
    import io
    from datetime import datetime
    from .monitor import score_all
    from .dashboard import build
    sample = text[:2000]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    ok, skipped = 0, 0
    for r in rows:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        title = r.get("titolo") or r.get("title") or r.get("vino") or ""
        price = _num((r.get("prezzo_finale") or r.get("prezzo") or r.get("final_bid") or "").replace("€", ""))
        if not title or not price:
            skipped += 1
            continue
        when = int(time.time()) - 86400
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                when = int(datetime.strptime(r.get("data", ""), fmt).timestamp())
                break
            except ValueError:
                continue
        p = parse_title(title)
        lot_id = -int(hashlib.sha1(f"{title}|{price}|{when}".encode()).hexdigest()[:12], 16)
        db.upsert_listing({
            "id": lot_id, "title": title, "slug": None, "category_id": 443, "image_url": None,
            "producer": p.producer, "cuvee": p.cuvee, "appellation": p.appellation, "vintage": p.vintage,
            "nv": int(p.nv), "mixed": int(p.mixed), "bottles": p.bottles or 1, "bottle_eq": p.bottle_eq or 1.0,
            "size_l": p.size_l, "wine_name": p.wine_name, "wine_key": p.wine_key, "parse_ok": int(bool(p.producer)),
        })
        db.update_live(lot_id, {"current_bid": price, "end_time": when, "final": 1, "sold": 1})
        ok += 1
    db.commit()
    score_all(cfg, db)
    build(cfg, db)
    return {"importati": ok, "scartati": skipped}


def pending_ids(db: DB, limit: int = 200) -> list[int]:
    """Lotti di cui chiedere l'esito: chiusi senza risultato + aperti che chiudono entro 48 ore."""
    now = int(time.time())
    rows = db.conn.execute(
        "SELECT id FROM lots WHERE final=0 AND end_time IS NOT NULL AND end_time < ? ORDER BY end_time DESC LIMIT ?",
        (now - 120, limit)).fetchall()
    ids = [r[0] for r in rows]
    if len(ids) < limit:
        rows = db.conn.execute(
            "SELECT id FROM lots WHERE final=0 AND (end_time IS NULL OR end_time BETWEEN ? AND ?) "
            "ORDER BY end_time LIMIT ?", (now - 120, now + 48 * 3600, limit - len(ids))).fetchall()
        ids += [r[0] for r in rows]
    return ids


def write_static(cfg: dict, port: int) -> Path:
    """Genera ingest.html e installa.html (col pulsante già configurato) nella cartella della dashboard."""
    site = Path(cfg["_root"]) / cfg["dashboard"]["cartella"]
    site.mkdir(parents=True, exist_ok=True)
    pages = int(cfg.get("browser", {}).get("pagine", 4))
    js = (WEB / "bookmarklet.js").read_text(encoding="utf-8")
    js = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    js = js.replace("__ORIGIN__", f"http://localhost:{port}").replace("__PAGES__", str(pages))
    bookmarklet = "javascript:" + urllib.parse.quote(js, safe="(){}[];,.:=+-*/!?&|<>'\"_$")
    inst = (WEB / "installa.html").read_text(encoding="utf-8")
    inst = inst.replace("__BOOKMARKLET__", json.dumps(bookmarklet)).replace("__PAGES_MINUS__", str(max(0, pages - 1)))
    (site / "installa.html").write_text(inst, encoding="utf-8")
    (site / "ingest.html").write_text((WEB / "ingest.html").read_text(encoding="utf-8"), encoding="utf-8")
    return site


def make_handler(cfg: dict, site: Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def log_message(self, *a, **k):
            pass

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def end_headers(self):
            if self.path.split("?")[0] in ("/", "/index.html", "/data.json"):
                self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):
            if self.path.startswith("/api/status"):
                from .vivino import is_running
                return self._json(200, {"vivino_in_corso": is_running()})
            if self.path.startswith("/api/pending"):
                db = DB(cfg["db_path"])
                try:
                    return self._json(200, {"need": pending_ids(db)})
                finally:
                    db.conn.close()
            return super().do_GET()

        def do_POST(self):
            routes = {"/api/ingest": ingest, "/api/settings": update_settings, "/api/reference": add_reference,
                      "/api/storico-csv": lambda c, d, p: import_history_csv(c, d, str(p.get("csv") or ""))}
            fn = routes.get(self.path)
            if fn is None:
                return self._json(404, {"error": "not found"})
            # solo JSON: impedisce a siti esterni di inviare dati con un semplice form
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return self._json(415, {"error": "serve application/json"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._json(413, {"error": "dimensione non valida"})
            try:
                payload = json.loads(self.rfile.read(n))
            except ValueError:
                return self._json(400, {"error": "JSON non valido"})
            db = DB(cfg["db_path"])
            try:
                return self._json(200, fn(cfg, db, payload))
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                log.exception("Richiesta %s fallita", self.path)
                return self._json(500, {"error": str(e)})
            finally:
                db.conn.close()

    return Handler
