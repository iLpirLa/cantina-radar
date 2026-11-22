"""Stima del valore di mercato per bottiglia (0,75 L) e calcolo della convenienza.

Fonti gratuite, in ordine di affidabilità:
  1. riferimenti.csv          – prezzi che inserisci tu (Wine-Searcher, Vivino, enoteche...)
  2. storico stessa annata    – prezzi finali delle aste Catawiki chiuse e registrate dall'app
  3. stima dell'esperto       – la forchetta indicata da Catawiki sulla pagina del lotto
  4. storico altre annate     – stesso vino, annate diverse (affidabilità bassa)

"Valore" = quanto si paga tipicamente per bottiglia, commissione inclusa, spedizione esclusa.
"Costo"  = quanto pagheresti tu ora: offerta + commissione + spedizione, diviso le bottiglie equivalenti.
"""
from __future__ import annotations

import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from .parser import norm_text, _key_tokens


@dataclass
class Reference:
    name: str
    name_norm: str
    vintage: int | None
    price: float
    source: str
    score: str = ""


def load_references(path: str | Path) -> list[Reference]:
    path = Path(path)
    if not path.exists():
        return []
    refs = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("vino") or "").strip()
            try:
                price = float(str(row.get("prezzo_bottiglia") or "").replace(",", ".").replace("€", "").strip())
            except ValueError:
                continue
            if not name or price <= 0:
                continue
            v = str(row.get("annata") or "").strip()
            refs.append(Reference(
                name=name,
                name_norm=" ".join(_key_tokens(name, drop_classification=True)),
                vintage=int(v) if v.isdigit() else None,
                price=price,
                source=(row.get("fonte") or "manuale").strip(),
                score=(row.get("punteggio") or "").strip(),
            ))
    return refs


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    # token_set: "lynch bages pauillac" vs "lynch bages pauillac 5eme" -> 100
    return float(fuzz.token_set_ratio(a, b))


def lot_cost(bid: float, bottle_eq: float, bottles: int, costs: dict) -> tuple[float, float]:
    """Ritorna (costo totale, costo per bottiglia equivalente)."""
    bid = max(float(bid or 0), 1.0)
    ship = costs["spedizione_lotto"] + max(0, (bottles or 1) - 1) * costs["spedizione_extra_bottiglia"]
    total = bid * (1 + costs["commissione_pct"]) + costs["commissione_fissa"] + ship
    return total, total / bottle_eq


def max_bid_for(target_per_bottle: float, bottle_eq: float, bottles: int, costs: dict) -> float:
    """Offerta massima per cui il costo per bottiglia resta <= target."""
    ship = costs["spedizione_lotto"] + max(0, (bottles or 1) - 1) * costs["spedizione_extra_bottiglia"]
    bid = (target_per_bottle * bottle_eq - costs["commissione_fissa"] - ship) / (1 + costs["commissione_pct"])
    return max(0.0, math.floor(bid + 1e-6))


