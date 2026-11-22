"""Spedizione e commissione lette dalla pagina del lotto Catawiki.

Il pulsante nel browser apre la pagina di ogni lotto e invia all'app solo le parti di testo (e di JSON)
che parlano di spedizione e commissione. Qui le interpretiamo. L'interpretazione sta nell'app,
non nel pulsante, così si può migliorare senza reinstallare il pulsante.
"""
from __future__ import annotations

import re

_EUR = r"€\s?([\d.]+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_EUR_AFTER = r"([\d.]+(?:,\d{1,2})?)\s?€"
COUNTRIES = {
    "italia": r"italia|italy|italie|italien",
    "spagna": r"spagna|spain|españa|espana|espagne|spanien",
}
_SHIP_KW = re.compile(r"spedizion\w*|shipping|env[ií]o|versand|livraison|consegna|delivery", re.I)
_FREE = re.compile(r"spedizione gratuita|free shipping|env[ií]o gratuito|livraison gratuite|kostenloser versand|"
                   r"gratis", re.I)
_FEE_KW = re.compile(r"protezione acquirent\w*|buyer protection|commission\w*|frais de protection|käuferschutz", re.I)
_FEE_PCT = re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s?%\s*(?:\+|più|plus|e)\s*" + _EUR, re.I)


def _num(s: str) -> float | None:
    s = (s or "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", s):  # 1.234,50
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _first_eur(text: str) -> float | None:
    m = re.search(_EUR, text) or re.search(_EUR_AFTER, text)
    return _num(m.group(1)) if m else None


def parse_details(det: dict) -> dict:
    """Ritorna {ship: {paese|'any': costo}, fee_pct, fee_fixed} con ciò che si riesce a ricavare."""
    texts = [str(t) for t in (det.get("s") or []) if t][:20]
    jsons = [str(t) for t in (det.get("j") or []) if t][:20]
    out: dict = {"ship": {}}

    # --- commissione: "9% + € 3"
    for t in texts:
        for m in _FEE_KW.finditer(t):
            win = t[max(0, m.start() - 60): m.end() + 160]
            mm = _FEE_PCT.search(win)
            if mm:
                pct, fixed = _num(mm.group(1)), _num(mm.group(2))
                if pct is not None and 0 < pct < 40 and fixed is not None and 0 <= fixed < 50:
                    out["fee_pct"], out["fee_fixed"] = pct / 100, fixed
                    break
        if "fee_pct" in out:
            break
    if "fee_pct" not in out:
        for j in jsons:
            if re.search(r"buyer_?protection|buyerfee", j, re.I):
                mp = re.search(r'"(?:percentage|percent|rate|pct)\w*"\s*:\s*"?([\d.]+)', j, re.I)
                mf = re.search(r'"(?:fixed|fixed_?fee|fixed_?amount|flat)\w*"\s*:\s*\{?[^0-9{}]{0,20}([\d.]+)', j, re.I)
                if mp:
                    pct = float(mp.group(1))
                    pct = pct / 100 if pct >= 1 else pct
                    if 0 < pct < 0.4:
                        out["fee_pct"] = pct
                        if mf:
                            fx = float(mf.group(1))
                            out["fee_fixed"] = fx / 100 if fx >= 100 else fx
                        break

    # --- spedizione: per paese ("Italia € 25") o importo unico vicino a "Spedizione"
    for t in texts:
        if not _SHIP_KW.search(t):
            continue
        for paese, rx in COUNTRIES.items():
            for m in re.finditer(rf"(?:{rx})[^€\d]{{0,40}}{_EUR}|{_EUR}\s{{0,3}}(?:verso|per|to|a|in|nach|vers)\s+(?:{rx})",
                                 t, re.I):
                v = _num(m.group(1) or m.group(2))
                if v is not None and 0 <= v <= 500:
                    out["ship"].setdefault(paese, v)
        for m in _SHIP_KW.finditer(t):
            win = t[m.start(): m.end() + 90]
            if _FREE.search(win):
                out["ship"].setdefault("any", 0.0)
                break
            v = _first_eur(win)
            if v is not None and 0 <= v <= 500:
                out["ship"].setdefault("any", v)
                break
    if not out["ship"]:
        for j in jsons:
            if not re.search(r"shipping|delivery", j, re.I):
                continue
            cents = "cent" in j.lower()
            for paese, code in (("italia", "IT"), ("spagna", "ES")):
                m = re.search(rf'"(?:country|country_?code|destination\w*)"\s*:\s*"{code}"[^{{}}]{{0,250}}?'
                              rf'"(?:amount|price|cost|value|total)\w*"\s*:\s*\{{?[^0-9{{}}]{{0,20}}([\d.]+)', j, re.I)
                if m:
                    v = float(m.group(1)) / (100 if cents else 1)
                    if 0 <= v <= 500:
                        out["ship"].setdefault(paese, v)
            m = re.search(r'"(?:shipping|delivery)_?(?:cost|price|amount|fee)s?\w*"\s*:\s*\{?[^0-9{}]{0,30}([\d.]+)', j, re.I)
            if m and "any" not in out["ship"]:
                v = float(m.group(1)) / (100 if cents else 1)
                if 0 <= v <= 500:
                    out["ship"]["any"] = v
    return out


def costs_for_lot(base: dict, lot) -> tuple[dict, str, str]:
    """Costi da usare per un lotto: quelli letti su Catawiki se ci sono, altrimenti le stime.
    Ritorna (costi, fonte_spedizione, fonte_commissione) con fonte = 'catawiki' o 'stima'."""
    c = dict(base)
    ship_src, fee_src = "stima", "stima"

    def col(name):
        try:
            return lot[name]
        except (IndexError, KeyError):
            return None

    paese = c.get("paese", "italia")
    ship = col("ship_it") if paese == "italia" else col("ship_es") if paese == "spagna" else None
    if ship is None:
        ship = col("ship_any")
    if ship is not None:
        c["spedizione_lotto"], c["spedizione_extra_bottiglia"] = float(ship), 0.0
        ship_src = "catawiki"
    if col("fee_pct") is not None:
        c["commissione_pct"] = float(col("fee_pct"))
        if col("fee_fixed") is not None:
            c["commissione_fissa"] = float(col("fee_fixed"))
        fee_src = "catawiki"
    return c, ship_src, fee_src
