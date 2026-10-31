/* refstats.gr — small enhancements; every page is complete without this file. */
(function () {
  // season switcher
  document.querySelectorAll("select[data-nav]").forEach(function (s) {
    s.addEventListener("change", function () { location.href = s.value; });
  });
  // home board: switch metric
  var chips = document.getElementById("metricChips"), board = document.getElementById("board");
  if (chips && board) {
    chips.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      var k = b.dataset.m, attr = "data-" + k.replace(/_/g, "-"), div = k === "saldo";
      chips.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b); });
      document.getElementById("formula").textContent = b.dataset.note;
      var rows = Array.prototype.slice.call(board.children);
      rows.sort(function (a, c) { return (+c.getAttribute(attr)) - (+a.getAttribute(attr)) || a.textContent.localeCompare(c.textContent, "el"); });
      var max = Math.max.apply(null, rows.map(function (r) { return Math.abs(+r.getAttribute(attr)); }).concat([1]));
      rows.forEach(function (r, i) {
        var v = +r.getAttribute(attr), w = Math.abs(v) / max * (div ? 50 : 100), bar = r.querySelector(".b"), val = r.querySelector(".val");
        r.querySelector(".zero").hidden = !div;
        bar.style.background = div ? (v >= 0 ? "var(--pos)" : "var(--neg)") : "var(--bar)";
        bar.style.left = div ? (v >= 0 ? 50 : 50 - w) + "%" : "0";
        bar.style.width = w + "%";
        val.textContent = div && v > 0 ? "+" + v : v;
        val.className = "val " + (div ? (v > 0 ? "pos" : v < 0 ? "neg" : "nil") : "");
        r.querySelector(".rk").textContent = i + 1;
        r.classList.toggle("top", i < 3);
        board.appendChild(r);
      });
    });
  }
  // sortable tables
  document.querySelectorAll("table.sortable").forEach(function (t) {
    var ths = t.querySelectorAll("thead th"), dir = {};
    ths.forEach(function (th, i) {
      th.tabIndex = 0;
      var go = function () {
        var body = t.tBodies[0], rows = Array.prototype.slice.call(body.rows);
        dir[i] = dir[i] === -1 ? 1 : -1;
        rows.sort(function (a, b) {
          var x = a.cells[i].dataset.v, y = b.cells[i].dataset.v;
          if (x === undefined) return a.cells[i].textContent.localeCompare(b.cells[i].textContent, "el") * -dir[i];
          return (x - y) * dir[i];
        });
        rows.forEach(function (r) { body.appendChild(r); });
        ths.forEach(function (h) { h.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", dir[i] < 0 ? "descending" : "ascending");
      };
      th.addEventListener("click", go);
      th.addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
    });
  });
})();
/* ψηφοφορία αναγνωστών στις αμφισβητούμενες φάσεις */
(function () {
  var polls = Array.prototype.slice.call(document.querySelectorAll(".poll"));
  if (!polls.length || !window.fetch) return;
  var api = polls[0].getAttribute("data-api"), KEY = "rs_votes", mine = {};
  try { mine = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { mine = {}; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(mine)); } catch (e) {} }
  function render(p, c) {
    var id = p.getAttribute("data-id"), team = p.getAttribute("data-team"), out = p.querySelector(".pres");
    var t = c.t || 0, r = c.r || 0, n = t + r, voted = mine[id];
    if (!voted) { out.hidden = !n; out.textContent = n ? n + (n === 1 ? " ψήφος" : " ψήφοι") + " ως τώρα" : ""; return; }
    var pt = n ? Math.round(100 * t / n) : 0;
    p.classList.add("done");
    out.hidden = false;
    out.innerHTML = '<div class="pbar"><i style="width:' + pt + '%"></i></div>' +
      '<span>Αναγνώστες: <b>' + pt + "%</b> με " + team + " · <b>" + (100 - pt) + "%</b> με διαιτητή (" + n + (n === 1 ? " ψήφος" : " ψήφοι") + ")</span>";
  }
  var ids = polls.map(function (p) { return p.getAttribute("data-id"); }), byId = {};
  polls.forEach(function (p) { byId[p.getAttribute("data-id")] = p; });
  for (var i = 0; i < ids.length; i += 60) {
    fetch(api + "/results?ids=" + ids.slice(i, i + 60).join(","))
      .then(function (r) { return r.json(); })
      .then(function (d) { Object.keys(d).forEach(function (k) { if (byId[k]) render(byId[k], d[k]); }); })
      .catch(function () { polls.forEach(function (p) { p.hidden = true; }); });
  }
  polls.forEach(function (p) {
    p.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b || p.classList.contains("done")) return;
      var id = p.getAttribute("data-id");
      p.classList.add("busy");
      fetch(api + "/vote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: id, side: b.getAttribute("data-s") }) })
        .then(function (r) { return r.json(); })
        .then(function (c) { mine[id] = b.getAttribute("data-s"); save(); p.classList.remove("busy"); render(p, c); })
        .catch(function () { p.classList.remove("busy"); });
    });
  });
})();