class Valuator:
    def __init__(self, refs: list[Reference], history_rows, costs: dict, match_min: float = 88,
                 vivino: dict | None = None):
        self.refs = refs
        self.vivino = vivino or {}
        self.costs = costs
        self.match_min = match_min
        # storico: per ogni vendita, prezzo pagato per bottiglia (commissione inclusa)
        self.history = []
        for r in history_rows:
            per_bottle = (r["current_bid"] * (1 + costs["commissione_pct"]) + costs["commissione_fissa"]) / r["bottle_eq"]
            self.history.append({
                "id": r["id"], "key": r["wine_key"], "name": r["wine_name"] or "", "vintage": r["vintage"],
                "nv": r["nv"], "per_bottle": per_bottle,
            })
        self._by_key: dict[str, list[dict]] = {}
        self._by_vintage: dict[int, list[dict]] = {}
        self._by_token: dict[str, list[dict]] = {}
        self._nv: list[dict] = []
        for h in self.history:
            self._by_key.setdefault(h["key"], []).append(h)
            if h["vintage"]:
                self._by_vintage.setdefault(h["vintage"], []).append(h)
            elif h["nv"]:
                self._nv.append(h)
            if h["name"]:
                self._by_token.setdefault(h["name"].split()[0], []).append(h)

    # ----------------------------------------------------------------- fonti
    def match_ref(self, lot) -> Reference | None:
        best, best_s = None, 0.0
        for ref in self.refs:
            if ref.vintage is not None and ref.vintage != lot["vintage"]:
                continue
            s = similarity(lot["wine_name"], ref.name_norm)
            s_adj = s + (2 if ref.vintage is not None else 0)
            if s >= self.match_min and s_adj > best_s:
                best, best_s = ref, s_adj
        return best

    def _from_vivino(self, lot) -> dict | None:
        v = self.vivino.get((lot["wine_key"], lot["vintage"]))
        if not v or not v.get("price") or v.get("currency") != "EUR":
            return None
        if lot["vintage"] and v.get("year") and v["year"] != lot["vintage"]:
            return None
        # prezzo da negozio: tende a sovrastimare il valore in asta, quindi affidabilità bassa
        return {"value": float(v["price"]), "conf": 0.45, "src": "prezzo Vivino (negozio)", "n": 1}

    def _from_refs(self, lot) -> dict | None:
        best, best_s = None, 0.0
        for ref in self.refs:
            if ref.vintage is not None and ref.vintage != lot["vintage"]:
                continue
            s = similarity(lot["wine_name"], ref.name_norm)
            # preferisci il riferimento con annata esatta a parità di somiglianza
            s_adj = s + (2 if ref.vintage is not None else 0)
            if s >= self.match_min and s_adj > best_s:
                best, best_s = ref, s_adj
        if not best:
            return None
        conf = 0.9 if best.vintage is not None else 0.65
        return {"value": best.price, "conf": conf, "src": f"rif. ({best.source})", "n": 1}

    def _comparables(self, lot, same_vintage: bool) -> list[float]:
        cands = self._by_key.get(lot["wine_key"], [])
        if len(cands) < 3:  # allarga con matching fuzzy sul nome (pre-filtrato per velocità)
            if same_vintage:
                pool = self._by_vintage.get(lot["vintage"], []) if lot["vintage"] else self._nv
            else:
                first = (lot["wine_name"] or " ").split()[0]
                pool = self._by_token.get(first, [])
            seen = {h["id"] for h in cands}
            cands = cands + [h for h in pool if h["id"] not in seen
                             and similarity(lot["wine_name"], h["name"]) >= self.match_min]
        out = []
        for h in cands:
            if h["id"] == lot["id"]:
                continue
            if same_vintage:
                if lot["vintage"] and h["vintage"] == lot["vintage"]:
                    out.append(h["per_bottle"])
                elif not lot["vintage"] and lot["nv"] and h["nv"]:
                    out.append(h["per_bottle"])
            elif h["vintage"] != lot["vintage"]:
                out.append(h["per_bottle"])
        return out

    def _from_history(self, lot) -> dict | None:
        comps = self._comparables(lot, same_vintage=True)
        if not comps:
            return None
        n = len(comps)
        return {"value": statistics.median(comps), "conf": min(0.85, 0.45 + 0.1 * n),
                "src": f"storico ({n})", "n": n}

    def _from_history_other(self, lot) -> dict | None:
        comps = self._comparables(lot, same_vintage=False)
        if len(comps) < 2:
            return None
        return {"value": statistics.median(comps), "conf": 0.35, "src": f"storico altre annate ({len(comps)})",
                "n": len(comps)}

    def _from_estimate(self, lot) -> dict | None:
        lo, hi = lot["estimate_low"], lot["estimate_high"]
        if not lo or not hi or not lot["bottle_eq"]:
            return None
        mid = (lo + hi) / 2
        per_bottle = (mid * (1 + self.costs["commissione_pct"]) + self.costs["commissione_fissa"]) / lot["bottle_eq"]
        return {"value": per_bottle, "conf": 0.6, "src": "stima esperto", "n": 1}

    # ------------------------------------------------------------ valutazione
    def market_value(self, lot) -> dict | None:
        if not lot["parse_ok"]:
            # lotti misti o non interpretabili: solo stima esperto
            return self._from_estimate(lot)
        sources = [s for s in (self._from_refs(lot), self._from_history(lot), self._from_estimate(lot),
                               self._from_vivino(lot)) if s]
        if not sources:
            other = self._from_history_other(lot)
            return other
        wsum = sum(s["conf"] for s in sources)
        value = sum(s["value"] * s["conf"] for s in sources) / wsum
        conf = max(s["conf"] for s in sources)
        if len(sources) > 1:
            spread = (max(s["value"] for s in sources) - min(s["value"] for s in sources)) / value
            conf = min(0.95, conf + 0.05) if spread <= 0.25 else conf * (0.8 if spread > 0.5 else 0.95)
        return {"value": value, "conf": round(conf, 2), "src": " + ".join(s["src"] for s in sources)}

    def quality(self, lot) -> dict:
        out = {}
        v = self.vivino.get((lot["wine_key"], lot["vintage"]))
        if v and v.get("rating"):
            out.update(rating=v["rating"], rating_count=v.get("rating_count"), rating_url=v.get("url"))
        ref = self.match_ref(lot) if lot["parse_ok"] else None
        if ref and ref.score:
            out["critic_score"] = ref.score
        return out

    def score(self, lot, target_discount: float) -> dict | None:
        from .lotdetails import costs_for_lot
        q = self.quality(lot)
        mv = self.market_value(lot)
        if not mv or not lot["bottle_eq"]:
            return q or None
        costs, _, _ = costs_for_lot(self.costs, lot)
        total, per_bottle = lot_cost(lot["current_bid"] or 0, lot["bottle_eq"], lot["bottles"], costs)
        discount = 1 - per_bottle / mv["value"]
        return {
            "market_per_bottle": round(mv["value"], 2),
            "cost_per_bottle": round(per_bottle, 2),
            "total_cost": round(total, 2),
            "discount": round(discount, 4),
            "confidence": mv["conf"],
            "value_source": mv["src"],
            "max_bid": max_bid_for(mv["value"] * (1 - target_discount), lot["bottle_eq"], lot["bottles"], costs),
            **q,
        }
