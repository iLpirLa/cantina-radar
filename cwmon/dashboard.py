"""Genera la dashboard web statica (un solo file HTML con i dati incorporati)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .db import DB
from .monitor import effective_alert_cfg, effective_costs, PAESI
from .parser import wine_type, WINE_TYPES
from .lotdetails import costs_for_lot
from .telegram import lot_url

CATEGORIES = {443: "Vino", 961: "Champagne", 971: "Porto e dolci", 437: "Whisky", 965: "Distillati",
              720: "Vino e distillati"}
TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def build(cfg: dict, db: DB, out_dir: str | Path | None = None) -> Path:
    out_dir = Path(out_dir or Path(cfg["_root"]) / cfg["dashboard"]["cartella"])
    out_dir.mkdir(parents=True, exist_ok=True)
    hours = cfg["dashboard"]["ore_max"] or None
    loc = cfg["catawiki"]["link_locale"]
    a = effective_alert_cfg(cfg, db)
    lots = []
    base_costs = effective_costs(cfg, db)
    for r in db.open_lots(within_hours=hours):
        lc, ship_src, fee_src = costs_for_lot(base_costs, r)
        lots.append({
            "id": r["id"], "t": r["title"], "u": lot_url(r["id"], r["slug"], loc), "img": r["image_url"],
            "cat": CATEGORIES.get(r["category_id"], str(r["category_id"] or "")),
            "v": r["vintage"], "bt": r["bottles"], "eq": r["bottle_eq"], "mix": r["mixed"],
            "end": r["end_time"], "bid": r["current_bid"],
            "rs": r["reserve_set"], "rm": r["reserve_met"],
            "elo": r["estimate_low"], "ehi": r["estimate_high"],
            "mv": r["market_per_bottle"], "cpb": r["cost_per_bottle"], "d": r["discount"],
            "c": r["confidence"], "src": r["value_source"], "mb": r["max_bid"],
            "pr": r["producer"], "cu": r["cuvee"], "ap": r["appellation"], "ok": r["parse_ok"],
            "rt": r["rating"], "rc": r["rating_count"], "ru": r["rating_url"], "cs": r["critic_score"],
            "ty": wine_type(r["title"] or "", r["category_id"]),
            "fp": lc["commissione_pct"], "ff": lc["commissione_fissa"], "fs": fee_src,
            "sl": lc["spedizione_lotto"], "sx": lc["spedizione_extra_bottiglia"], "ss": ship_src,
        })
    history = []
    costs = effective_costs(cfg, db)
    fee, fix = costs["commissione_pct"], costs["commissione_fissa"]
    for r in db.sold_history():
        history.append({
            "id": r["id"], "t": r["title"], "u": lot_url(r["id"], r["slug"], loc) if r["id"] > 0 else None,
            "end": r["end_time"], "bid": r["current_bid"], "eq": r["bottle_eq"], "v": r["vintage"],
            "ppb": round((r["current_bid"] * (1 + fee) + fix) / r["bottle_eq"], 2) if r["bottle_eq"] else None,
            "cat": CATEGORIES.get(r["category_id"], ""),
        })
    payload = {
        "generated": int(time.time()), "stats": db.stats(), "last_run": db.get("last_run", {}),
        "settings": {"sconto_minimo": a["sconto_minimo"], "affidabilita_minima": a["affidabilita_minima"],
                     "ore_alla_chiusura": a["ore_alla_chiusura"], "punteggio_minimo": a.get("punteggio_minimo") or 0,
                     "budget_massimo": a.get("budget_massimo") or 0, "pausa": bool(a.get("pausa"))},
        "costs": costs, "paesi": PAESI, "wine_types": WINE_TYPES,
        "lots": lots,
        "history": history,
        "vivino_blocked": bool(db.get("vivino_bloccato")),
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    (out_dir / "data.json").write_text(data, encoding="utf-8")
    return out
