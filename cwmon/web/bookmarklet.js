// Pulsante "Cantina Radar": gira nella pagina Catawiki che stai guardando.
// 1) legge i lotti della pagina (e, sulle pagine di elenco, alcune pagine successive)
// 2) chiede a Catawiki le offerte aggiornate, dal tuo browser, come fa il sito stesso
// 3) apre l'app sul tuo computer passando i dati nell'indirizzo (#...): funziona anche se
//    Catawiki isola le finestre (Cross-Origin-Opener-Policy)
// Gli ID dei lotti visti restano nel browser (localStorage) per registrarne poi il prezzo finale.
(function () {
  var ORIGIN = "__ORIGIN__", PAGES = __PAGES__, KEY = "cantinaRadarSeen";
  if (!/catawiki\./.test(location.hostname)) { alert("Usa il pulsante Cantina Radar da una pagina di catawiki.com"); return; }
  var old = document.getElementById("cantina-radar-panel");
  if (old) old.remove();
  var box = document.createElement("div");
  box.id = "cantina-radar-panel";
  box.style.cssText = "position:fixed;z-index:2147483647;right:20px;bottom:20px;width:320px;padding:16px 18px;border-radius:14px;" +
    "background:#1f1815;color:#f3ebe4;font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;box-shadow:0 10px 40px rgba(0,0,0,.45);border:1px solid #3a2d27";
  var head = document.createElement("div");
  head.style.cssText = "font:600 16px Georgia,serif;margin-bottom:6px";
  head.textContent = "🍷 Cantina Radar";
  var msg = document.createElement("div");
  var close = document.createElement("span");
  close.textContent = "✕";
  close.style.cssText = "position:absolute;top:10px;right:14px;cursor:pointer;color:#a8978b";
  close.onclick = function () { box.remove(); };
  box.appendChild(close); box.appendChild(head); box.appendChild(msg);
  document.body.appendChild(box);
  function say(t) { msg.textContent = t; }

  var RE = /\/l\/(\d{6,})(?:-([a-z0-9-]+))?/, Q = /\(\s*[\d.,]+\s*(?:l|cl|ml)\s*\)/i;
  function grab(doc, out) {
    doc.querySelectorAll('a[href*="/l/"]').forEach(function (a) {
      var m = (a.getAttribute("href") || "").match(RE);
      if (!m) return;
      var id = m[1], o = out[id] || (out[id] = { id: +id, slug: m[2] || "", title: "", img: "", text: "" });
      var c = [a.getAttribute("title") || "", a.getAttribute("aria-label") || ""];
      var im = a.querySelector("img");
      if (im) { c.push(im.getAttribute("alt") || ""); if (!o.img) o.img = im.currentSrc || im.getAttribute("src") || im.getAttribute("data-src") || ""; }
      a.querySelectorAll("p,h2,h3,h4,span,div").forEach(function (e) {
        var t = (e.textContent || "").trim();
        if (t.length < 300 && Q.test(t)) c.push(t);
      });
      c.forEach(function (t) { t = t.replace(/\s+/g, " ").trim(); if (Q.test(t) && t.length > o.title.length) o.title = t; });
      var tx = (a.textContent || "").replace(/\s+/g, " ").trim().slice(0, 250);
      if (tx.length > o.text.length) o.text = tx;
    });
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function loadSeen() { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; } }
  function saveSeen(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }

  async function run() {
    var out = {};
    grab(document, out);
    var single = location.pathname.match(RE);
    if (single && !out[single[1]]) {
      var h1 = document.querySelector("h1");
      out[single[1]] = { id: +single[1], slug: single[2] || "", title: (h1 ? h1.textContent : document.title).trim(), img: "", text: "" };
    }
    say("Lettura pagina 1… " + Object.keys(out).length + " lotti");
    if (!single && PAGES > 1) {
      var u = new URL(location.href), p0 = +(u.searchParams.get("page") || 1);
      for (var i = 1; i < PAGES; i++) {
        u.searchParams.set("page", p0 + i);
        await sleep(1500);
        var r = await fetch(u.href, { credentials: "include" });
        if (!r.ok) break;
        var before = Object.keys(out).length;
        grab(new DOMParser().parseFromString(await r.text(), "text/html"), out);
        say("Lettura pagina " + (i + 1) + "… " + Object.keys(out).length + " lotti");
        if (Object.keys(out).length === before) break;
      }
    }
    // lotti visti in passato: chiusi da registrare o in chiusura da aggiornare
    var seen = loadSeen(), now = Date.now() / 1000, need = [];
    Object.keys(seen).forEach(function (id) {
      var end = seen[id];
      if (end && end < now - 7 * 86400) delete seen[id];
      else if (!out[id] && (!end || end < now + 48 * 3600)) need.push(id);
    });
    var ids = Object.keys(out).concat(need.slice(0, 300));
    var live = [], liveStatus = null;
    say("Offerte aggiornate per " + ids.length + " lotti…");
    for (var j = 0; j < ids.length; j += 40) {
      try {
        var r2 = await fetch("/buyer/api/v1/lots/live?ids=" + ids.slice(j, j + 40).join(","),
                             { credentials: "include", headers: { Accept: "application/json" } });
        liveStatus = r2.status;
        if (r2.ok) { var js = await r2.json(); live = live.concat((js && js.lots) || []); }
      } catch (e) { liveStatus = String(e); }
    }
    var withLive = {};
    live.forEach(function (it) {
      var id = it && (it.id || it.lot_id || it.lotId);
      if (!id) return;
      withLive[id] = 1;
      var l = it.liveLot || it, end = l.bidding_end_time || l.biddingEndTime || l.close_at || l.end_time;
      if (typeof end === "string") end = Date.parse(end) / 1000;
      else if (end > 1e11) end = end / 1000;
      seen[id] = end || seen[id] || 0;
    });
    Object.keys(out).forEach(function (id) { if (!(id in seen)) seen[id] = 0; if (withLive[id]) out[id].text = ""; });
    saveSeen(seen);
    return { lots: Object.values(out), live: live, live_status: liveStatus, url: location.href };
  }

  function openApp(data) {
    var url = ORIGIN + "/ingest.html#" + encodeURIComponent(JSON.stringify(data));
    var w = window.open(url, "_blank");
    if (w) { say("✓ " + data.lots.length + " lotti inviati a Cantina Radar."); setTimeout(function () { box.remove(); }, 4000); return; }
    // popup bloccato: serve un clic (nuova "attivazione utente")
    say(data.lots.length + " lotti pronti.");
    var b = document.createElement("a");
    b.href = url; b.target = "_blank"; b.rel = "noopener";
    b.textContent = "Apri i risultati →";
    b.style.cssText = "display:inline-block;margin-top:10px;padding:8px 14px;border-radius:999px;background:#8e1b3a;color:#fff;text-decoration:none;font-weight:600";
    b.onclick = function () { setTimeout(function () { box.remove(); }, 500); };
    box.appendChild(b);
  }

  run().then(openApp).catch(function (err) { say("Errore: " + err); });
})();
