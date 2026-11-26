// Pulsante "Cantina Radar": gira nella pagina Catawiki che stai guardando.
// 1) legge i lotti della pagina (e, sulle pagine di elenco, alcune pagine successive)
// 2) chiede a Catawiki le offerte aggiornate, dal tuo browser, come fa il sito stesso
// 3) apre l'app sul tuo computer passando i dati nell'indirizzo (#...): funziona anche se
//    Catawiki isola le finestre (Cross-Origin-Opener-Policy)
// Gli ID dei lotti visti restano nel browser (localStorage) per registrarne poi il prezzo finale.
(function () {
  var ORIGIN = "__ORIGIN__", PAGES = __PAGES__, KEY = "cantinaRadarSeen", DKEY = "cantinaRadarDetails", MAXD = __DETAILS__,
      TKEY = "cantinaRadarShipTpl";
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

  var RE = /\/l\/(\d{6,})(?:-([a-z0-9-]+))?/, Q = /\(\s*[\d.,]+\s*(?:cl|ml|lt|litri|litro|litres?|liters?|l)\s*\)/i;
  // testo di un elemento con spazi tra i blocchi (textContent li incolla: "0,75 L)Offerta attuale250 €")
  function leafText(el) {
    var parts = [];
    el.querySelectorAll("*").forEach(function (e) {
      if (!e.children.length) { var t = (e.textContent || "").trim(); if (t) parts.push(t); }
    });
    return (parts.length ? parts.join(" ") : (el.textContent || "")).replace(/\s+/g, " ").trim();
  }
  // taglia tutto ciò che segue l'ultimo formato "(0,75 L)"
  function cut(t) { var m = t.match(/^(.*\(\s*[\d.,]+\s*(?:cl|ml|lt|litri|litro|litres?|liters?|l)\s*\))/i); return m ? m[1] : t; }
  function grab(doc, out) {
    doc.querySelectorAll('a[href*="/l/"]').forEach(function (a) {
      var m = (a.getAttribute("href") || "").match(RE);
      if (!m) return;
      var id = m[1], o = out[id] || (out[id] = { id: +id, slug: m[2] || "", title: "", img: "", text: "" });
      var c = [a.getAttribute("title") || "", a.getAttribute("aria-label") || ""];
      var im = a.querySelector("img");
      if (im) { c.push(im.getAttribute("alt") || ""); if (!o.img) o.img = im.currentSrc || im.getAttribute("src") || im.getAttribute("data-src") || ""; }
      a.querySelectorAll("p,h2,h3,h4,span,div").forEach(function (e) {
        var t = leafText(e);
        if (t.length < 300) c.push(t);
      });
      var best = "";
      c.forEach(function (t) { t = cut(t.replace(/\s+/g, " ").trim()); if (Q.test(t) && t.length > best.length) best = t; });
      if (!best) {  // nessun formato tra parentesi (es. distillati): primo titolo/testo plausibile
        for (var k = 0; k < c.length; k++) {
          var t2 = c[k].replace(/\s+/g, " ").trim();
          if (t2.length >= 8 && t2.length <= 200 && !/^(offerta|current|final|starting|mancano|\d+\s*(ore|h|min|giorni?))/i.test(t2)) { best = t2; break; }
        }
      }
      if (best && (Q.test(best) || !Q.test(o.title)) && best.length > o.title.length) o.title = best;
      var tx = leafText(a).slice(0, 250);
      if (tx.length > o.text.length) o.text = tx;
    });
  }
  // parti della pagina del lotto che parlano di spedizione e commissione (interpretate poi dall'app)
  var KW = /(spedizion|shipping|env[ií]o|versand|livraison|consegna|protezione acquirent|buyer protection|commission|costi)/gi;
  var JK = /"[A-Za-z_]*(?:[sS]hipping|[bB]uyer_?[pP]rotection|[bB]uyer[fF]ee|[dD]elivery)[A-Za-z_]*"\s*:/g;
  function snippets(html, doc) {
    var txt = leafText(doc.body || doc.documentElement), out = [], last = -999, m;
    KW.lastIndex = 0;
    while ((m = KW.exec(txt)) && out.length < 10) {
      if (m.index - last < 150) continue;
      last = m.index;
      out.push(txt.slice(Math.max(0, m.index - 120), m.index + 240));
    }
    var js = []; JK.lastIndex = 0;
    while ((m = JK.exec(html)) && js.length < 10) js.push(html.substr(m.index, 320));
    return { s: out, j: js };
  }
  function compactShipping(txt) {
    try {
      var j = JSON.parse(txt), sh = j && j.shipping;
      if (sh && Array.isArray(sh.rates)) {
        return JSON.stringify({ shipping: {
          rates: sh.rates.filter(function (r) { return /^(it|es)$/i.test(r.region_code || ""); })
            .map(function (r) { return { region_code: r.region_code, price: r.price, currency_code: r.currency_code }; }),
          destination_country: sh.destination_country ? { country: { short_code: ((sh.destination_country.country || {}).short_code) },
            shipping: sh.destination_country.shipping } : null,
          is_pickup_only: !!sh.is_pickup_only } });
      }
    } catch (e) {}
    return txt.slice(0, 4000);
  }
  // solo i campi delle offerte live che servono all'app
  function compactLive(it) {
    var o = {};
    Object.keys(it || {}).forEach(function (k) {
      if (/^(id|lot_?id|lotId|bid|current_?bid\w*|currentBid|bidding_end_time|biddingEndTime|close\w*|end\w*|reserve\w*|winner_token|winnerToken|sold|is_sold|isSold|status|state|liveLot)$/i.test(k)) {
        var v = it[k];
        if (v && typeof v === "object" && !Array.isArray(v) && ("EUR" in v)) v = { EUR: v.EUR };
        if (k === "winner_token" || k === "winnerToken") v = v ? "1" : null;
        if (k === "liveLot") v = compactLive(v);
        o[k] = v;
      }
    });
    return o;
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
        if (r2.ok) { var js = await r2.json(); live = live.concat(((js && js.lots) || []).map(compactLive)); }
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

    // spedizione e commissione dalla pagina di ogni lotto (una volta per lotto, prima quelli che chiudono presto)
    var det = {}, done = {};
    try { done = JSON.parse(localStorage.getItem(DKEY) || "{}"); } catch (e) {}
    Object.keys(done).forEach(function (id) { if (done[id] < now - 5 * 86400) delete done[id]; });
    var loc = (location.pathname.match(/^\/([a-z]{2})\//) || [0, "it"])[1];
    // la spedizione viene caricata dalla pagina con una richiesta separata: su una pagina di lotto la individuiamo
    var tpl = "", resAll = [];
    try { tpl = localStorage.getItem(TKEY) || ""; } catch (e) {}
    try { resAll = performance.getEntriesByType("resource").map(function (e) { return e.name; }); } catch (e) {}
    if (single) {
      var hit = resAll.filter(function (u) {
        return u.indexOf(single[1]) >= 0 && /ship|deliver|spediz|envio|versand/i.test(u) && u.indexOf(location.origin) === 0;
      })[0];
      if (hit) { tpl = hit.replace(single[1], "{ID}"); try { localStorage.setItem(TKEY, tpl); } catch (e) {} }
    }
    async function shipping(id) {
      if (!tpl) return [];
      // una sola richiesta: la risposta di Catawiki contiene le tariffe di tutti i paesi
      var variants = [{ c: "", u: tpl.replace("{ID}", id) }];
      var outv = [];
      for (var v = 0; v < variants.length; v++) {
        try {
          var rs = await fetch(variants[v].u, { credentials: "include", headers: { Accept: "application/json" } });
          if (rs.ok) outv.push({ c: variants[v].c, b: compactShipping(await rs.text()) });
        } catch (e) {}
      }
      return outv;
    }
    if (single) {
      det[single[1]] = snippets(document.documentElement.outerHTML, document);
      det[single[1]].k = await shipping(single[1]);
      done[single[1]] = now;
    }
    // se abbiamo appena scoperto come leggere la spedizione, rileggi anche i lotti già visti
    if (single && tpl && !done.__tpl) {  // prima volta che abbiamo il modello: rileggi i lotti già visti
      Object.keys(done).forEach(function (id) { if (id !== single[1]) delete done[id]; });
      done.__tpl = now;
    }
    var todo = Object.keys(out).filter(function (id) { return id !== "__tpl"; }).filter(function (id) { return !done[id] && !det[id] && (!seen[id] || seen[id] > now); })
      .sort(function (a, b) { return (seen[a] || 9e12) - (seen[b] || 9e12); }).slice(0, MAXD);
    for (var k = 0; k < todo.length; k++) {
      say("Spedizione e commissione: lotto " + (k + 1) + " di " + todo.length + "…");
      try {
        if (tpl) {
          var kk = await shipping(todo[k]);
          if (kk.length) { det[todo[k]] = { k: kk }; done[todo[k]] = now; }
        } else {
          var r3 = await fetch("/" + loc + "/l/" + todo[k], { credentials: "include" });
          if (r3.ok) {
            var h3 = await r3.text();
            det[todo[k]] = snippets(h3, new DOMParser().parseFromString(h3, "text/html"));
            done[todo[k]] = now - 4 * 86400;  // senza modo di leggere la spedizione: riprova presto
          }
        }
      } catch (e) {}
      await sleep(tpl ? 700 : 1000);
    }
    try { localStorage.setItem(DKEY, JSON.stringify(done)); } catch (e) {}
    var res = single ? resAll.filter(function (u) { return /\/api\/|graphql/i.test(u); }).slice(0, 60) : [];
    return { lots: Object.values(out), live: live, live_status: liveStatus, url: location.href, details: det,
             resources: res, ship_template: tpl };
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
