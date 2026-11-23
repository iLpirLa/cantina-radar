"""Punteggio Vivino (valutazione media della community, scala 1-5) e prezzo indicativo.

Vivino non ha un'API pubblica ufficiale: usiamo la sua pagina di ricerca pubblica, con poche richieste
distanziate e un archivio locale (ogni vino viene cercato al massimo una volta ogni 30 giorni).
Se Vivino rifiuta le richieste, l'app smette di cercare e lo segnala: non si aggira alcun blocco.
Uso esclusivamente personale.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from .parser import norm_text
from .valuation import similarity

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.vivino.com/search/wines"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}
CACHE_DAYS = 30
MISS_DAYS = 10
COOLDOWN_HOURS = 12      # dopo un rifiuto di Vivino non si cerca per 12 ore
PER_RUN = 12             # ricerche massime a ogni pressione del pulsante
_lock = threading.Lock()
_running = threading.Event()

_RATING_RE = re.compile(r"(?<![\d.,])([1-4][.,]\d|5[.,]0)(?![\d.,])")
_COUNT_RE = re.compile(r"\(?\s*([\d.,\s]+)\s*(?:ratings|valutazioni|voti|recensioni|bewertungen|notes|avis)\b", re.I)
_PRICE_RE = re.compile(r"(?:(€|EUR)\s?([\d.,]+)|([\d.,]+)\s?(€|EUR)|(\$|£)\s?([\d.,]+))")
_WINE_HREF_RE = re.compile(r"/w/(\d+)")
_YEAR_RE = re.compile(r"\b(19\d\d|20[0-4]\d)\b")


@dataclass
class VivinoHit:
    name: str
    year: int | None
    rating: float | None
    count: int | None
    price: float | None
    currency: str | None
    url: str


def _num(s: str) -> float | None:
    s = (s or "").strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def parse_search_html(html: str) -> list[VivinoHit]:
    """Estrae i risultati dalla pagina di ricerca. Difensivo: cerca le schede attorno ai link /w/<id>."""
    soup = BeautifulSoup(html or "", "html.parser")
    hits: dict[str, VivinoHit] = {}
    for a in soup.find_all("a", href=_WINE_HREF_RE):
        href = a["href"]
        key = href.split("#")[0]
        if key in hits:
            continue
        # risali fino al contenitore della scheda (che contiene il punteggio)
        card, node = None, a
        for _ in range(8):
            node = node.parent
            if node is None:
                break
            txt = node.get_text(" ", strip=True)
            if _COUNT_RE.search(txt) or node.find(class_=re.compile("average|rating", re.I)):
                card = node
                break
        if card is None:
            continue
        name = a.get_text(" ", strip=True)
        if len(name) < 3:
            name_el = card.find(class_=re.compile("wine-card__name|name", re.I))
            name = name_el.get_text(" ", strip=True) if name_el else ""
        # il link può contenere tutta la scheda: taglia al punteggio ("4,6 ( 7998 Voti ) 569 €")
        name = re.split(r"\s(?:[1-4][.,]\d|5[.,]0)\s*\(", name)[0].strip()
        region_el = card.find(class_=re.compile("wine-card__region|region", re.I))
        if region_el:
            region = region_el.get_text(" ", strip=True)
            if region and region not in name:
                name = f"{name} {region}"
        name = re.sub(r"\s+([,.])", r"\1", re.sub(r"\s+", " ", name))
        rating = None
        avg = card.find(class_=re.compile("average__number|averageValue|rating__average", re.I))
        if avg:
            m = _RATING_RE.search(avg.get_text(" ", strip=True))
            rating = _num(m.group(1)) if m else None
        text = card.get_text(" ", strip=True)
        if rating is None:
            m = _RATING_RE.search(text)
            rating = _num(m.group(1)) if m else None
        mc = _COUNT_RE.search(text)
        count = int(_num(mc.group(1)) or 0) if mc else None
        price, cur = None, None
        mp = _PRICE_RE.search(text)
        if mp:
            if mp.group(1):
                cur, price = "EUR", _num(mp.group(2))
            elif mp.group(4):
                cur, price = "EUR", _num(mp.group(3))
            else:
                cur, price = ("USD" if mp.group(5) == "$" else "GBP"), _num(mp.group(6))
        ym = re.search(r"year=(\d{4})", href) or _YEAR_RE.search(name)
        url = href if href.startswith("http") else f"https://www.vivino.com{href}"
        hits[key] = VivinoHit(name=name, year=int(ym.group(1)) if ym else None, rating=rating, count=count,
                              price=price, currency=cur, url=url)

    if not hits:  # fallback: JSON incorporato nella pagina
        for m in re.finditer(r'"name"\s*:\s*"([^"]{3,120})"[^{}]{0,600}?"ratings_average"\s*:\s*([\d.]+)'
                             r'[^{}]{0,200}?"ratings_count"\s*:\s*(\d+)', html or ""):
            y = _YEAR_RE.search(m.group(1))
            hits[m.group(0)[:60]] = VivinoHit(m.group(1), int(y.group(1)) if y else None, float(m.group(2)),
                                              int(m.group(3)), None, None, "")
    return [h for h in hits.values() if h.rating and 1 <= h.rating <= 5]


def build_query(lot) -> str:
    bits = [lot["producer"] or "", lot["cuvee"] or ""]
    if not lot["cuvee"]:
        bits.append(" ".join((lot["appellation"] or "").split()[:3]))
    q = " ".join(b for b in bits if b).strip()
    return re.sub(r"\s+", " ", q)[:120]


def best_match(lot, hits: list[VivinoHit], min_sim: float = 70) -> VivinoHit | None:
    name = lot["wine_name"] or norm_text(build_query(lot))
    best, best_score = None, 0.0
    for h in hits:
        s = similarity(name, " ".join(norm_text(h.name).split()))
        if lot["vintage"] and h.year == lot["vintage"]:
            s += 8
        elif lot["vintage"] and h.year and h.year != lot["vintage"]:
            s -= 4
        if s > best_score:
            best, best_score = h, s
    return best if best and best_score >= min_sim else None


class Vivino:
    def __init__(self, delay: float = 2.0, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.s.headers.update(HEADERS)
        self.delay = delay
        self.blocked = False

    def search(self, query: str) -> list[VivinoHit]:
        r = self.s.get(SEARCH_URL, params={"q": query}, timeout=25)
        if r.status_code in (401, 403, 429):
            self.blocked = True
            log.warning("Vivino ha rifiutato la richiesta (HTTP %s): ricerca punteggi sospesa", r.status_code)
            return []
        if r.status_code != 200:
            return []
        return parse_search_html(r.text)


def cache_get(db, key: str, vintage) -> dict | None:
    row = db.conn.execute("SELECT * FROM vivino WHERE wine_key=? AND vintage IS ?", (key, vintage)).fetchone()
    return dict(row) if row else None


def enrich(cfg: dict, db, limit: int | None = None) -> int:
    """Cerca su Vivino i vini aperti senza punteggio in archivio. Ritorna il numero di ricerche fatte."""
    if not cfg.get("vivino", {}).get("attivo", True):
        return 0
    now = int(time.time())
    blocked_at = db.get("vivino_bloccato") or 0
    if blocked_at and now - blocked_at < COOLDOWN_HOURS * 3600:
        return 0  # rispettiamo il limite di Vivino: niente richieste fino alla fine della pausa
    limit = limit or int(cfg.get("vivino", {}).get("ricerche", PER_RUN))
    rows = db.conn.execute(
        "SELECT l.* FROM lots l LEFT JOIN vivino v ON v.wine_key=l.wine_key AND v.vintage IS l.vintage "
        "WHERE l.final=0 AND l.parse_ok=1 AND l.wine_key!='' AND COALESCE(l.category_id,443) NOT IN (437,965) "
        "AND l.end_time IS NOT NULL AND l.end_time BETWEEN ? AND ? "
        "AND (v.wine_key IS NULL OR (v.rating IS NULL AND v.fetched_at < ?) OR v.fetched_at < ?) "
        "ORDER BY l.end_time LIMIT ?",
        (now, now + 48 * 3600, now - MISS_DAYS * 86400, now - CACHE_DAYS * 86400, limit)).fetchall()
    if not rows:
        return 0
    viv = Vivino(max(4.0, float(cfg.get("vivino", {}).get("pausa", 4.0))))
    done, seen = 0, set()
    for lot in rows:
        k = (lot["wine_key"], lot["vintage"])
        if k in seen:
            continue
        seen.add(k)
        q = build_query(lot)
        if lot["vintage"]:
            q = f"{q} {lot['vintage']}"
        try:
            hits = viv.search(q)
        except requests.RequestException as e:
            log.warning("Vivino non raggiungibile: %s", e)
            break
        if viv.blocked:
            db.set("vivino_bloccato", int(time.time()))
            break
        if blocked_at:
            db.set("vivino_bloccato", 0)  # Vivino risponde di nuovo: via l'avviso
            blocked_at = 0
        h = best_match(lot, hits)
        db.conn.execute(
            "INSERT OR REPLACE INTO vivino(wine_key, vintage, query, name, year, rating, rating_count, price, "
            "currency, url, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (lot["wine_key"], lot["vintage"], q, h.name if h else None, h.year if h else None,
             h.rating if h else None, h.count if h else None, h.price if h else None,
             h.currency if h else None, h.url if h else None, int(time.time())))
        db.commit()
        done += 1
        time.sleep(viv.delay)
    return done


def enrich_in_background(cfg: dict) -> bool:
    """Avvia l'arricchimento in un thread separato (uno alla volta); al termine aggiorna valutazioni e dashboard."""
    if _running.is_set():
        return False

    def work():
        from .db import DB
        from .monitor import score_all
        from .dashboard import build
        _running.set()
        try:
            with _lock:
                db = DB(cfg["db_path"])
                try:
                    n = enrich(cfg, db)
                    if n:
                        score_all(cfg, db)
                        build(cfg, db)
                        log.info("Vivino: %s vini cercati", n)
                finally:
                    db.conn.close()
        except Exception:  # noqa: BLE001
            log.exception("Arricchimento Vivino fallito")
        finally:
            _running.clear()

    threading.Thread(target=work, daemon=True).start()
    return True


def is_running() -> bool:
    return _running.is_set()
