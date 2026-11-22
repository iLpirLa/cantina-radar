"""Lettura dei dati pubblici di Catawiki.

Catawiki non offre un'API pubblica. Questo modulo usa:
  1. le pagine pubbliche di categoria (filtrate per giorno di chiusura) per scoprire i lotti;
  2. l'endpoint JSON che il sito stesso usa per mostrare le offerte live (/buyer/api/v1/lots/live);
  3. (facoltativo) la pagina del singolo lotto per leggere la stima dell'esperto.

Le richieste sono poche e distanziate (vedi `request_delay` in config.yaml). Uso esclusivamente personale.
Tutte le estrazioni sono difensive: se Catawiki cambia struttura, usa `python -m cwmon doctor`.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE = "https://www.catawiki.com"
AMS = ZoneInfo("Europe/Amsterdam")
_LOT_HREF_RE = re.compile(r"/(?:[a-z]{2}/)?l/(\d{6,})(?:-([a-z0-9-]+))?")
_QTY_HINT_RE = re.compile(r"\(\s*[\d.,]+\s*(?:l|cl|ml)\s*\)|\b\d+\s+(?:bottles?|magnums?)\b", re.I)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9,it;q=0.8",
}


class CatawikiClient:
    def __init__(self, delay: float = 2.0, scrape_locale: str = "en", session: requests.Session | None = None):
        self.delay = max(1.0, float(delay))
        self.locale = scrape_locale
        self.s = session or requests.Session()
        self.s.headers.update(HEADERS)
        self._last = 0.0
        self.requests_made = 0

    # ------------------------------------------------------------------ http
    def _get(self, url: str, params: dict | None = None, accept_json: bool = False) -> requests.Response:
        wait = self.delay + random.uniform(0, 0.8) - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        headers = {"Accept": "application/json"} if accept_json else {"Accept": "text/html,application/xhtml+xml"}
        for attempt in range(3):
            try:
                r = self.s.get(url, params=params, headers=headers, timeout=30)
                self._last = time.time()
                self.requests_made += 1
                if r.status_code in (429, 503):
                    pause = 20 * (attempt + 1)
                    log.warning("Catawiki risponde %s, pausa di %ss", r.status_code, pause)
                    time.sleep(pause)
                    continue
                return r
            except requests.RequestException as e:
                log.warning("Errore di rete (%s), nuovo tentativo", e)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"Impossibile raggiungere {url}")

    # ------------------------------------------------------------- listing
    @staticmethod
    def end_days(days_ahead: int) -> list[str]:
        today = datetime.now(AMS).date()
        return [(today + timedelta(days=i)).strftime("%Y%m%d") for i in range(max(1, days_ahead))]

    def category_page(self, category_id: int, page: int = 1, end_day: str | None = None) -> str:
        params: dict[str, Any] = {}
        if end_day:
            params["filters"] = f"bidding_end_days[]={end_day}"
        if page > 1:
            params["page"] = page
        r = self._get(f"{BASE}/{self.locale}/c/{category_id}", params=params)
        if r.status_code == 403:
            raise RuntimeError(f"Catawiki ha rifiutato la richiesta (HTTP 403) per la categoria {category_id}: "
                               "il sito blocca le richieste automatiche. Vedi la sezione 'Limiti' del README.")
        if r.status_code != 200:
            raise RuntimeError(f"Pagina categoria {category_id} p.{page}: HTTP {r.status_code}")
        return r.text

    def discover_lots(self, category_id: int, days_ahead: int, max_pages: int) -> list[dict]:
        found: dict[int, dict] = {}
        for day in self.end_days(days_ahead):
            for page in range(1, max_pages + 1):
                html = self.category_page(category_id, page, day)
                lots = parse_listing_html(html)
                new = [l for l in lots if l["id"] not in found]
                for l in lots:
                    l["category_id"] = category_id
                    prev = found.get(l["id"])
                    if not prev or len(l.get("title") or "") > len(prev.get("title") or ""):
                        found[l["id"]] = l
                log.info("Categoria %s, chiusura %s, pagina %s: %s lotti (%s nuovi)",
                         category_id, day, page, len(lots), len(new))
                if not new or len(lots) < 10:
                    break
        return list(found.values())

    # ---------------------------------------------------------------- live
    def live(self, lot_ids: Iterable[int], batch: int = 40) -> dict[int, dict]:
        ids = list(dict.fromkeys(int(i) for i in lot_ids))
        out: dict[int, dict] = {}
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            r = self._get(f"{BASE}/buyer/api/v1/lots/live", params={"ids": ",".join(map(str, chunk))},
                          accept_json=True)
            if r.status_code != 200:
                log.warning("Endpoint live: HTTP %s", r.status_code)
                continue
            try:
                payload = r.json()
            except ValueError:
                log.warning("Endpoint live: risposta non JSON")
                continue
            for item in payload.get("lots", []) if isinstance(payload, dict) else []:
                parsed = parse_live_item(item)
                if parsed.get("id"):
                    out[parsed["id"]] = parsed
        return out

    # -------------------------------------------------------------- detail
    def lot_page(self, lot_id: int) -> str:
        r = self._get(f"{BASE}/{self.locale}/l/{lot_id}")
        return r.text if r.status_code == 200 else ""


# ====================================================================== parsing
def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    # taglia eventuali code tipo "Current bid € 45" o "Offerta attuale"
    text = re.split(r"\s(?:Current bid|Final bid|Starting bid|Offerta attuale|Offerta finale|€\s?\d)", text)[0]
    return text.strip(" -")


def parse_listing_html(html: str) -> list[dict]:
    """Estrae {id, slug, title, image_url} dai lotti presenti in una pagina di categoria."""
    lots: dict[int, dict] = {}

    def add(lot_id: int, slug: str = "", title: str = "", image: str = "", end_time: int | None = None):
        cur = lots.setdefault(lot_id, {"id": lot_id, "slug": "", "title": "", "image_url": "", "end_time": None})
        if slug and not cur["slug"]:
            cur["slug"] = slug
        title = _clean_title(title)
        if title and (_QTY_HINT_RE.search(title) or not cur["title"]) and len(title) > len(cur["title"]):
            cur["title"] = title
        if image and not cur["image_url"]:
            cur["image_url"] = image
        if end_time and not cur["end_time"]:
            cur["end_time"] = end_time

    soup = BeautifulSoup(html, "html.parser")

    # Strategia 1: JSON incorporato (Next.js __NEXT_DATA__ o application/json)
    for script in soup.find_all("script"):
        txt = script.string or script.get_text() or ""
        if script.get("id") == "__NEXT_DATA__" or (script.get("type") == "application/json" and '"title"' in txt):
            try:
                data = json.loads(txt)
            except ValueError:
                continue
            for d in _walk(data):
                url = str(_first(d, "url", "href", "link", default=""))
                m = _LOT_HREF_RE.search(url)
                lid = _first(d, "lotId", "lot_id", "id")
                if m or (lid and "title" in d and ("biddingEndTime" in d or "bidding_end_time" in d or m)):
                    try:
                        lot_id = int(m.group(1) if m else lid)
                    except (TypeError, ValueError):
                        continue
                    add(lot_id, m.group(2) or "" if m else "", str(d.get("title") or ""),
                        str(_first(d, "thumbImageUrl", "imageUrl", "image", default="")),
                        _to_epoch(_first(d, "biddingEndTime", "bidding_end_time")))

    # Strategia 2: link <a href="/en/l/123-slug">
    for a in soup.find_all("a", href=True):
        m = _LOT_HREF_RE.search(a["href"])
        if not m:
            continue
        lot_id, slug = int(m.group(1)), m.group(2) or ""
        candidates = [a.get("title") or "", a.get("aria-label") or ""]
        img = a.find("img")
        if img is not None:
            candidates.append(img.get("alt") or "")
        for el in a.find_all(["p", "h2", "h3", "h4", "span", "div"]):
            t = el.get_text(" ", strip=True)
            if t and _QTY_HINT_RE.search(t) and len(t) < 300:
                candidates.append(t)
        candidates.append(a.get_text(" ", strip=True)[:300])
        best = ""
        for c in candidates:
            c = _clean_title(c)
            if _QTY_HINT_RE.search(c) and len(c) > len(best):
                best = c
        image = (img.get("src") or img.get("data-src") or "") if img is not None else ""
        add(lot_id, slug, best, image)

    # Strategia 3: payload RSC/JSON in testo ("id":123,..."title":"...")
    for m in re.finditer(r'"id"\s*:\s*(\d{6,})\s*,[^{}]{0,400}?"title"\s*:\s*"((?:[^"\\]|\\.){5,300})"', html):
        try:
            title = json.loads(f'"{m.group(2)}"')
        except ValueError:
            title = m.group(2)
        if int(m.group(1)) in lots or _QTY_HINT_RE.search(title):
            add(int(m.group(1)), title=title)

    return list(lots.values())


def _to_epoch(v) -> int | None:
    if v in (None, "", 0):
        return None
    if isinstance(v, (int, float)):
        return int(v / 1000) if v > 1e11 else int(v)
    if isinstance(v, str):
        if v.isdigit():
            return _to_epoch(int(v))
        try:
            return int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _to_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(bool(v))
    if isinstance(v, str):
        return int(v.lower() in ("true", "1", "yes"))
    return None


def _amount(v, currency: str = "EUR"):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "."))
        except ValueError:
            return None
    if isinstance(v, dict):
        for k in (currency, currency.lower(), "amount", "value", "EUR", "eur"):
            if k in v:
                return _amount(v[k], currency)
    return None


_OPEN_STATUSES = {"open", "opened", "active", "running", "live", "extended", "bidding", "not_closed", "open_now"}
_UNSOLD_STATUSES = {"unsold", "not_sold", "withdrawn", "cancelled", "canceled", "rejected", "reserve_not_met",
                    "no_bids", "closed_unsold"}


def parse_live_item(item: dict) -> dict:
    """Normalizza un elemento dell'endpoint live (nomi dei campi camelCase o snake_case)."""
    d = item.get("liveLot") if isinstance(item.get("liveLot"), dict) else item
    lot_id = _first(item, "id", "lot_id", "lotId") or _first(d, "id", "lot_id", "lotId")
    try:
        lot_id = int(lot_id)
    except (TypeError, ValueError):
        return {}
    bid = _amount(_first(d, "bid", "current_bid", "currentBid", "current_bid_amount", "highest_bid",
                         "amount", "bid_amount"))
    end = _to_epoch(_first(d, "bidding_end_time", "biddingEndTime", "close_at", "closeAt", "end_time",
                           "endTime", "closing_time", "closingTime"))
    status = str(_first(d, "close_status", "closeStatus", "status", "state", default="") or "").lower()
    reserve_met = _to_bool(_first(d, "reserve_price_met", "reservePriceMet"))
    reserve_set = _to_bool(_first(d, "reserve_price_set", "reservePriceSet", "has_reserve_price"))
    sold_flag = _to_bool(_first(d, "sold", "is_sold", "isSold"))
    closed_flag = _to_bool(_first(d, "closed", "is_closed", "isClosed"))

    now = time.time()
    final = 0
    if closed_flag or (status and status not in _OPEN_STATUSES) or (end and end < now - 600 and status not in
                                                                    ("extended",)):
        final = 1
    sold = None
    if final:
        if sold_flag is not None:
            sold = sold_flag
        elif status in _UNSOLD_STATUSES or reserve_met == 0:
            sold = 0
        else:
            sold = int((bid or 0) > 0)
    return {
        "id": lot_id, "current_bid": bid, "currency": "EUR", "end_time": end,
        "reserve_set": reserve_set if reserve_set is not None else (1 if reserve_met is not None else None),
        "reserve_met": reserve_met, "close_status": status or None, "final": final, "sold": sold,
    }


