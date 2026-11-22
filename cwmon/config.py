from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "catawiki": {
        "categories": [443, 961, 971], "days_ahead": 2, "max_pages": 15, "request_delay": 2.0,
        "link_locale": "it", "scrape_locale": "en", "max_detail_pages": 30,
    },
    "costi": {
        "commissione_pct": 0.09, "commissione_fissa": 3.0,
        "paese": "italia",
        "spedizione": {"italia": {"lotto": 25.0, "extra_bottiglia": 2.0},
                       "spagna": {"lotto": 25.0, "extra_bottiglia": 2.0}},
    },
    "valutazione": {"file_riferimenti": "riferimenti.csv", "match_minimo": 88, "giorni_storico": 365},
    "avvisi": {
        "sconto_minimo": 0.25, "ore_alla_chiusura": 3, "affidabilita_minima": 0.5,
        "budget_massimo": 0, "escludi_riserva_non_raggiunta": True,
        "ultima_chiamata_minuti": 45, "includi": [], "escludi": [], "punteggio_minimo": 0,
    },
    "dashboard": {"cartella": "site", "ore_max": 48},
    "browser": {"pagine": 4},
    "vivino": {"attivo": True, "pausa": 2.0},
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _load_dotenv(path: Path) -> None:
    """Carica un file .env (solo uso locale) senza sovrascrivere variabili già impostate."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: str | os.PathLike | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    _load_dotenv(path.parent / ".env")
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = _merge(DEFAULTS, data)
    cfg["_root"] = str(path.parent)
    cfg["telegram"] = {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
    }
    cfg["db_path"] = os.environ.get("CWMON_DB", str(Path(cfg["_root"]) / "data" / "cwmon.db"))
    cfg["dashboard_url"] = os.environ.get("CWMON_DASHBOARD_URL", "").strip()
    return cfg
