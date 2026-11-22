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


def ingest(cfg: dict, db: DB, payload: dict) -> dict:
    from .monitor import score_all, send_alerts, candidates
    from .dashboard import build
    from .telegram import Telegram

    lots = payload.get("lots") or []
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
        title, slug = str(l.get("title") or "")[:400], str(l.get("slug") or "")[:300]
        p = parse_title(title, slug)
        db.upsert_listing({
            "id": lot_id, "title": title or p.raw or slug.replace("-", " "), "slug": slug or None,
            "category_id": category, "image_url": (str(l.get("img") or "")[:500] or None),
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
    log.info("Importazione dal browser: %s", res)
    return res


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
            if self.path.startswith("/api/pending"):
                db = DB(cfg["db_path"])
                try:
                    return self._json(200, {"need": pending_ids(db)})
                finally:
                    db.conn.close()
            return super().do_GET()

        def do_POST(self):
            if self.path != "/api/ingest":
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
                return self._json(200, ingest(cfg, db, payload))
            except Exception as e:  # noqa: BLE001
                log.exception("Importazione fallita")
                return self._json(500, {"error": str(e)})
            finally:
                db.conn.close()

    return Handler
