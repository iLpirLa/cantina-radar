"""Ciclo principale: scoperta lotti → offerte live → chiusure → stime → valutazione → avvisi → dashboard."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .catawiki import CatawikiClient, parse_estimate
from .db import DB
from .parser import parse_title, norm_text
from .telegram import Telegram, HELP, alert_text, top_text, lot_url, fmt_eur
from .valuation import Valuator, load_references

log = logging.getLogger(__name__)


def effective_alert_cfg(cfg: dict, db: DB) -> dict:
    a = dict(cfg["avvisi"])
    a.update(db.get("overrides", {}) or {})
    return a


# ------------------------------------------------------------------ raccolta
def collect(cfg: dict, db: DB, client: CatawikiClient) -> dict:
    c = cfg["catawiki"]
    discovered = 0
    for cat in c["categories"]:
        try:
            lots = client.discover_lots(int(cat), int(c["days_ahead"]), int(c["max_pages"]))
        except Exception as e:  # una categoria che fallisce non blocca le altre
            log.error("Categoria %s non letta: %s", cat, e)
            continue
        for l in lots:
            p = parse_title(l.get("title") or "", l.get("slug") or "")
            row = {
                "id": l["id"], "title": l.get("title") or p.raw or (l.get("slug") or "").replace("-", " "),
                "slug": l.get("slug") or None, "category_id": l.get("category_id"),
                "image_url": l.get("image_url") or None,
                "producer": p.producer, "cuvee": p.cuvee, "appellation": p.appellation, "vintage": p.vintage,
                "nv": int(p.nv), "mixed": int(p.mixed), "bottles": p.bottles, "bottle_eq": p.bottle_eq,
                "size_l": p.size_l, "wine_name": p.wine_name, "wine_key": p.wine_key, "parse_ok": int(p.ok),
            }
            db.upsert_listing(row)
            if l.get("end_time"):
                db.update_live(l["id"], {"end_time": l["end_time"]})
        discovered += len(lots)
    db.commit()

    # offerte live per i lotti aperti + quelli da chiudere
    ids = [r["id"] for r in db.open_lots()] + db.lots_to_finalize()
    live = client.live(ids) if ids else {}
    for lot_id, data in live.items():
        db.update_live(lot_id, data)
    # lotti scaduti da oltre 2 giorni senza risposta: chiudili senza esito
    db.conn.execute("UPDATE lots SET final=1 WHERE final=0 AND end_time < ?", (int(time.time()) - 2 * 86400,))
    db.commit()

    # stime dell'esperto per i lotti che chiudono presto
    n_detail = 0
    soon = [r for r in db.open_lots(within_hours=12) if not r["estimate_checked"]]
    for r in soon[: int(c["max_detail_pages"])]:
        lo, hi = parse_estimate(client.lot_page(r["id"]))
        db.set_estimate(r["id"], lo, hi)
        n_detail += 1
    db.commit()
    return {"scoperti": discovered, "live": len(live), "pagine_lotto": n_detail, "richieste": client.requests_made}


# ---------------------------------------------------------------- valutazione
def score_all(cfg: dict, db: DB) -> Valuator:
    refs = load_references(Path(cfg["_root"]) / cfg["valutazione"]["file_riferimenti"])
    val = Valuator(refs, db.history(int(cfg["valutazione"]["giorni_storico"])), cfg["costi"],
                   float(cfg["valutazione"]["match_minimo"]))
    target = float(effective_alert_cfg(cfg, db)["sconto_minimo"])
    for lot in db.open_lots():
        s = val.score(lot, target)
        db.save_score(lot["id"], s or {})
    db.commit()
    log.info("Valutazione: %s riferimenti, %s vendite nello storico", len(refs), len(val.history))
    return val


def candidates(cfg: dict, db: DB, within_hours: float | None = None) -> list:
    a = effective_alert_cfg(cfg, db)
    rows = db.open_lots(within_hours=within_hours)
    out = []
    inc = [norm_text(k) for k in a.get("includi") or [] if k]
    exc = [norm_text(k) for k in a.get("escludi") or [] if k]
    for r in rows:
        if r["discount"] is None or r["confidence"] is None:
            continue
        if r["discount"] < float(a["sconto_minimo"]) or r["confidence"] < float(a["affidabilita_minima"]):
            continue
        if a["budget_massimo"] and (r["current_bid"] or 0) > float(a["budget_massimo"]):
            continue
        if a["escludi_riserva_non_raggiunta"] and r["reserve_set"] and r["reserve_met"] == 0:
            continue
        t = norm_text(r["title"] or "")
        if inc and not any(k in t for k in inc):
            continue
        if any(k in t for k in exc):
            continue
        out.append(r)
    return sorted(out, key=lambda r: -(r["discount"] * r["confidence"]))


# --------------------------------------------------------------------- avvisi
def send_alerts(cfg: dict, db: DB, tg: Telegram) -> int:
    a = effective_alert_cfg(cfg, db)
    if a.get("pausa"):
        return 0
    loc = cfg["catawiki"]["link_locale"]
    sent = 0
    now = time.time()
    for r in candidates(cfg, db, within_hours=float(a["ore_alla_chiusura"])):
        kind = "last_call" if r["end_time"] and r["end_time"] - now <= a["ultima_chiamata_minuti"] * 60 else "first"
        if db.was_alerted(r["id"], kind) or (kind == "first" and db.was_alerted(r["id"], "last_call")):
            continue
        s = {k: r[k] for k in ("discount", "cost_per_bottle", "market_per_bottle", "max_bid", "value_source",
                                "confidence")}
        buttons = [("Apri su Catawiki", lot_url(r["id"], r["slug"], loc))]
        if cfg.get("dashboard_url"):
            buttons.append(("Dashboard", cfg["dashboard_url"]))
        res = tg.send(alert_text(r, s, kind), buttons)
        if res is None and tg.enabled:
            continue
        db.mark_alerted(r["id"], kind, r["discount"])
        sent += 1
    return sent


# -------------------------------------------------------------------- comandi
def handle_commands(cfg: dict, db: DB, tg: Telegram, timeout: int = 0) -> int:
    if not tg.enabled:
        return 0
    offset = db.get("tg_offset")
    handled = 0
    for upd in tg.updates(offset, timeout=timeout):
        db.set("tg_offset", upd["update_id"] + 1)
        msg = upd.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if chat != tg.chat_id or not text.startswith("/"):
            continue  # accetta comandi solo dalla tua chat
        handled += 1
        reply_command(cfg, db, tg, text)
    return handled


def reply_command(cfg: dict, db: DB, tg: Telegram, text: str) -> None:
    cmd, *args = text.split()
    cmd = cmd.split("@")[0].lower()
    ov = db.get("overrides", {}) or {}

    def set_num(key: str, scale: float = 1.0, label: str = ""):
        try:
            ov[key] = float(args[0].replace(",", ".").rstrip("%")) / scale
        except (IndexError, ValueError):
            tg.send(f"Uso: {cmd} &lt;numero&gt;")
            return
        db.set("overrides", ov)
        tg.send(f"✅ {label} aggiornato.")

    if cmd in ("/start", "/aiuto", "/help"):
        tg.send(HELP)
    elif cmd == "/top":
        tg.send(top_text(candidates(cfg, db)))
    elif cmd == "/stato":
        st, a = db.stats(), effective_alert_cfg(cfg, db)
        last = db.get("last_run", {})
        tg.send(
            "<b>📊 Stato</b>\n"
            f"Lotti tracciati: {st['tracciati']} (aperti {st['aperti']})\n"
            f"Vendite nello storico: {st['storico_venduti']}\n"
            f"Avvisi inviati: {st['avvisi_inviati']}\n"
            f"Ultimo ciclo: {last.get('quando', '–')}\n\n"
            f"Sconto minimo: {a['sconto_minimo'] * 100:.0f}% · entro {a['ore_alla_chiusura']:g}h · "
            f"budget {fmt_eur(a['budget_massimo']) if a['budget_massimo'] else 'illimitato'}"
            f"{' · ⏸ IN PAUSA' if a.get('pausa') else ''}"
        )
    elif cmd == "/soglia":
        set_num("sconto_minimo", 100, "Sconto minimo")
    elif cmd == "/budget":
        set_num("budget_massimo", 1, "Budget")
    elif cmd == "/ore":
        set_num("ore_alla_chiusura", 1, "Finestra di chiusura")
    elif cmd == "/pausa":
        ov["pausa"] = True
        db.set("overrides", ov)
        tg.send("⏸ Avvisi sospesi. /riprendi per riattivarli.")
    elif cmd == "/riprendi":
        ov["pausa"] = False
        db.set("overrides", ov)
        tg.send("▶️ Avvisi riattivati.")
    else:
        tg.send("Comando non riconosciuto. /aiuto per l'elenco.")


# ----------------------------------------------------------------------- run
def run_once(cfg: dict, build_dashboard: bool = True, collect_data: bool = True) -> dict:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from .dashboard import build

    db = DB(cfg["db_path"])
    tg = Telegram(cfg["telegram"]["token"], cfg["telegram"]["chat_id"])
    summary: dict = {}
    handle_commands(cfg, db, tg)  # prima i comandi, così le nuove soglie valgono subito
    if collect_data:
        client = CatawikiClient(cfg["catawiki"]["request_delay"], cfg["catawiki"]["scrape_locale"])
        summary.update(collect(cfg, db, client))
    score_all(cfg, db)
    summary["avvisi"] = send_alerts(cfg, db, tg)
    summary["quando"] = datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M")
    db.set("last_run", summary)
    if build_dashboard:
        out = build(cfg, db)
        summary["dashboard"] = str(out)
    log.info("Ciclo completato: %s", summary)
    return summary
