"""Bot Telegram: avvisi + comandi (/top, /stato, /soglia, /budget, /ore, /aiuto).

Su GitHub Actions i comandi vengono letti ad ogni ciclo (risposta entro ~30 minuti).
In locale `python -m cwmon bot` risponde subito.
"""
from __future__ import annotations

import html
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)
ROME = ZoneInfo("Europe/Rome")

HELP = (
    "<b>🍷 Catawiki Wine Monitor</b>\n\n"
    "/top – migliori occasioni aperte ora\n"
    "/stato – statistiche e impostazioni\n"
    "/soglia 30 – sconto minimo per gli avvisi (%)\n"
    "/budget 200 – offerta massima per lotto (0 = nessun limite)\n"
    "/ore 3 – avvisa per lotti che chiudono entro N ore\n"
    "/pausa – sospende gli avvisi · /riprendi – li riattiva\n"
    "/aiuto – questo messaggio"
)


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token, self.chat_id = token, str(chat_id)
        self.enabled = bool(token and chat_id)

    def _call(self, method: str, **params):
        if not self.token:
            return None
        # il long polling di getUpdates tiene aperta la connessione per "timeout" secondi
        http_timeout = int(params.get("timeout") or 0) + 20
        try:
            r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params, timeout=http_timeout)
            data = r.json()
            if not data.get("ok"):
                log.warning("Telegram %s: %s", method, data.get("description"))
            return data
        except (requests.RequestException, ValueError) as e:
            log.warning("Telegram non raggiungibile: %s", e)
            return None

    def send(self, text: str, buttons: list[tuple[str, str]] | None = None, chat_id: str | None = None):
        if not self.enabled:
            log.info("[telegram disattivato] %s", text.replace("\n", " | ")[:200])
            return None
        params = {"chat_id": chat_id or self.chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "url": u} for t, u in buttons]]}
        return self._call("sendMessage", **params)

    def updates(self, offset: int | None, timeout: int = 0) -> list[dict]:
        data = self._call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message"])
        return (data or {}).get("result", []) if data else []


# --------------------------------------------------------------------- format
def fmt_eur(v) -> str:
    if v is None:
        return "–"
    return f"€ {v:,.0f}".replace(",", ".")


def time_left(end_time: int | None) -> str:
    if not end_time:
        return "?"
    s = int(end_time - time.time())
    if s <= 0:
        return "chiuso"
    h, m = divmod(s // 60, 60)
    if h >= 24:
        return f"{h // 24}g {h % 24}h"
    return f"{h}h {m:02d}m" if h else f"{m} min"


def lot_url(lot_id: int, slug: str | None, locale: str) -> str:
    return f"https://www.catawiki.com/{locale}/l/{lot_id}" + (f"-{slug}" if slug else "")


def alert_text(lot, s: dict, kind: str) -> str:
    head = "⏰ <b>ULTIMA CHIAMATA</b>" if kind == "last_call" else "🍷 <b>Occasione</b>"
    end_local = "?"
    if lot["end_time"]:
        dt = datetime.fromtimestamp(lot["end_time"], ROME)
        end_local = dt.strftime("%H:%M") if dt.date() == datetime.now(ROME).date() else dt.strftime("%d/%m %H:%M")
    rating = ""
    try:
        if lot["rating"]:
            rating = f"★ Vivino {lot['rating']:.1f}".replace(".", ",") + (f" ({lot['rating_count']} voti)" if lot["rating_count"] else "") + "\n"
        if lot["critic_score"]:
            rating += f"✎ Critica: {html.escape(lot['critic_score'])}\n"
    except (IndexError, KeyError):
        pass
    reserve = ""
    if lot["reserve_set"] and lot["reserve_met"] == 0:
        reserve = "\n⚠️ Riserva non ancora raggiunta"
    return (
        f"{head} · sconto <b>{s['discount'] * 100:.0f}%</b>\n"
        f"<b>{html.escape(lot['title'] or '')}</b>\n\n"
        f"Offerta attuale: <b>{fmt_eur(lot['current_bid'])}</b> · chiude tra {time_left(lot['end_time'])} ({end_local})\n"
        f"Costo reale/bott.: {fmt_eur(s['cost_per_bottle'])} vs valore {fmt_eur(s['market_per_bottle'])}\n"
        f"💡 Offri al massimo <b>{fmt_eur(s['max_bid'])}</b> per restare nel tuo sconto minimo\n"
        f"{rating}"
        f"Fonte valore: {html.escape(s['value_source'])} · affidabilità {s['confidence'] * 100:.0f}%"
        f"{reserve}"
    )


def top_text(rows, limit: int = 10) -> str:
    if not rows:
        return "Nessuna occasione al momento con i filtri attuali."
    lines = ["<b>🏆 Migliori occasioni aperte</b>\n"]
    for r in rows[:limit]:
        lines.append(
            f"<b>{r['discount'] * 100:.0f}%</b> · {html.escape((r['title'] or '')[:80])}\n"
            f"   {fmt_eur(r['current_bid'])} (max {fmt_eur(r['max_bid'])}) · {time_left(r['end_time'])} · "
            f"<a href=\"{lot_url(r['id'], r['slug'], 'it')}\">apri</a>"
        )
    return "\n".join(lines)
