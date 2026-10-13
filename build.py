#!/usr/bin/env python3
"""refstats.gr static site generator.

Reads the four published Google Sheet CSVs (see config.json) and writes a
static site to ./public. Standard library only.

  python build.py                 # fetch CSVs from config.json, build ./public
  python build.py --local DIR     # read agones.csv, var.csv, omades.csv, diaitites.csv from DIR
  python build.py --preview       # links end in index.html (for previewing files without a server)
"""
import csv, io, json, os, re, shutil, sys, unicodedata, urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from html import escape

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "public")
CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
PREVIEW = "--preview" in sys.argv
LOCAL = sys.argv[sys.argv.index("--local") + 1] if "--local" in sys.argv else None
SITE = CFG["site_url"].rstrip("/")

# ---------------------------------------------------------------- data in
def fetch(name):
    if LOCAL:
        return open(os.path.join(LOCAL, name + ".csv"), encoding="utf-8").read()
    req = urllib.request.Request(CFG["csv"][name], headers={"User-Agent": "refstats-build"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")

def rows(name):
    data = list(csv.DictReader(io.StringIO(fetch(name))))
    return [{(k or "").strip(): (v or "").strip() for k, v in d.items()} for d in data]

def num(x):
    x = (x or "").strip().replace(",", ".")
    if not x:
        return 0
    try:
        return int(round(float(x)))
    except ValueError:
        return 0

def pdate(x):
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(x.strip(), f)
        except ValueError:
            pass
    return None

GR = str.maketrans({"α":"a","β":"v","γ":"g","δ":"d","ε":"e","ζ":"z","η":"i","θ":"th","ι":"i","κ":"k","λ":"l","μ":"m",
    "ν":"n","ξ":"x","ο":"o","π":"p","ρ":"r","σ":"s","ς":"s","τ":"t","υ":"y","φ":"f","χ":"ch","ψ":"ps","ω":"o"})
def slugify(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    s = s.translate(GR)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "x"

TEAMS = {}
for r in rows("omades"):
    if r.get("Ομάδα"):
        TEAMS[r["Ομάδα"]] = r.get("Slug (URL)") or slugify(r["Ομάδα"])
REFS = {}
for r in rows("diaitites"):
    if r.get("Διαιτητής"):
        REFS[r["Διαιτητής"]] = {"slug": r.get("Slug (URL)") or slugify(r["Διαιτητής"]),
                                "assoc": r.get("Ένωση / Χώρα", ""), "foreign": r.get("Ξένος", "") == "Ναι"}

PAIRS = [("pen", "Πέναλτι"), ("yel", "Κίτρινες"), ("red", "Κόκκινες"), ("foul", "Φάουλ"), ("ann", "Ακυρ. γκολ")]
MATCHES = []
for r in rows("agones"):
    if not (r.get("ID") and r.get("Γηπεδούχος") and r.get("Φιλοξενούμενος")):
        continue
    m = {"id": r["ID"], "season": r["Σεζόν"], "phase": r.get("Φάση") or "Κανονική", "round": num(r["Αγωνιστική"]),
         "date": pdate(r.get("Ημερομηνία", "")), "home": r["Γηπεδούχος"], "away": r["Φιλοξενούμενος"],
         "gh": num(r["Γκολ Γηπ"]), "ga": num(r["Γκολ Φιλ"]), "ref": r.get("Διαιτητής", ""), "var": r.get("VAR", ""),
         "src": r.get("Πηγή", ""), "var_items": []}
    for k, col in PAIRS:
        m[k + "_h"] = num(r.get(col + " Γηπ")); m[k + "_a"] = num(r.get(col + " Φιλ"))
    MATCHES.append(m)
BYID = {m["id"]: m for m in MATCHES}
for r in rows("var"):
    m = BYID.get(r.get("ID αγώνα", ""))
    if m and r.get("Τύπος επέμβασης"):
        m["var_items"].append({"min": r.get("Λεπτό", ""), "type": r["Τύπος επέμβασης"],
                               "ben": r.get("Ωφελημένη ομάδα", ""), "desc": r.get("Περιγραφή", ""), "src": r.get("Πηγή", "")})
def minute_key(x):
    a = re.findall(r"\d+", x["min"]); return (int(a[0]) if a else 0, int(a[1]) if len(a) > 1 else 0)
for m in MATCHES:
    m["var_items"].sort(key=minute_key)
    m["var_h"] = sum(1 for v in m["var_items"] if v["ben"] == m["home"])
    m["var_a"] = sum(1 for v in m["var_items"] if v["ben"] == m["away"])
for m in MATCHES:  # make sure every name used has a page
    for t in (m["home"], m["away"]):
        TEAMS.setdefault(t, slugify(t))
    for p in (m["ref"], m["var"]):
        if p: REFS.setdefault(p, {"slug": slugify(p), "assoc": "", "foreign": False})

PHASE_ORDER = {"Κανονική": 0, "Πλέι οφ 1-4": 1, "Πλέι οφ 5-8": 2, "Πλέι άουτ": 3}
MATCHES.sort(key=lambda m: (m["season"], PHASE_ORDER.get(m["phase"], 9), m["round"], m["date"] or datetime.min, m["home"]))
SEASONS = sorted({m["season"] for m in MATCHES}, reverse=True)
CUR = SEASONS[0] if SEASONS else ""

# ---------------------------------------------------------------- stats
KEYS = ["n", "pen_for", "pen_against", "var_for", "var_against", "red_opp", "red_own", "yel", "foul", "ann", "w", "d", "l"]
def side(m, team):
    h = team == m["home"]; o, p = ("h", "a") if h else ("a", "h")
    gf, ga = (m["gh"], m["ga"]) if h else (m["ga"], m["gh"])
    return {"n": 1, "pen_for": m["pen_" + o], "pen_against": m["pen_" + p], "var_for": m["var_" + o], "var_against": m["var_" + p],
            "red_opp": m["red_" + p], "red_own": m["red_" + o], "yel": m["yel_" + o], "foul": m["foul_" + o], "ann": m["ann_" + o],
            "w": int(gf > ga), "d": int(gf == ga), "l": int(gf < ga)}
def saldo(t): return (t["pen_for"] + t["var_for"] + t["red_opp"]) - (t["pen_against"] + t["var_against"] + t["red_own"])
def totals(ms, team):
    t = dict.fromkeys(KEYS, 0)
    for m in ms:
        if team in (m["home"], m["away"]):
            for k, v in side(m, team).items(): t[k] += v
    t["saldo"] = saldo(t); return t
def season_ms(s): return [m for m in MATCHES if m["season"] == s]

# ---------------------------------------------------------------- html helpers
PAGES = []  # (path, priority) for sitemap
def rel(frm, to):
    """relative link from page dir `frm` to page dir `to` (both like 'omades/paok/'; '' = home)."""
    up = "../" * frm.count("/")
    href = up + to
    if PREVIEW:
        href += "index.html"
    return href or "./"
def esc(s): return escape(str(s), quote=True)
def sg(v): return f"+{v}" if v > 0 else str(v)
def cls(v): return "pos" if v > 0 else "neg" if v < 0 else "nil"
def fdate(d): return d.strftime("%d/%m/%Y") if d else ""
def team_link(here, t): return f'<a href="{rel(here, "omades/" + TEAMS[t] + "/")}">{esc(t)}</a>'
def ref_link(here, p):
    if not p: return "—"
    return f'<a href="{rel(here, "diaitites/" + REFS[p]["slug"] + "/")}">{esc(p)}</a>'
def round_path(m): return f"agonistiki/{m['season']}/{slugify(m['phase'])}-{m['round']}/"
def round_gen(m): return f"{m['round']}ης αγωνιστικής" + ("" if m["phase"] == "Κανονική" else f" ({m['phase']})")
def round_label(m): return f"{m['round']}η αγωνιστική" + ("" if m["phase"] == "Κανονική" else f" ({m['phase']})")

NOW = datetime.now(timezone(timedelta(hours=3)))
UPDATED = NOW.strftime("%d/%m/%Y %H:%M")

def page(path, title, desc, body, priority="0.6", canonical=None):
    here = path
    nav = [("", "Ομάδες"), ("diaitites/", "Διαιτητές"), ("agonistiki/", "Αγωνιστικές"), ("methodologia/", "Μεθοδολογία")]
    sec = path.split("/")[0] + "/" if path else ""
    navh = "".join(f'<a href="{rel(here, p)}"{" aria-current=\"page\"" if (p == sec or (p == "" and sec in ("", "sezon/"))) else ""}>{l}</a>' for p, l in nav)
    can = SITE + "/" + (canonical if canonical is not None else path)
    html = f"""<!doctype html>
<html lang="el">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(can)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="refstats.gr">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{esc(can)}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect x='9' y='4' width='14' height='22' rx='2' fill='%23F2C230' transform='rotate(-9 16 16)'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fira+Sans+Extra+Condensed:wght@500;700;800&family=Commissioner:wght@400;500;600&display=swap">
<link rel="stylesheet" href="{"../" * here.count("/")}assets/style.css">
</head>
<body>
<div class="wrap">
<header class="mast">
  <a class="logo" href="{rel(here, "")}"><span class="yc" aria-hidden="true"></span><span>refstats<small>.gr</small></span></a>
  <nav class="top">{navh}</nav>
</header>
<main>
{body}
</main>
<footer>
  <p>refstats.gr · Ανεξάρτητη καταγραφή στατιστικών διαιτησίας της Super League. Δεν σχετίζεται με την ΕΠΟ, την ΚΕΔ ή τη Super League.</p>
  <p>Τελευταία ενημέρωση: {UPDATED} · <a href="{rel(here, "methodologia/")}">Μεθοδολογία</a> · <a href="{rel(here, "aporrito/")}">Πολιτική απορρήτου</a></p>
</footer>
</div>
<script src="{"../" * here.count("/")}assets/app.js" defer></script>
</body>
</html>"""
    d = os.path.join(OUT, path)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(html)
    if canonical is None:
        PAGES.append((path, priority))

METRICS = [
    ("saldo", "Ισοζύγιο", "Ισοζύγιο: πέναλτι + VAR υπέρ + κόκκινες αντιπάλου − (πέναλτι + VAR κατά + δικές κόκκινες)."),
    ("pen_for", "Πέναλτι υπέρ", "Πέναλτι που δόθηκαν υπέρ της ομάδας (από τον διαιτητή ή μετά από VAR)."),
    ("pen_against", "Πέναλτι κατά", "Πέναλτι που δόθηκαν κατά της ομάδας."),
    ("var_for", "VAR υπέρ", "Επεμβάσεις VAR που άλλαξαν απόφαση υπέρ της ομάδας."),
    ("var_against", "VAR κατά", "Επεμβάσεις VAR που άλλαξαν απόφαση κατά της ομάδας."),
    ("ann", "Ακυρωμένα γκολ", "Γκολ της ομάδας που δεν μέτρησαν."),
    ("red_own", "Κόκκινες", "Αποβολές παικτών της ομάδας (μαζί με τη 2η κίτρινη)."),
    ("yel", "Κίτρινες", "Κίτρινες κάρτες σε παίκτες της ομάδας."),
    ("foul", "Φάουλ", "Φάουλ που έκανε η ομάδα."),
]

def board(here, T):
    """prerendered saldo board; app.js re-sorts it for the other metrics using data-* attributes."""
    T = sorted(T, key=lambda t: (-t["saldo"], t["team"]))
    mx = max([abs(t["saldo"]) for t in T] + [1])
    out = []
    for i, t in enumerate(T):
        v = t["saldo"]; w = abs(v) / mx * 50
        data = " ".join(f'data-{k.replace("_", "-")}="{t[k]}"' for k, _, _ in METRICS)
        out.append(f'<div class="row{" top" if i < 3 else ""}" {data}><span class="rk">{i+1}</span>'
                   f'<span class="nm">{team_link(here, t["team"])}<span>{t["n"]} αγ.</span></span>'
                   f'<span class="track"><span class="zero"></span><span class="b" style="background:var({"--pos" if v >= 0 else "--neg"});left:{50 if v >= 0 else 50 - w:.2f}%;width:{w:.2f}%"></span></span>'
                   f'<span class="val {cls(v)}">{sg(v)}</span></div>')
    chips = "".join(f'<button type="button" data-m="{k}" data-note="{esc(n)}"{" aria-pressed=\"true\"" if k == "saldo" else " aria-pressed=\"false\""}>{l}</button>' for k, l, n in METRICS)
    return (f'<div class="chips" id="metricChips">{chips}</div><p class="formula" id="formula">{esc(METRICS[0][2])}</p>'
            f'<div class="board" id="board">{"".join(out)}</div>')

def season_switch(here, s):
    if len(SEASONS) < 2: return ""
    opts = "".join(f'<option value="{rel(here, "" if x == CUR else "sezon/" + x + "/")}"{" selected" if x == s else ""}>{x}</option>' for x in SEASONS)
    return f'<label class="season" for="seasonSel">Σεζόν <select id="seasonSel" data-nav>{opts}</select></label>'

def rounds_of(ms):
    seen = {}
    for m in ms: seen.setdefault((PHASE_ORDER.get(m["phase"], 9), m["round"], m["phase"]), m)
    return [seen[k] for k in sorted(seen)]

def home_page(s, path):
    ms = season_ms(s)
    teams = sorted({t for m in ms for t in (m["home"], m["away"])})
    T = [dict(totals(ms, t), team=t) for t in teams]
    last = rounds_of(ms)[-1] if ms else None
    nvar = sum(len(m["var_items"]) for m in ms)
    body = f"""<div class="headrow"><div><h1>Ισοζύγιο διαιτησίας Super League {s}</h1>
<p class="lead">{len(ms)} αγώνες · {nvar} επεμβάσεις VAR που άλλαξαν απόφαση{f' · έως την <a href="{rel(path, round_path(last))}">{round_label(last)}</a>' if last else ''}.</p></div>{season_switch(path, s)}</div>
{board(path, T)}
<p class="note">Το ισοζύγιο μετράει αποφάσεις, όχι λάθη. Μια ομάδα που επιτίθεται περισσότερο κερδίζει φυσιολογικά περισσότερα πέναλτι. Δες τη <a href="{rel(path, "methodologia/")}">μεθοδολογία</a>.</p>"""
    title = f"Στατιστικά διαιτησίας Super League {s} · refstats.gr" if path == "" else f"Ισοζύγιο διαιτησίας Super League {s} · refstats.gr"
    desc = f"Πέναλτι, κάρτες και επεμβάσεις VAR υπέρ και κατά κάθε ομάδας της Super League {s}, αγώνα προς αγώνα."
    page(path, title, desc, body, "1.0" if path == "" else "0.7")

def kpis(items):
    return '<div class="kpis">' + "".join(f'<div class="kpi"><span>{l}</span><b class="{c}">{v}</b></div>' for l, v, c in items) + "</div>"

def match_table(here, ms, team=None):
    h = ('<tr><th>Αγ.</th><th>Ημ/νία</th><th class="l">Αγώνας</th><th>Σκορ</th><th class="l">Διαιτητής</th><th>Πέναλτι</th><th>Κάρτες</th><th>VAR</th></tr>')
    rws = []
    for m in sorted(ms, key=lambda m: (m["season"], PHASE_ORDER.get(m["phase"], 9), m["round"]), reverse=True):
        rws.append(f'<tr><td><a href="{rel(here, round_path(m))}">{m["round"]}{"" if m["phase"] == "Κανονική" else "*"}</a></td><td>{fdate(m["date"])}</td>'
                   f'<td class="l">{team_link(here, m["home"])} – {team_link(here, m["away"])}</td><td>{m["gh"]}–{m["ga"]}</td>'
                   f'<td class="l">{ref_link(here, m["ref"])}</td><td>{m["pen_h"]}–{m["pen_a"]}</td>'
                   f'<td><i class="cy"></i>{m["yel_h"]}–{m["yel_a"]} <i class="cr"></i>{m["red_h"]}–{m["red_a"]}</td><td>{m["var_h"]}–{m["var_a"]}</td></tr>')
    return f'<div class="tablewrap"><table class="t">{h}{"".join(rws)}</table></div><p class="note">Στις στήλες με δύο νούμερα, πρώτα ο γηπεδούχος.</p>'

def var_list(here, ms, team=None):
    items = [(m, v) for m in ms for v in m["var_items"]]
    if not items: return '<p class="note">Δεν έχει καταγραφεί επέμβαση VAR που να άλλαξε απόφαση.</p>'
    out = []
    for m, v in sorted(items, key=lambda x: (x[0]["season"], PHASE_ORDER.get(x[0]["phase"], 9), x[0]["round"], minute_key(x[1])), reverse=True):
        tag = ""
        if team:
            tag = '<span class="pill pos">υπέρ</span>' if v["ben"] == team else '<span class="pill neg">κατά</span>' if v["ben"] else ""
        src = f' · <a href="{esc(v["src"])}" rel="nofollow noopener" target="_blank">πηγή</a>' if v["src"].startswith("http") else ""
        out.append(f'<li><div class="vh"><b>{esc(v["min"])}\'</b> {esc(v["type"])} · υπέρ {esc(v["ben"] or "—")} {tag}</div>'
                   f'<div class="vd">{esc(v["desc"])}</div><div class="vm"><a href="{rel(here, round_path(m))}">{round_label(m)}</a> · {esc(m["home"])}–{esc(m["away"])}{src}</div></li>')
    return f'<ul class="varlist">{"".join(out)}</ul>'

def team_page(team):
    path = f"omades/{TEAMS[team]}/"
    ms = [m for m in MATCHES if team in (m["home"], m["away"])]
    cur = [m for m in ms if m["season"] == CUR]
    t = totals(cur, team)
    allt = totals(ms, team)
    k = kpis([("Ισοζύγιο", sg(t["saldo"]), cls(t["saldo"])), ("Πέναλτι υπέρ / κατά", f'{t["pen_for"]} / {t["pen_against"]}', ""),
              ("VAR υπέρ / κατά", f'{t["var_for"]} / {t["var_against"]}', ""), ("Κόκκινες δικές / αντιπάλων", f'{t["red_own"]} / {t["red_opp"]}', ""),
              ("Κίτρινες", t["yel"], ""), ("Αγώνες", t["n"], "")])
    # by referee, all seasons, vs team average
    avg = allt["saldo"] / allt["n"] if allt["n"] else 0
    byref = defaultdict(list)
    for m in ms:
        if m["ref"]: byref[m["ref"]].append(m)
    rr = []
    for p, lst in byref.items():
        tt = totals(lst, team); per = tt["saldo"] / tt["n"]
        rr.append((per - avg, p, tt, per))
    rr.sort(key=lambda x: (-x[0], x[1]))
    rt = "".join(f'<tr><td class="l">{ref_link(path, p)}{" <span class=\"pill\">μικρό δείγμα</span>" if tt["n"] < 5 else ""}</td><td>{tt["n"]}</td>'
                 f'<td>{tt["w"]}-{tt["d"]}-{tt["l"]}</td><td class="{cls(tt["saldo"])}">{sg(tt["saldo"])}</td><td>{per:+.2f}</td><td class="{cls(round(d, 2))}"><b>{d:+.2f}</b></td></tr>'
                 for d, p, tt, per in rr)
    body = f"""<p class="crumb"><a href="{rel(path, "")}">Ομάδες</a> / {esc(team)}</p>
<h1>{esc(team)}: στατιστικά διαιτησίας</h1>
<p class="lead">Σεζόν {CUR}: {t["w"]} νίκες, {t["d"]} ισοπαλίες, {t["l"]} ήττες σε {t["n"]} αγώνες.</p>
{k}
<h2>Με κάθε διαιτητή</h2>
<p class="lead">Ισοζύγιο ανά αγώνα με κάθε διαιτητή, σε σύγκριση με τον μέσο όρο της ομάδας ({avg:+.2f}). Όλες οι καταγεγραμμένες σεζόν.</p>
<div class="tablewrap"><table class="t"><tr><th class="l">Διαιτητής</th><th>Αγώνες</th><th>Ν-Ι-Η</th><th>Ισοζύγιο</th><th>Ανά αγώνα</th><th>Διαφορά</th></tr>{rt}</table></div>
<h2>Φάσεις VAR</h2>
{var_list(path, ms, team)}
<h2>Αγώνες</h2>
{match_table(path, ms, team)}"""
    page(path, f"{team}: διαιτητές, πέναλτι, VAR · Super League {CUR}",
         f"Ισοζύγιο διαιτησίας του {team} στη Super League {CUR}: πέναλτι υπέρ και κατά, κάρτες, επεμβάσεις VAR και στατιστικά με κάθε διαιτητή.", body, "0.8")

def ref_stats(lst):
    n = len(lst)
    pen = sum(m["pen_h"] + m["pen_a"] for m in lst); yel = sum(m["yel_h"] + m["yel_a"] for m in lst)
    red = sum(m["red_h"] + m["red_a"] for m in lst); var = sum(len(m["var_items"]) for m in lst)
    hw = sum(1 for m in lst if m["gh"] > m["ga"])
    return {"n": n, "pen": pen, "yel": yel, "red": red, "var": var, "ppm": pen / n if n else 0, "ypm": yel / n if n else 0, "hwp": hw / n if n else 0}

def refs_index():
    path = "diaitites/"
    ms = season_ms(CUR)
    by = defaultdict(list); byvar = defaultdict(int)
    for m in ms:
        if m["ref"]: by[m["ref"]].append(m)
        if m["var"]: byvar[m["var"]] += 1
    lg = ref_stats(ms)
    rows_ = sorted(((p, ref_stats(l)) for p, l in by.items()), key=lambda x: (-x[1]["n"], x[0]))
    tr = "".join(f'<tr><td class="l">{ref_link(path, p)}{" <span class=\"pill\">" + esc(REFS[p]["assoc"]) + "</span>" if REFS[p]["foreign"] else ""}</td>'
                 f'<td data-v="{s["n"]}">{s["n"]}</td><td data-v="{byvar.get(p, 0)}">{byvar.get(p, 0)}</td><td data-v="{s["ppm"]:.3f}">{s["ppm"]:.2f}</td>'
                 f'<td data-v="{s["ypm"]:.3f}">{s["ypm"]:.2f}</td><td data-v="{s["red"]}">{s["red"]}</td><td data-v="{s["var"]}">{s["var"]}</td><td data-v="{s["hwp"]:.3f}">{round(s["hwp"] * 100)}%</td></tr>'
                 for p, s in rows_)
    vonly = sorted(p for p in byvar if p not in by)
    vo = f'<p class="note">Μόνο ως VAR: {", ".join(ref_link(path, p) for p in vonly)}.</p>' if vonly else ""
    body = f"""<h1>Διαιτητές Super League {CUR}</h1>
<p class="lead">Μέσος όρος πρωταθλήματος: {lg["ppm"]:.2f} πέναλτι και {lg["ypm"]:.2f} κίτρινες ανά αγώνα, νίκη γηπεδούχου στο {round(lg["hwp"] * 100)}%. Πάτησε μια στήλη για ταξινόμηση.</p>
<div class="tablewrap"><table class="t sortable"><thead><tr><th class="l">Διαιτητής</th><th>Αγώνες</th><th>Ως VAR</th><th>Πέναλτι/αγ.</th><th>Κίτρινες/αγ.</th><th>Κόκκινες</th><th>Επεμβ. VAR</th><th>Νίκες γηπ.</th></tr></thead><tbody>{tr}</tbody></table></div>
{vo}"""
    page(path, f"Διαιτητές Super League {CUR}: πέναλτι, κάρτες, VAR · refstats.gr",
         f"Στατιστικά κάθε διαιτητή της Super League {CUR}: αγώνες, πέναλτι και κάρτες ανά αγώνα, επεμβάσεις VAR, νίκες γηπεδούχου.", body, "0.9")

def ref_page(p):
    path = f"diaitites/{REFS[p]['slug']}/"
    lst = [m for m in MATCHES if m["ref"] == p]
    asvar = [m for m in MATCHES if m["var"] == p]
    s = ref_stats(lst); lg = ref_stats(season_ms(CUR))
    info = REFS[p]["assoc"]
    head = f"""<p class="crumb"><a href="{rel(path, "diaitites/")}">Διαιτητές</a> / {esc(p)}</p>
<h1>{esc(p)}: στατιστικά διαιτητή</h1>
<p class="lead">{esc(("Ένωση/χώρα: " + info + ". ") if info else "")}{s["n"]} αγώνες ως κύριος διαιτητής, {len(asvar)} ως VAR.</p>"""
    blocks = [head]
    if lst:
        blocks.append(kpis([("Αγώνες", s["n"], ""), ("Πέναλτι / αγώνα", f'{s["ppm"]:.2f}', ""), ("Κίτρινες / αγώνα", f'{s["ypm"]:.2f}', ""),
                            ("Κόκκινες", s["red"], ""), ("Επεμβάσεις VAR", s["var"], ""), ("Νίκες γηπεδούχου", f'{round(s["hwp"] * 100)}%', "")]))
        blocks.append(f'<p class="note">Μέσος όρος πρωταθλήματος {CUR}: {lg["ppm"]:.2f} πέναλτι και {lg["ypm"]:.2f} κίτρινες ανά αγώνα.</p>')
        teams = sorted({t for m in lst for t in (m["home"], m["away"])})
        rr = []
        for t in teams:
            mine = totals(lst, t); allt = totals([m for m in MATCHES if t in (m["home"], m["away"])], t)
            per = mine["saldo"] / mine["n"]; avg = allt["saldo"] / allt["n"]
            rr.append((per - avg, t, mine, per, avg))
        rr.sort(key=lambda x: (-x[0], x[1]))
        tr = "".join(f'<tr><td class="l">{team_link(path, t)}{" <span class=\"pill\">μικρό δείγμα</span>" if mm["n"] < 5 else ""}</td><td>{mm["n"]}</td>'
                     f'<td class="{cls(mm["saldo"])}">{sg(mm["saldo"])}</td><td>{per:+.2f}</td><td>{avg:+.2f}</td><td class="{cls(round(d, 2))}"><b>{d:+.2f}</b></td></tr>'
                     for d, t, mm, per, avg in rr)
        blocks.append(f"""<h2>Ισοζύγιο ανά ομάδα</h2>
<p class="lead">Η διαφορά δείχνει πόσο απέχει το ισοζύγιο της ομάδας ανά αγώνα με αυτόν τον διαιτητή από τον μέσο όρο της με όλους.</p>
<div class="tablewrap"><table class="t"><tr><th class="l">Ομάδα</th><th>Αγώνες</th><th>Ισοζύγιο</th><th>Ανά αγώνα</th><th>Μ.ο. ομάδας</th><th>Διαφορά</th></tr>{tr}</table></div>
<h2>Φάσεις VAR στους αγώνες του</h2>{var_list(path, lst)}
<h2>Αγώνες</h2>{match_table(path, lst)}""")
    if asvar:
        tr = "".join(f'<tr><td><a href="{rel(path, round_path(m))}">{m["round"]}</a></td><td class="l">{esc(m["home"])} – {esc(m["away"])}</td>'
                     f'<td class="l">{ref_link(path, m["ref"])}</td><td>{len(m["var_items"])}</td></tr>' for m in reversed(asvar))
        blocks.append(f'<h2>Ως VAR</h2><div class="tablewrap"><table class="t"><tr><th>Αγ.</th><th class="l">Αγώνας</th><th class="l">Διαιτητής</th><th>Επεμβάσεις</th></tr>{tr}</table></div>')
    page(path, f"{p}: διαιτητής Super League, στατιστικά · refstats.gr",
         f"Ο διαιτητής {p} στη Super League: αγώνες, πέναλτι και κάρτες ανά αγώνα, επεμβάσεις VAR και ισοζύγιο κάθε ομάδας μαζί του.", body="\n".join(blocks), priority="0.7")

def round_page(s, first):
    ms = [m for m in MATCHES if m["season"] == s and m["phase"] == first["phase"] and m["round"] == first["round"]]
    path = round_path(first)
    allr = rounds_of(season_ms(s)); i = [round_path(x) for x in allr].index(path)
    prev = f'<a href="{rel(path, round_path(allr[i-1]))}">← {round_label(allr[i-1])}</a>' if i > 0 else "<span></span>"
    nxt = f'<a href="{rel(path, round_path(allr[i+1]))}">{round_label(allr[i+1])} →</a>' if i < len(allr) - 1 else "<span></span>"
    cards = []
    for m in ms:
        v = "".join(f'<div class="vx"><b>{esc(x["min"])}\'</b> {esc(x["type"])} · υπέρ {esc(x["ben"] or "—")}<span>{esc(x["desc"])}</span></div>' for x in m["var_items"])
        p = m["pen_h"] + m["pen_a"]; r = m["red_h"] + m["red_a"]
        y = m["yel_h"] + m["yel_a"]
        ev = (f'<i class="y">{y} κίτριν{"η" if y == 1 else "ες"}</i>' + (f'<i class="r">{r} κόκκιν{"ες" if r > 1 else "η"}</i>' if r else "")
              + (f'<i class="p">{p} πέναλτι</i>' if p else "") + (f'<i class="v">{len(m["var_items"])} VAR</i>' if m["var_items"] else ""))
        cards.append(f'<article class="m"><div class="sc"><span class="h">{team_link(path, m["home"])}</span><b>{m["gh"]}–{m["ga"]}</b><span class="a">{team_link(path, m["away"])}</span></div>'
                     f'<div class="ref">{fdate(m["date"])} · Διαιτητής: {ref_link(path, m["ref"])} · VAR: {ref_link(path, m["var"])}</div><div class="ev">{ev}</div>{v}</article>')
    body = f"""<p class="crumb"><a href="{rel(path, "agonistiki/")}">Αγωνιστικές</a> / {s} / {round_label(first)}</p>
<h1>Η διαιτησία της {round_gen(first)} · Super League {s}</h1>
<p class="lead">Διαιτητές, πέναλτι, κάρτες και επεμβάσεις VAR σε κάθε αγώνα.</p>
<div class="matches">{"".join(cards)}</div>
<div class="pager">{prev}{nxt}</div>"""
    page(path, f"Διαιτησία {round_gen(first)} Super League {s} · refstats.gr",
         f"Οι διαιτητές της {round_gen(first)} της Super League {s}, τα πέναλτι, οι κάρτες και οι επεμβάσεις VAR αγώνα προς αγώνα.", body, "0.6")

def rounds_index():
    path = "agonistiki/"
    parts = []
    for s in SEASONS:
        links = "".join(f'<a href="{rel(path, round_path(m))}">{m["round"]}{"" if m["phase"] == "Κανονική" else " " + esc(m["phase"])}</a>' for m in rounds_of(season_ms(s)))
        parts.append(f'<h2>Σεζόν {s}</h2><div class="roundlinks">{links}</div>')
    page(path, "Αγωνιστικές Super League: διαιτητές και VAR · refstats.gr",
         "Όλες οι αγωνιστικές της Super League με τους διαιτητές, τα πέναλτι, τις κάρτες και τις επεμβάσεις VAR κάθε αγώνα.",
         "<h1>Αγωνιστικές</h1>" + "".join(parts), "0.5")

def static_pages():
    page("methodologia/", "Μεθοδολογία · refstats.gr", "Πώς καταγράφει το refstats.gr τα στατιστικά διαιτησίας: τι μετράει ως πέναλτι, φάση VAR και ισοζύγιο διαιτησίας.", f"""<div class="prose">
<h1>Πώς μετράμε</h1>
<p>Καταγράφουμε αποφάσεις, όχι κρίσεις. Δεν λέμε αν ένα πέναλτι ήταν σωστό. Μετράμε ότι δόθηκε.</p>
<h2>Ισοζύγιο διαιτησίας</h2>
<p><code>(πέναλτι υπέρ + VAR υπέρ + κόκκινες αντιπάλου) − (πέναλτι κατά + VAR κατά + δικές κόκκινες)</code></p>
<p>Ένα πέναλτι που δόθηκε μετά από VAR μετράει και στα πέναλτι και στις φάσεις VAR.</p>
<h2>Φάσεις VAR</h2>
<p>Μετράει μόνο η επέμβαση που άλλαξε την απόφαση του διαιτητή: πέναλτι που δόθηκε ή ακυρώθηκε, κόκκινη που δόθηκε ή ακυρώθηκε, γκολ που ακυρώθηκε ή κατοχυρώθηκε. Ένας έλεγχος που επιβεβαίωσε την απόφαση του γηπέδου δεν μετράει. Κάθε επέμβαση χρεώνεται υπέρ της ομάδας που ωφελήθηκε.</p>
<h2>Κάρτες και γκολ</h2>
<ul><li>Κόκκινες: απευθείας κόκκινες και αποβολές με δεύτερη κίτρινη. Η δεύτερη κίτρινη δεν μετράει στις κίτρινες.</li>
<li>Κάρτες σε προπονητές και πάγκο δεν μετράνε.</li>
<li>Ακυρωμένα γκολ: γκολ της ομάδας που δεν μέτρησαν, είτε από τον διαιτητή ή τον βοηθό είτε μετά από VAR.</li></ul>
<h2>Τι δεν δείχνουν τα νούμερα</h2>
<p>Ένα θετικό ισοζύγιο δεν σημαίνει εύνοια. Μια ομάδα που επιτίθεται περισσότερο κερδίζει περισσότερα πέναλτι. Γι' αυτό στις σελίδες ομάδων και διαιτητών συγκρίνουμε κάθε ομάδα με τον δικό της μέσο όρο. Συνδυασμοί διαιτητή και ομάδας με λιγότερους από 5 αγώνες σημειώνονται ως μικρό δείγμα.</p>
<h2>Πηγές</h2>
<p>Ορισμοί της ΚΕΔ, επίσημα φύλλα αγώνα και βίντεο των φάσεων. Κάθε αγώνας και κάθε φάση VAR στη βάση έχει πηγή. Αν βρεις λάθος, στείλε μας την πηγή και θα το διορθώσουμε.</p>
</div>""", "0.4")
    page("aporrito/", "Πολιτική απορρήτου · refstats.gr", "Πολιτική απορρήτου του refstats.gr.", """<div class="prose">
<h1>Πολιτική απορρήτου</h1>
<p>Το refstats.gr δεν χρησιμοποιεί cookies, δεν ζητά προσωπικά στοιχεία και δεν εμφανίζει διαφημίσεις.</p>
<p>Η σελίδα φορτώνει γραμματοσειρές από τις Google Fonts, οπότε η Google λαμβάνει τη διεύθυνση IP του επισκέπτη κατά τη φόρτωσή τους. Η φιλοξενία γίνεται στο GitHub Pages, που κρατά τεχνικά αρχεία καταγραφής για λόγους ασφαλείας.</p>
<p>Αν στο μέλλον προστεθούν μετρήσεις επισκεψιμότητας ή διαφημίσεις, η σελίδα αυτή θα ενημερωθεί πριν από την ενεργοποίησή τους.</p>
</div>""", "0.1")

# ---------------------------------------------------------------- build
if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)
shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(OUT, "assets"))
home_page(CUR, "")
for s in SEASONS[1:]:
    home_page(s, f"sezon/{s}/")
for t in sorted({t for m in MATCHES for t in (m["home"], m["away"])}):
    team_page(t)
refs_index()
for p in sorted({p for m in MATCHES for p in (m["ref"], m["var"]) if p}):
    ref_page(p)
for s in SEASONS:
    for first in rounds_of(season_ms(s)):
        round_page(s, first)
rounds_index()
static_pages()
# 404, robots, sitemap, CNAME
page("404/", "Η σελίδα δεν βρέθηκε · refstats.gr", "", f'<h1>Η σελίδα δεν βρέθηκε</h1><p class="lead"><a href="/">Επιστροφή στην αρχική</a></p>', canonical="")
shutil.move(os.path.join(OUT, "404", "index.html"), os.path.join(OUT, "404.html")); os.rmdir(os.path.join(OUT, "404"))
open(os.path.join(OUT, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
today = NOW.strftime("%Y-%m-%d")
open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8").write(
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + "".join(f"<url><loc>{esc(SITE + '/' + p)}</loc><lastmod>{today}</lastmod><priority>{pr}</priority></url>\n" for p, pr in PAGES)
    + "</urlset>\n")
if CFG.get("custom_domain"):
    open(os.path.join(OUT, "CNAME"), "w").write(CFG["custom_domain"] + "\n")
open(os.path.join(OUT, ".nojekyll"), "w").write("")
print(f"OK: {len(MATCHES)} αγώνες, {sum(len(m['var_items']) for m in MATCHES)} φάσεις VAR, {len(PAGES)} σελίδες -> {OUT}")
