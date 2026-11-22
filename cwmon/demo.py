"""Dati di esempio (inventati) per provare dashboard, scoring e avvisi senza collegarsi a Catawiki."""
from __future__ import annotations

import random
import time
from pathlib import Path

from .db import DB
from .parser import parse_title

# (titolo, prezzo tipico pagato per bottiglia commissione inclusa) – valori illustrativi
WINES = [
    ("2008 Château Lynch Bages - Pauillac 5ème Grand Cru Classé", 140),
    ("2016 Château Pontet-Canet - Pauillac 5ème Grand Cru Classé", 165),
    ("2015 Tenuta San Guido, Sassicaia - Bolgheri", 320),
    ("2016 Prunotto, Bussia Vigna Colonnello - Barolo Riserva", 105),
    ("2013 Bruno Giacosa, Falletto - Barolo", 210),
    ("2017 Domaine de Chevalier - Pessac-Léognan Grand Cru Classé", 70),
    ("2010 Castello dei Rampolla, Sammarco - Toscana", 95),
    ("2019 Tignanello, Marchesi Antinori - Toscana", 120),
    ("2012 Dom Pérignon - Champagne Brut", 230),
    ("2004 Dal Forno Romano, Monte Lodoletta Valpolicella - Veneto Superiore", 150),
    ("2018 Clos Saint-Jean - Châteauneuf-du-Pape", 38),
    ("2011 Biondi-Santi, Tenuta Greppo - Brunello di Montalcino", 160),
    ("2005 Château Canon-la-Gaffelière - Saint-Émilion Grand Cru Classé", 85),
    ("2014 Gaja - Barbaresco", 210),
]


def run_demo(cfg: dict) -> Path:
    root = Path(cfg["_root"])
    db_path = root / "data" / "demo.db"
    if db_path.exists():
        db_path.unlink()
    cfg = dict(cfg, db_path=str(db_path))
    db = DB(str(db_path))
    rnd = random.Random(7)
    now = int(time.time())
    fee, fix = cfg["costi"]["commissione_pct"], cfg["costi"]["commissione_fissa"]
    lot_id = 900_000_000

    def insert(title: str, bid: float, end: int, final: int, sold: int | None, reserve=(0, None), est=None):
        nonlocal lot_id
        lot_id += 1
        p = parse_title(title)
        db.upsert_listing({
            "id": lot_id, "title": title, "slug": None, "category_id": 961 if "Champagne" in title else 443,
            "image_url": None, "producer": p.producer, "cuvee": p.cuvee, "appellation": p.appellation,
            "vintage": p.vintage, "nv": int(p.nv), "mixed": int(p.mixed), "bottles": p.bottles,
            "bottle_eq": p.bottle_eq, "size_l": p.size_l, "wine_name": p.wine_name, "wine_key": p.wine_key,
            "parse_ok": int(p.ok),
        })
        db.update_live(lot_id, {"current_bid": bid, "end_time": end, "final": final, "sold": sold,
                                "reserve_set": reserve[0], "reserve_met": reserve[1]})
        if est:
            db.set_estimate(lot_id, *est)

    # storico: 3-6 vendite chiuse per vino, con rumore ±15%
    for name, ppb in WINES:
        for _ in range(rnd.randint(3, 6)):
            n = rnd.choice([1, 1, 1, 2, 3, 6])
            hammer = (ppb * rnd.uniform(0.85, 1.15) * n - fix) / (1 + fee)
            insert(f"{name} - {n} {'Bottle' if n == 1 else 'Bottles'} (0.75L)", round(hammer), now - rnd.randint(1, 60) * 86400, 1, 1)

    # lotti aperti: alcuni a sconto, altri cari
    for i, (name, ppb) in enumerate(WINES):
        n = rnd.choice([1, 1, 2, 3, 6])
        ratio = rnd.choice([0.45, 0.55, 0.65, 0.8, 0.95, 1.1])
        bid = max(10, round((ppb * ratio * n - fix - 25) / (1 + fee)))
        end = now + rnd.randint(10, 46 * 60) * 60
        reserve = rnd.choice([(0, None), (0, None), (1, 1), (1, 0)])
        est = (round(ppb * n * 0.8), round(ppb * n * 1.0)) if i % 3 == 0 else None
        insert(f"{name} - {n} {'Bottle' if n == 1 else 'Bottles'} (0.75L)", bid, end, 0, None, reserve, est)
    # lotto misto e lotto senza storico
    insert("Domaine Vincent Paris ; Domaine Paul Jaboulet Ainé - Rhône - 4 Bottles (0.75L)", 60, now + 5400, 0, None,
           est=(90, 120))
    insert("2001 Fattoria Sconosciuta, Riserva Speciale - Chianti Classico - 1 Bottle (0.75L)", 22, now + 9000, 0, None)
    db.commit()

    from .dashboard import build
    from .monitor import score_all
    score_all(cfg, db)
    return build(cfg, db, root / "site-demo")