_EST_PATTERNS = [
    # JSON: "expertEstimate":{"min":120,"max":150} / "estimate":{"low":..,"high":..}
    re.compile(r'"(?:expert_?[eE]stimate|estimated?_?[pP]rice|estimate)s?"\s*:\s*\{\s*"(?:min|low|from)\w*"\s*:\s*'
               r'(?:\{[^{}]*?)?"?([\d.]+)"?[^{}]*\}?\s*,\s*"(?:max|high|to)\w*"\s*:\s*(?:\{[^{}]*?)?"?([\d.]+)', re.S),
    re.compile(r'"(?:expert_?estimate|estimate)_?(?:min|low)\w*"\s*:\s*"?([\d.]+).{0,200}?'
               r'"(?:expert_?estimate|estimate)_?(?:max|high)\w*"\s*:\s*"?([\d.]+)', re.S | re.I),
    # Testo: "Expert's estimate € 120 - € 150" / "Stima dell'esperto € 120 - € 150"
    re.compile(r"(?:Expert(?:'|’|&#x27;|&#39;)?s?\s+estimate|Stima dell(?:'|’|&#x27;|&#39;)\s?esperto|Estimation de"
               r" l(?:'|’)expert|Schätzung)[^€\d]{0,40}€\s?([\d.,]+)\s*[-–]\s*€\s?([\d.,]+)", re.I),
]


def _num(s: str) -> float | None:
    s = s.strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def parse_estimate(html: str) -> tuple[float | None, float | None]:
    for pat in _EST_PATTERNS:
        m = pat.search(html or "")
        if m:
            lo, hi = _num(m.group(1)), _num(m.group(2))
            if lo and hi and 0 < lo <= hi < 10_000_000:
                return lo, hi
    return None, None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
