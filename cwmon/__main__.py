"""Uso:
    python -m cwmon start          TUTTO INSIEME sul PC: monitoraggio ogni 20 min + bot + dashboard
    python -m cwmon run            un ciclo completo (raccolta, valutazione, avvisi, dashboard)
    python -m cwmon loop -m 30     ripete il ciclo ogni 30 minuti (per tenerlo acceso sul PC)
    python -m cwmon serve          rigenera la dashboard e la apre su http://localhost:8000
    python -m cwmon bot            bot Telegram con risposte immediate (in locale)
    python -m cwmon doctor         verifica che la lettura di Catawiki funzioni e salva campioni in debug/
    python -m cwmon demo           dati di esempio per provare dashboard e scoring senza rete
    python -m cwmon test-telegram  invia un messaggio di prova
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from .config import load_config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cwmon", description="Catawiki Wine Monitor")
    ap.add_argument("command", choices=["start", "run", "loop", "serve", "bot", "doctor", "demo", "test-telegram"])
    ap.add_argument("-c", "--config", default=None, help="percorso di config.yaml")
    ap.add_argument("-m", "--minutes", type=int, default=20, help="intervallo per 'loop' e 'start'")
    ap.add_argument("--lan", action="store_true", help="dashboard visibile anche dal telefono sulla stessa Wi-Fi")
    ap.add_argument("-p", "--port", type=int, default=8000, help="porta per 'serve'")
    ap.add_argument("--no-collect", action="store_true", help="salta la raccolta (solo valutazione/avvisi)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    cfg = load_config(args.config)

    if args.command == "start":
        start(cfg, args.minutes, args.port, args.lan)
    elif args.command == "run":
        from .monitor import run_once
        print(json.dumps(run_once(cfg, collect_data=not args.no_collect), ensure_ascii=False, indent=2))
    elif args.command == "loop":
        from .monitor import run_once
        while True:
            try:
                run_once(cfg)
            except Exception:
                logging.exception("Ciclo fallito, riprovo al prossimo giro")
            time.sleep(args.minutes * 60)
    elif args.command == "serve":
        serve(cfg, args.port)
    elif args.command == "bot":
        run_bot(cfg)
    elif args.command == "doctor":
        return doctor(cfg)
    elif args.command == "demo":
        from .demo import run_demo
        out = run_demo(cfg)
        print(f"Dashboard di esempio: {out}")
    elif args.command == "test-telegram":
        from .telegram import Telegram
        tg = Telegram(cfg["telegram"]["token"], cfg["telegram"]["chat_id"])
        if not tg.enabled:
            print("Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
            return 1
        print(tg.send("✅ Catawiki Wine Monitor collegato. Scrivi /aiuto per i comandi."))
    return 0


def start(cfg: dict, minutes: int, port: int, lan: bool) -> None:
    """Modalità PC: ciclo periodico + bot Telegram + dashboard locale, in un solo processo."""
    import functools
    import http.server
    import threading
    import webbrowser
    from .dashboard import build
    from .db import DB
    from .monitor import run_once

    site = Path(cfg["_root"]) / cfg["dashboard"]["cartella"]
    db = DB(cfg["db_path"])
    build(cfg, db)
    db.conn.close()
    host = "0.0.0.0" if lan else "127.0.0.1"
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass

    handler = functools.partial(Quiet, directory=str(site))
    srv = http.server.ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://localhost:{port}/"
    print(f"\n  Dashboard: {url}")
    if lan:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
            print(f"  Dal telefono (stessa Wi-Fi): http://{s.getsockname()[0]}:{port}/")
            s.close()
        except OSError:
            pass
    if cfg["telegram"]["token"]:
        threading.Thread(target=run_bot, args=(cfg,), daemon=True).start()
        print("  Bot Telegram: attivo")
    else:
        print("  Bot Telegram: non configurato (manca il file .env)")
    print(f"  Monitoraggio: ogni {minutes} minuti. Lascia aperta questa finestra (Ctrl+C per uscire).\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    while True:
        try:
            run_once(cfg, commands=False)
        except Exception:
            logging.exception("Ciclo fallito, riprovo al prossimo giro")
        time.sleep(minutes * 60)


def serve(cfg: dict, port: int) -> None:
    import functools
    import http.server
    import webbrowser
    from .dashboard import build
    from .db import DB
    from .monitor import score_all

    db = DB(cfg["db_path"])
    score_all(cfg, db)
    out = build(cfg, db)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out.parent))
    url = f"http://localhost:{port}/"
    print(f"Dashboard su {url}  (Ctrl+C per uscire)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


def run_bot(cfg: dict) -> None:
    from .db import DB
    from .monitor import handle_commands
    from .telegram import Telegram

    tg = Telegram(cfg["telegram"]["token"], cfg["telegram"]["chat_id"])
    if not tg.enabled:
        print("Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
        return
    db = DB(cfg["db_path"])
    logging.info("Bot in ascolto")
    while True:
        try:
            handle_commands(cfg, db, tg, timeout=50)
        except Exception:
            logging.exception("Errore bot")
            time.sleep(10)


def doctor(cfg: dict) -> int:
    """Controlla ogni passaggio della lettura e salva i campioni grezzi in debug/."""
    from .catawiki import CatawikiClient, parse_listing_html, parse_estimate
    from .parser import parse_title

    dbg = Path(cfg["_root"]) / "debug"
    dbg.mkdir(exist_ok=True)
    c = CatawikiClient(cfg["catawiki"]["request_delay"], cfg["catawiki"]["scrape_locale"])
    cat = cfg["catawiki"]["categories"][0]
    day = c.end_days(1)[0]
    ok = True
    print(f"1) Pagina categoria {cat}, chiusura {day}…")
    try:
        html = c.category_page(cat, 1, day)
    except Exception as e:
        print(f"   ✗ {e}")
        return 1
    (dbg / "categoria.html").write_text(html, encoding="utf-8")
    lots = parse_listing_html(html)
    with_title = [l for l in lots if l["title"]]
    print(f"   {'✓' if lots else '✗'} {len(lots)} lotti trovati, {len(with_title)} con titolo completo")
    for l in lots[:5]:
        p = parse_title(l["title"], l["slug"])
        print(f"     #{l['id']}  {l['title'][:70] or l['slug'][:70]}")
        print(f"        → annata {p.vintage}, produttore '{p.producer}', {p.bottles} bott. ({p.bottle_eq} eq.), ok={p.ok}")
    ok &= bool(lots)
    if not lots:
        print("   Nessun lotto: Catawiki potrebbe aver cambiato struttura o bloccato la richiesta.")
        return 1

    print("2) Offerte live…")
    raw = c._get("https://www.catawiki.com/buyer/api/v1/lots/live",
                 params={"ids": ",".join(str(l["id"]) for l in lots[:5])}, accept_json=True)
    (dbg / "live.json").write_text(raw.text, encoding="utf-8")
    live = c.live([l["id"] for l in lots[:5]])
    for lid, d in live.items():
        print(f"     #{lid}: offerta {d['current_bid']}, chiusura {d['end_time']}, riserva ok {d['reserve_met']}, "
              f"stato {d['close_status']}")
    print(f"   {'✓' if live else '✗'} {len(live)} lotti con dati live (risposta grezza in debug/live.json)")
    ok &= bool(live) and any(d["current_bid"] is not None for d in live.values())
    ok &= any(d["end_time"] for d in live.values())

    print("3) Pagina lotto (stima dell'esperto)…")
    page = c.lot_page(lots[0]["id"])
    (dbg / "lotto.html").write_text(page, encoding="utf-8")
    lo, hi = parse_estimate(page)
    print(f"   {'✓' if lo else '–'} stima: {lo}–{hi} (non tutti i lotti ne hanno una)")
    print("\nRisultato:", "TUTTO OK ✅" if ok else "QUALCOSA NON VA ⚠️  — invia i file in debug/ per l'analisi")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
