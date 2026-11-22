// Pulsante "Cantina Radar": gira nella pagina Catawiki che stai guardando.
// 1) apre la finestra dell'app sul tuo computer (subito, così il browser non la blocca come popup)
// 2) legge i lotti della pagina (e, sulle pagine di elenco, alcune pagine successive)
// 3) chiede a Catawiki le offerte aggiornate, dal tuo browser, come fa il sito stesso
// 4) passa i dati alla finestra dell'app con postMessage
(function () {
  var ORIGIN = "__ORIGIN__", PAGES = __PAGES__;
  if (!/catawiki\./.test(location.hostname)) { alert("Usa il pulsante Cantina Radar da una pagina di catawiki.com"); return; }
  var w = window.open(ORIGIN + "/ingest.html", "cantinaradar");
  if (!w) { alert("Il browser ha bloccato la finestra: consenti i popup per catawiki.com e riprova."); return; }
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
      var tx = (a.textContent || "").replace(/\s+/g, " ").trim().slice(0, 400);
      if (tx.length > o.text.length) o.text = tx;
    });
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function run(need) {
    var out = {};
    grab(document, out);
    var single = location.pathname.match(RE);
    if (single && !out[single[1]]) {
      var h1 = document.querySelector("h1");
      out[single[1]] = { id: +single[1], slug: single[2] || "", title: (h1 ? h1.textContent : document.title).trim(), img: "", text: "" };
    }
    if (!single && PAGES > 1) {
      var u = new URL(location.href), p0 = +(u.searchParams.get("page") || 1);
      for (var i = 1; i < PAGES; i++) {
        u.searchParams.set("page", p0 + i);
        await sleep(1500);
        var r = await fetch(u.href, { credentials: "include" });
        if (!r.ok) break;
        var before = Object.keys(out).length;
        grab(new DOMParser().parseFromString(await r.text(), "text/html"), out);
        if (Object.keys(out).length === before) break;
      }
    }
    var ids = Object.keys(out).concat((need || []).map(String)).filter(function (v, i, a) { return a.indexOf(v) === i; });
    var live = [], liveStatus = null;
    for (var j = 0; j < ids.length; j += 40) {
      try {
        var r2 = await fetch("/buyer/api/v1/lots/live?ids=" + ids.slice(j, j + 40).join(","),
                             { credentials: "include", headers: { Accept: "application/json" } });
        liveStatus = r2.status;
        if (r2.ok) { var js = await r2.json(); live = live.concat((js && js.lots) || []); }
      } catch (e) { liveStatus = String(e); }
    }
    return { lots: Object.values(out), live: live, live_status: liveStatus, url: location.href };
  }
  window.addEventListener("message", function h(e) {
    if (e.origin !== ORIGIN || !e.data || e.data.type !== "ready") return;
    window.removeEventListener("message", h);
    run(e.data.need)
      .then(function (d) { w.postMessage({ type: "data", payload: d }, ORIGIN); })
      .catch(function (err) { w.postMessage({ type: "error", message: String(err) }, ORIGIN); });
  });
})();
