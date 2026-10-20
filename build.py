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

def fetch_opt(name):
    """Sheets added later (τηλεκριτική). Missing link/file = feature off."""
    try:
        if LOCAL:
            f = os.path.join(LOCAL, name + ".csv")
            return open(f, encoding="utf-8").read() if os.path.exists(f) else ""
        return fetch(name) if CFG["csv"].get(name) else ""
    except Exception as e:
        print(f"Προειδοποίηση: δεν διαβάστηκε το φύλλο {name}: {e}")
        return ""

_TK = None
def rows_opt(name):
    """Returns the τηλεκριτική sheet `name`, recognised by its column headers,
    so it does not matter which link was put under which key in config.json."""
    global _TK
    if _TK is None:
        _TK = {}
        for k in ("sxoliastes", "faseis", "gnomes", "anakoinoseis"):
            text = fetch_opt(k)
            if not text.strip():
                continue
            hdr = {h.strip() for h in next(csv.reader(io.StringIO(text)))}
            kind = "anakoinoseis" if "Περίληψη" in hdr else "gnomes" if "Ετυμηγορία" in hdr else "faseis" if "Κατηγορία" in hdr else "sxoliastes" if "Ιδιότητα" in hdr else k
            data = list(csv.DictReader(io.StringIO(text)))
            _TK[kind] = [{(a or "").strip(): (b or "").strip() for a, b in d.items()} for d in data]
    return _TK.get(name, [])

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
ALLM = {}
for r in rows("agones"):
    if not (r.get("ID") and r.get("Γηπεδούχος") and r.get("Φιλοξενούμενος")):
        continue
    ALLM[r["ID"]] = {"id": r["ID"], "season": r["Σεζόν"], "phase": r.get("Φάση") or "Κανονική", "round": num(r["Αγωνιστική"]),
                     "date": pdate(r.get("Ημερομηνία", "")), "home": r["Γηπεδούχος"], "away": r["Φιλοξενούμενος"], "ref": r.get("Διαιτητής", ""), "var": r.get("VAR", "")}
    # A match appears on the site only once its card/penalty numbers are filled in.
    # Rows with these cells still empty (e.g. pasted fixtures) are skipped until completed.
    if not all((r.get(c) or "").strip() for c in ("Πέναλτι Γηπ", "Πέναλτι Φιλ", "Κίτρινες Γηπ", "Κίτρινες Φιλ")):
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

# ---------------------------------------------------------------- τηλεκριτική
KIND_ORDER = {"Τηλεκριτικός": 0, "Δημοσιογράφος": 1}
CRIT = {}
for i, r in enumerate(rows_opt("sxoliastes")):
    n = r.get("Σχολιαστής", "")
    if n:
        CRIT[n] = {"name": n, "slug": r.get("Slug (URL)") or slugify(n), "kind": r.get("Ιδιότητα") or "Τηλεκριτικός",
                   "outlet": r.get("Μέσο", ""), "order": i}
PH, PHBY = [], {}
WARN = []
for i, r in enumerate(rows_opt("faseis"), start=2):
    code, m = r.get("Κωδικός φάσης", ""), ALLM.get(r.get("ID αγώνα", ""))
    if not any(r.values()): continue
    if not code: WARN.append(f"Φάσεις γρ.{i}: λείπει ο Κωδικός φάσης"); continue
    if not m: WARN.append(f"Φάσεις γρ.{i}: το ID αγώνα «{r.get('ID αγώνα', '')}» δεν υπάρχει στους Αγώνες"); continue
    if code in PHBY: WARN.append(f"Φάσεις γρ.{i}: ο κωδικός «{code}» υπάρχει ήδη, αγνοήθηκε"); continue
    p = {"code": code, "m": m, "min": r.get("Λεπτό", ""), "cat": r.get("Κατηγορία", ""), "dec": r.get("Απόφαση διαιτητή", ""),
         "ben": r.get("Ωφελημένη ομάδα", ""), "var": r.get("Επέμβαση VAR", "") == "Ναι", "desc": r.get("Περιγραφή", ""),
         "video": r.get("Βίντεο", ""), "ops": {}}
    PH.append(p); PHBY[code] = p
for i, r in enumerate(rows_opt("gnomes"), start=2):
    p, c, v = PHBY.get(r.get("Κωδικός φάσης", "")), r.get("Σχολιαστής", ""), r.get("Ετυμηγορία", "")
    if not any(r.values()): continue
    if not p: WARN.append(f"Γνώμες γρ.{i}: ο κωδικός «{r.get('Κωδικός φάσης', '')}» δεν υπάρχει στις Φάσεις"); continue
    if v not in ("Σωστή", "Λάθος", "Οριακή"): WARN.append(f"Γνώμες γρ.{i}: άγνωστη Ετυμηγορία «{v}»"); continue
    if not c: WARN.append(f"Γνώμες γρ.{i}: λείπει ο Σχολιαστής"); continue
    if p and c and v in ("Σωστή", "Λάθος", "Οριακή"):
        CRIT.setdefault(c, {"name": c, "slug": slugify(c), "kind": "Τηλεκριτικός", "outlet": "", "order": 999})
        p["ops"][c] = {"v": v, "should": r.get("Τι έπρεπε να δοθεί", ""), "why": r.get("Αιτιολογία", ""), "src": r.get("Πηγή", "")}
WARN += [f"Φάσεις: η φάση «{p['code']}» δεν έχει καμία γνώμη, δεν εμφανίζεται" for p in PH if not p["ops"]]
WARN += [f"Φάσεις: η φάση «{p['code']}» δεν έχει Ωφελημένη ομάδα του αγώνα" for p in PH if p["ops"] and p["ben"] not in (p["m"]["home"], p["m"]["away"])]
PH = [p for p in PH if p["ops"]]
PH.sort(key=lambda p: (p["m"]["season"], PHASE_ORDER.get(p["m"]["phase"], 9), p["m"]["round"], p["m"]["date"] or datetime.min, p["m"]["home"], minute_key({"min": p["min"]})))
CRITICS = sorted([c for c in CRIT.values() if any(c["name"] in p["ops"] for p in PH)], key=lambda c: (KIND_ORDER.get(c["kind"], 2), c["order"], c["name"]))
# ---- official club statements about the refereeing of a match
ANN = []
for r in rows_opt("anakoinoseis"):
    m = ALLM.get(r.get("ID αγώνα", "")); t = r.get("Ομάδα", "")
    if m and t in (m["home"], m["away"]) and r.get("Περίληψη"):
        ANN.append({"m": m, "team": t, "date": pdate(r.get("Ημερομηνία", "")), "text": r["Περίληψη"], "link": r.get("Link", "")})
ANN.sort(key=lambda a: (a["date"] or datetime.min, a["m"]["date"] or datetime.min), reverse=True)
TK = bool(PH or ANN)
def consensus(p):
    ok = sum(1 for c, o in p["ops"].items() if CRIT[c]["kind"] != "Δημοσιογράφος" and o["v"] == "Σωστή")
    bad = sum(1 for c, o in p["ops"].items() if CRIT[c]["kind"] != "Δημοσιογράφος" and o["v"] == "Λάθος")
    if not ok and not bad: return None, ok, bad
    return ("Λάθος" if bad > ok else "Σωστή" if ok > bad else "Ισοψηφία"), ok, bad

# ---- who did each critic side with: the referee or the team that protested
SHORT = {"Ολυμπιακός": "ΟΛΥ", "Παναθηναϊκός": "ΠΑΟ", "ΑΕΚ": "ΑΕΚ", "ΠΑΟΚ": "ΠΑΟΚ", "Άρης": "ΑΡΗΣ", "ΟΦΗ": "ΟΦΗ",
         "Αστέρας Τρίπολης": "ΑΣΤ", "Ατρόμητος": "ΑΤΡ", "Βόλος": "ΒΟΛ", "Ηρακλής": "ΗΡΑ", "Καλαμάτα": "ΚΑΛ",
         "Κηφισιά": "ΚΗΦ", "Λεβαδειακός": "ΛΕΒ", "Παναιτωλικός": "ΠΑΝ", "Λαμία": "ΛΑΜ", "Πανσερραϊκός": "ΠΣΕ",
         "Αστέρας Aktor": "ΑΣΤ", "ΑΕΛ": "ΑΕΛ", "Athens Kallithea": "ΚΑΛΛ", "Athens Kallithea FC": "ΚΑΛΛ"}
def short(t): return SHORT.get(t, t)
def protester(p):
    m = p["m"]
    if p["ben"] == m["home"]: return m["away"]
    if p["ben"] == m["away"]: return m["home"]
    return None
MIN_N, MIN_M = 10, 3  # a lean figure needs at least 10 decisive phases from at least 3 matches
def is_tele(name): return CRIT[name]["kind"] != "Δημοσιογράφος"
def _pro(p, team, v):
    """True if verdict v favours `team`: it protested and the critic said Λάθος,
    or the opponent protested and the critic said Σωστή."""
    return (v == "Λάθος") if protester(p) == team else (v == "Σωστή")
def lean(cname, team, mode):
    """mode 'prot': phases where `team` protested · 'opp': where its opponent protested · 'all': both.
    Returns (n, rate of the critic in favour of team, rate of the other τηλεκριτικοί on the same phases)."""
    sel = []
    for p in PH:
        pr = protester(p)
        if not pr or team not in (p["m"]["home"], p["m"]["away"]): continue
        if mode == "prot" and pr != team: continue
        if mode == "opp" and pr == team: continue
        o = p["ops"].get(cname)
        if o and o["v"] in ("Σωστή", "Λάθος"): sel.append((p, o["v"]))
    n = len(sel)
    if not n: return 0, None, None
    if len({p["m"]["id"] for p, _ in sel}) < MIN_M: n = min(n, MIN_N - 1)  # too few matches: treat as not enough data
    mine = sum(1 for p, v in sel if _pro(p, team, v)) / n
    oth = [(p, o["v"]) for p, _ in sel for c, o in p["ops"].items() if c != cname and is_tele(c) and o["v"] in ("Σωστή", "Λάθος")]
    others = sum(1 for p, v in oth if _pro(p, team, v)) / len(oth) if oth else None
    return n, mine, others
def lean_teams():
    ts = {}
    for p in PH:
        if protester(p):
            for t in (p["m"]["home"], p["m"]["away"]): ts[t] = ts.get(t, 0) + 1
    big = {"Ολυμπιακός": 0, "Παναθηναϊκός": 1, "ΑΕΚ": 2, "ΠΑΟΚ": 3, "Άρης": 4}
    return [t for t, _ in sorted(ts.items(), key=lambda x: (big.get(x[0], 9), -x[1], x[0]))]

# ---------------------------------------------------------------- stats
KEYS = ["n", "pen_for", "pen_against", "var_for", "var_against", "red_opp", "red_own", "yel", "yel_opp", "foul", "ann", "w", "d", "l"]
def side(m, team):
    h = team == m["home"]; o, p = ("h", "a") if h else ("a", "h")
    gf, ga = (m["gh"], m["ga"]) if h else (m["ga"], m["gh"])
    return {"n": 1, "pen_for": m["pen_" + o], "pen_against": m["pen_" + p], "var_for": m["var_" + o], "var_against": m["var_" + p],
            "red_opp": m["red_" + p], "red_own": m["red_" + o], "yel": m["yel_" + o], "yel_opp": m["yel_" + p], "foul": m["foul_" + o], "ann": m["ann_" + o],
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

GA4 = (CFG.get("ga4_id") or "").strip()
if GA4 and not re.fullmatch(r"G-[A-Z0-9]+", GA4):
    print(f"Προειδοποίηση: το ga4_id «{GA4}» δεν μοιάζει με κωδικό GA4 (G-XXXXXXX) και αγνοήθηκε.")
    GA4 = ""
CONSENT = ""
if GA4:
    CONSENT = """<div id="ck" hidden role="dialog" aria-label="Cookies" style="position:fixed;left:16px;right:16px;bottom:calc(16px + env(safe-area-inset-bottom,0px));max-width:560px;margin:0 auto;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:14px 16px;z-index:50;font-size:14px">
<p style="margin:0 0 10px">Με τη συγκατάθεσή σου χρησιμοποιούμε cookies του Google Analytics για να μετράμε την επισκεψιμότητα. <a href="/aporrito/">Περισσότερα</a></p>
<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" data-c="yes" style="font:inherit;font-weight:600;padding:8px 14px;border-radius:6px;border:1px solid var(--ink);background:var(--ink);color:var(--bg);cursor:pointer">Αποδοχή</button><button type="button" data-c="no" style="font:inherit;font-weight:600;padding:8px 14px;border-radius:6px;border:1px solid var(--ink);background:var(--surface);color:var(--ink);cursor:pointer">Απόρριψη</button></div></div>
<script>(function(){var id="%s",b=document.getElementById("ck"),c;
function load(){if(window.gtag)return;var s=document.createElement("script");s.async=true;s.src="https://www.googletagmanager.com/gtag/js?id="+id;document.head.appendChild(s);window.dataLayer=window.dataLayer||[];window.gtag=function(){dataLayer.push(arguments)};gtag("js",new Date());gtag("config",id);}
try{c=localStorage.getItem("rs_consent")}catch(e){}
if(c==="yes")load();else if(c!=="no")b.hidden=false;
b.addEventListener("click",function(e){var v=e.target.getAttribute("data-c");if(!v)return;try{localStorage.setItem("rs_consent",v)}catch(x){}b.hidden=true;if(v==="yes")load();});
var l=document.getElementById("ckset");if(l)l.addEventListener("click",function(e){e.preventDefault();try{localStorage.removeItem("rs_consent")}catch(x){}b.hidden=false;});})();</script>""" % GA4

def page(path, title, desc, body, priority="0.6", canonical=None):
    here = path
    nav = [("", "Ομάδες"), ("diaitites/", "Διαιτητές"), ("agonistiki/", "Αγωνιστικές")] + ([("tilekritiki/", "Τηλεκριτική")] if TK else []) + [("methodologia/", "Μεθοδολογία")]
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
  <p>Τελευταία ενημέρωση: {UPDATED} · <a href="{rel(here, "methodologia/")}">Μεθοδολογία</a> · <a href="{rel(here, "aporrito/")}">Πολιτική απορρήτου</a>{' · <a href="#" id="ckset">Ρυθμίσεις cookies</a>' if GA4 else ""}</p>
</footer>
</div>
<script src="{"../" * here.count("/")}assets/app.js" defer></script>
{CONSENT}
</body>
</html>"""
    d = os.path.join(OUT, path)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(html)
    if canonical is None:
        PAGES.append((path, priority))

METRICS = [
    ("saldo", "Ισοζύγιο", "Ισοζύγιο: (πέναλτι + VAR + κόκκινες υπέρ) − (πέναλτι + VAR + κόκκινες κατά). Κόκκινες υπέρ: αποβολές αντιπάλων."),
    ("pen_for", "Πέναλτι υπέρ", "Πέναλτι που δόθηκαν υπέρ της ομάδας (από τον διαιτητή ή μετά από VAR)."),
    ("pen_against", "Πέναλτι κατά", "Πέναλτι που δόθηκαν κατά της ομάδας."),
    ("var_for", "VAR υπέρ", "Επεμβάσεις VAR που άλλαξαν απόφαση υπέρ της ομάδας."),
    ("var_against", "VAR κατά", "Επεμβάσεις VAR που άλλαξαν απόφαση κατά της ομάδας."),
    ("ann", "Ακυρωθέντα γκολ", "Γκολ της ομάδας που δεν μέτρησαν."),
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

def _leader(items, key, low=False):
    """items: list of (name, value). Returns (value, [names]) for the max (or min)."""
    items = [x for x in items if x[1] is not None]
    if not items: return None, []
    v = (min if low else max)(x[1] for x in items)
    return v, sorted(n for n, x in items if x == v)

def podiums(here, ms, T):
    if not ms: return ""
    n = len(ms)
    pen = sum(m["pen_h"] + m["pen_a"] for m in ms); red = sum(m["red_h"] + m["red_a"] for m in ms)
    yel = sum(m["yel_h"] + m["yel_a"] for m in ms); var = sum(len(m["var_items"]) for m in ms)
    vann = defaultdict(int)
    for m in ms:
        for v in m["var_items"]:
            if v["type"] == "Ακυρώθηκε γκολ" and v["ben"] in (m["home"], m["away"]):
                vann[m["away"] if v["ben"] == m["home"] else m["home"]] += 1
    strip = (f'<div class="tot"><span class="t-pen"><b>{pen}</b> πέναλτι</span><span class="t-red"><b>{red}</b> κόκκινες</span>'
             f'<span class="t-ann"><b>{sum(vann.values())}</b> γκολ ακυρώθηκαν από VAR</span><span class="t-var"><b>{var}</b> επεμβάσεις VAR</span>'
             f'<span class="t-yel"><b>{yel}</b> κίτρινες</span><span class="t-n">{n} αγώνες</span></div>')
    nt = len(T) or 1
    by = {t["team"]: t for t in T}
    def names(lst, kind):
        if not lst: return "—"
        link = (lambda x: team_link(here, x)) if kind == "team" else (lambda x: ref_link(here, x))
        return ", ".join(link(x) for x in lst[:2]) + (f" +{len(lst) - 2}" if len(lst) > 2 else "")
    cards = []
    def card(cls_, label, val, sub, who, kind):
        tag = '<i class="rf">ΔΙΑΙΤ.</i>' if kind == "ref" else ""
        cards.append(f'<div class="pod {cls_}"><span class="pl">{label}</span><b class="pv">{val}</b><span class="ps">{sub}</span>'
                     f'<span class="pw">{tag}{names(who, kind)}</span></div>')
    v, w = _leader([(t["team"], t["saldo"]) for t in T], "saldo")
    card("c-green", "Θετικότερο ισοζύγιο", sg(v), "ισοζύγιο διαιτησίας", w, "team")
    v, w = _leader([(t["team"], t["saldo"]) for t in T], "saldo", low=True)
    card("c-red", "Αρνητικότερο ισοζύγιο", sg(v), "ισοζύγιο διαιτησίας", w, "team")
    avgp = sum(t["pen_for"] for t in T) / nt
    v, w = _leader([(t["team"], t["pen_for"]) for t in T], "pen_for")
    card("c-orange", "Περισσότερα πέναλτι υπέρ", v, f"πέναλτι · μέσος όρος {avgp:.1f}".replace(".", ","), w, "team")
    v, w = _leader([(t["team"], t["pen_against"]) for t in T], "pen_against")
    card("c-purple", "Περισσότερα πέναλτι κατά", v, f"πέναλτι · μέσος όρος {avgp:.1f}".replace(".", ","), w, "team")
    avgr = sum(t["red_own"] for t in T) / nt
    v, w = _leader([(t["team"], t["red_own"]) for t in T], "red_own")
    card("c-wine", "Περισσότερες κόκκινες", v, f"αποβολές · μέσος όρος {avgr:.1f}".replace(".", ","), w, "team")
    if vann:
        v, w = _leader(list(vann.items()), "ann")
        card("c-blue", "Το VAR ακύρωσε τα περισσότερα γκολ", v, ("ακυρωθέν γκολ" if v == 1 else "ακυρωθέντα γκολ") + " μετά από VAR", w, "team")
    else:
        card("c-blue", "Το VAR ακύρωσε τα περισσότερα γκολ", 0, "κανένα γκολ δεν ακυρώθηκε από VAR", [], "team")
    byref = defaultdict(list)
    for m in ms:
        if m["ref"]: byref[m["ref"]].append(m)
    mn = 3 if any(len(l) >= 3 for l in byref.values()) else 1
    rs = {p: l for p, l in byref.items() if len(l) >= mn}
    cpm = [(p, round(sum(m["yel_h"] + m["yel_a"] + m["red_h"] + m["red_a"] for m in l) / len(l), 1)) for p, l in rs.items()]
    v, w = _leader(cpm, "c")
    card("c-yellow", "Ο πιο αυστηρός διαιτητής", f"{v:.1f}".replace(".", ",") if v is not None else "—", f"κάρτες ανά αγώνα · τουλάχιστον {mn} αγώνες", w, "ref")
    ppm = [(p, round(sum(m["pen_h"] + m["pen_a"] for m in l) / len(l), 2)) for p, l in rs.items()]
    v, w = _leader(ppm, "p")
    card("c-pink", "Ο διαιτητής των πέναλτι", f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",") if v is not None else "—", f"πέναλτι ανά αγώνα · τουλάχιστον {mn} αγώνες", w, "ref")
    return f'{strip}<h2 class="podh"><span>Τα ρεκόρ της σεζόν</span></h2><div class="pods">{"".join(cards)}</div>'

def home_page(s, path):
    ms = season_ms(s)
    teams = sorted({t for m in ms for t in (m["home"], m["away"])})
    T = [dict(totals(ms, t), team=t) for t in teams]
    last = rounds_of(ms)[-1] if ms else None
    nvar = sum(len(m["var_items"]) for m in ms)
    body = f"""<div class="headrow"><div><h1>Ισοζύγιο διαιτησίας Super League {s}</h1>
<p class="lead">{len(ms)} αγώνες · {nvar} επεμβάσεις VAR που άλλαξαν απόφαση{f' · έως την <a href="{rel(path, round_path(last))}">{round_label(last)}</a>' if last else ''}.</p></div>{season_switch(path, s)}</div>
{podiums(path, ms, T)}
<h2>Ισοζύγιο ανά ομάδα</h2>
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
              ("VAR υπέρ / κατά", f'{t["var_for"]} / {t["var_against"]}', ""), ("Κόκκινες υπέρ / κατά", f'{t["red_opp"]} / {t["red_own"]}', ""),
              ("Κίτρινες υπέρ / κατά", f'{t["yel_opp"]} / {t["yel"]}', ""), ("Αγώνες", t["n"], "")])
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
{team_ph(path, team)}{ann_block(path, [a for a in ANN if a["team"] == team])}
<h2>Φάσεις VAR</h2>
{var_list(path, ms, team)}
<h2>Αγώνες</h2>
{match_table(path, ms, team)}"""
    page(path, f"{team}: διαιτητές, πέναλτι, VAR · Super League {CUR}",
         f"Ισοζύγιο διαιτησίας του {team} στη Super League {CUR}: πέναλτι υπέρ και κατά, κάρτες, επεμβάσεις VAR και στατιστικά με κάθε διαιτητή.", body, "0.8")

def team_ph(path, team):
    ph = [p for p in PH if team in (p["m"]["home"], p["m"]["away"])]
    if not ph: return ""
    plus, minus = team_errors(team, ph)
    return (f'<h2>Αμφισβητούμενες φάσεις</h2><p class="lead">Κατά την πλειοψηφία των τηλεκριτικών, η ομάδα <b class="pos">ωφελήθηκε</b> από {plus} '
            f'και <b class="neg">αδικήθηκε</b> από {minus} λάθος αποφάσεις.</p>{phase_cards(path, ph)}')

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

def ref_ph(path, ref):
    ph = [x for x in PH if x["m"]["ref"] == ref]
    if not ph: return ""
    w = sum(1 for x in ph if consensus(x)[0] == "Λάθος")
    return (f'<h2>Αμφισβητούμενες φάσεις</h2><p class="lead">{len(ph)} φάσεις στους αγώνες του σχολιάστηκαν· η πλειοψηφία των τηλεκριτικών έκρινε λάθος τις {w}.</p>'
            f'{phase_cards(path, ph)}')

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
{ref_ph(path, p)}{ann_block(path, [a for a in ANN if p in (a["m"]["ref"], a["m"]["var"])], title="Ανακοινώσεις ομάδων για τους αγώνες του")}
<h2>Φάσεις VAR στους αγώνες του</h2>{var_list(path, lst)}
<h2>Αγώνες</h2>{match_table(path, lst)}""")
    if asvar:
        tr = "".join(f'<tr><td><a href="{rel(path, round_path(m))}">{m["round"]}</a></td><td class="l">{esc(m["home"])} – {esc(m["away"])}</td>'
                     f'<td class="l">{ref_link(path, m["ref"])}</td><td>{len(m["var_items"])}</td></tr>' for m in reversed(asvar))
        blocks.append(f'<h2>Ως VAR</h2><div class="tablewrap"><table class="t"><tr><th>Αγ.</th><th class="l">Αγώνας</th><th class="l">Διαιτητής</th><th>Επεμβάσεις</th></tr>{tr}</table></div>')
    page(path, f"{p}: διαιτητής Super League, στατιστικά · refstats.gr",
         f"Ο διαιτητής {p} στη Super League: αγώνες, πέναλτι και κάρτες ανά αγώνα, επεμβάσεις VAR και ισοζύγιο κάθε ομάδας μαζί του.", body="\n".join(blocks), priority="0.7")

def other(m, t): return m["away"] if t == m["home"] else m["home"] if t == m["away"] else ""

def match_chips(m):
    """Short labelled chips: what the refereeing produced in this match, per team."""
    chips = []
    vpen = defaultdict(int); vred = defaultdict(int); vann = defaultdict(int)
    for v in m["var_items"]:
        t, b = v["type"], v["ben"]
        o = other(m, b)
        if t == "Δόθηκε πέναλτι":
            chips.append(("c-green", f"VAR: πέναλτι · {b}")); vpen[b] += 1
        elif t == "Ακυρώθηκε πέναλτι":
            chips.append(("c-teal", f"VAR: ακυρώθηκε πέναλτι · {o}"))
        elif t == "Δόθηκε κόκκινη":
            chips.append(("c-wine", f"VAR: κόκκινη · {o}")); vred[o] += 1
        elif t == "Ακυρώθηκε κόκκινη":
            chips.append(("c-wine2", f"VAR: ακυρώθηκε κόκκινη · {b}"))
        elif t == "Ακυρώθηκε γκολ":
            chips.append(("c-purple", f"VAR: ακυρώθηκε γκολ · {o}")); vann[o] += 1
        elif t == "Κατοχυρώθηκε γκολ":
            chips.append(("c-blue", f"VAR: κατοχυρώθηκε γκολ · {b}"))
        else:
            chips.append(("c-grey", f"VAR: {t}"))
    for side_, team in (("h", m["home"]), ("a", m["away"])):
        n = m["pen_" + side_] - vpen[team]
        if n > 0: chips.append(("c-orange", f"Πέναλτι{' ×' + str(n) if n > 1 else ''} · {team}"))
    for side_, team in (("h", m["home"]), ("a", m["away"])):
        n = m["red_" + side_] - vred[team]
        if n > 0: chips.append(("c-red", f"Κόκκινη{' ×' + str(n) if n > 1 else ''} · {team}"))
    for side_, team in (("h", m["home"]), ("a", m["away"])):
        n = m["ann_" + side_] - vann[team]
        if n > 0: chips.append(("c-lilac", ("Ακυρωθέν γκολ" if n == 1 else f"Ακυρωθέντα γκολ ×{n}") + f" · {team}"))
    return chips

def match_card(here, m, detail=False):
    chips = match_chips(m)
    ch = "".join(f'<i class="mc {c}">{esc(t)}</i>' for c, t in chips)
    y = m["yel_h"] + m["yel_a"]
    v = ""
    if detail:
        v = "".join(f'<div class="vx"><b>{esc(x["min"])}\'</b> {esc(x["type"])} · υπέρ {esc(x["ben"] or "—")}<span>{esc(x["desc"])}</span></div>' for x in m["var_items"])
    return (f'<article class="m{" busy" if len(chips) >= 3 else ""}"><div class="sc"><span class="h">{team_link(here, m["home"])}</span><b>{m["gh"]}–{m["ga"]}</b><span class="a">{team_link(here, m["away"])}</span></div>'
            f'<div class="ref">{fdate(m["date"])} · Διαιτητής: {ref_link(here, m["ref"])} · VAR: {ref_link(here, m["var"])} · {y} κίτριν{"η" if y == 1 else "ες"}</div>'
            + (f'<div class="chips2">{ch}</div>' if ch else '') + f'{v}</article>')

def round_page(s, first):
    ms = [m for m in MATCHES if m["season"] == s and m["phase"] == first["phase"] and m["round"] == first["round"]]
    path = round_path(first)
    allr = rounds_of(season_ms(s)); i = [round_path(x) for x in allr].index(path)
    prev = f'<a href="{rel(path, round_path(allr[i-1]))}">← {round_label(allr[i-1])}</a>' if i > 0 else "<span></span>"
    nxt = f'<a href="{rel(path, round_path(allr[i+1]))}">{round_label(allr[i+1])} →</a>' if i < len(allr) - 1 else "<span></span>"
    cards = [match_card(path, m, detail=True) for m in ms]
    body = f"""<p class="crumb"><a href="{rel(path, "agonistiki/")}">Αγωνιστικές</a> / {s} / {round_label(first)}</p>
<h1>Η διαιτησία της {round_gen(first)} · Super League {s}</h1>
<p class="lead">Τι άφησε η διαιτησία σε κάθε αγώνα: πέναλτι, κόκκινες, ακυρωθέντα γκολ και επεμβάσεις VAR.</p>
<div class="matches">{"".join(cards)}</div>
<p class="note">Οι ετικέτες «VAR:» είναι αποφάσεις που άλλαξαν μετά από επέμβαση του VAR· οι υπόλοιπες δόθηκαν από τον διαιτητή στο γήπεδο. Είναι νούμερα, όχι κατηγορίες.</p>
{round_ph(path, ms)}{ann_block(path, [a for a in ANN if a["m"]["id"] in {m["id"] for m in ms}])}
<div class="pager">{prev}{nxt}</div>"""
    page(path, f"Διαιτησία {round_gen(first)} Super League {s} · refstats.gr",
         f"Οι διαιτητές της {round_gen(first)} της Super League {s}, τα πέναλτι, οι κάρτες και οι επεμβάσεις VAR αγώνα προς αγώνα.", body, "0.6")

def round_ph(path, ms):
    ids = {m["id"] for m in ms}
    ph = [p for p in PH if p["m"]["id"] in ids]
    if not ph: return ""
    return f'<h2>Αμφισβητούμενες φάσεις: τι είπαν οι τηλεκριτικοί</h2>{phase_cards(path, ph, newest_first=False)}'

def rounds_index():
    path = "agonistiki/"
    latest = ""
    if CUR and season_ms(CUR):
        last = rounds_of(season_ms(CUR))[-1]
        ms = [m for m in MATCHES if m["season"] == CUR and m["phase"] == last["phase"] and m["round"] == last["round"]]
        latest = (f'<div class="headrow"><div><h2 style="margin-top:6px">Τελευταία αγωνιστική: {last["round"]}η{"" if last["phase"] == "Κανονική" else " (" + last["phase"] + ")"}</h2>'
                  f'<p class="lead">Super League {CUR} · τι άφησε η διαιτησία, αγώνα προς αγώνα. <a href="{rel(path, round_path(last))}">Λεπτομέρειες και φάσεις VAR →</a></p></div></div>'
                  f'<div class="matches two">{"".join(match_card(path, m) for m in ms)}</div>'
                  '<p class="note">Οι ετικέτες «VAR:» είναι αποφάσεις που άλλαξαν μετά από επέμβαση του VAR. Είναι νούμερα, όχι κατηγορίες.</p>')
    parts = []
    for s_ in SEASONS:
        links = "".join(f'<a href="{rel(path, round_path(m))}">{m["round"]}{"" if m["phase"] == "Κανονική" else " " + esc(m["phase"])}</a>' for m in rounds_of(season_ms(s_)))
        parts.append(f'<h2>Σεζόν {s_}</h2><div class="roundlinks">{links}</div>')
    page(path, "Αγωνιστικές Super League: διαιτητές και VAR · refstats.gr",
         "Η τελευταία αγωνιστική της Super League και όλες οι προηγούμενες, με τους διαιτητές, τα πέναλτι, τις κόκκινες και τις επεμβάσεις VAR κάθε αγώνα.",
         "<h1>Αγωνιστικές</h1>" + latest + '<h2 style="margin-top:34px">Όλες οι αγωνιστικές</h2>' + "".join(parts).replace("<h2>", "<h3>").replace("</h2>", "</h3>"), "0.7")

VSYM = {"Σωστή": ("✓", "ok"), "Λάθος": ("✗", "bad"), "Οριακή": ("≈", "mid")}
def ph_anchor(p): return "f-" + slugify(p["code"])
def ph_where(here, p):
    m = p["m"]; rp = round_path(m)
    label = f'{esc(m["home"])}–{esc(m["away"])} {esc(p["min"])}\''
    return f'<a href="{rel(here, rp)}#{ph_anchor(p)}">{label}</a>' if rp in ROUNDPATHS else label
def cons_cell(p):
    c, ok, bad = consensus(p)
    if not c: return '<td class="cons nil">—</td>'
    k = {"Σωστή": "ok", "Λάθος": "bad"}.get(c, "mid")
    return f'<td class="cons {k}"><b>{c}</b> <span>({ok}–{bad})</span></td>' if c != "Ισοψηφία" else f'<td class="cons mid"><b>Ισοψηφία</b> <span>({ok}–{bad})</span></td>'
def side_of(p, o):
    pr = protester(p)
    if o["v"] == "Οριακή": return "≈ οριακή", "mid"
    if o["v"] == "Σωστή": return "Διαιτητής", "ref"
    return (short(pr), "tm") if pr else ("Λάθος", "tm")
def phase_card(here, p):
    pr = protester(p)
    c, ok, bad = consensus(p)
    tele = [(n, o) for n, o in p["ops"].items() if is_tele(n)]
    jour = [(n, o) for n, o in p["ops"].items() if not is_tele(n)]
    order = {x["name"]: i for i, x in enumerate(CRITICS)}
    chips = "".join(f'<a class="cc {side_of(p, o)[1]}{"" if is_tele(n) else " j"}" href="{rel(here, "tilekritiki/" + CRIT[n]["slug"] + "/")}"><span>{esc(n)}</span><b>{esc(side_of(p, o)[0])}</b></a>'
                    for n, o in sorted(tele, key=lambda x: order.get(x[0], 99)) + sorted(jour, key=lambda x: order.get(x[0], 99)))
    if c:
        tot = ok + bad
        k = {"Σωστή": "ok", "Λάθος": "bad"}.get(c, "mid")
        word = {"Σωστή": "Σωστή απόφαση", "Λάθος": "Λάθος απόφαση", "Ισοψηφία": "Ισοψηφία"}[c]
        bar = (f'<div class="pc-v"><div class="vb" role="img" aria-label="{bad} με {esc(pr or "την ομάδα")}, {ok} με τον διαιτητή">'
               f'<i class="t" style="width:{100 * bad / tot:.0f}%"></i><i class="r" style="width:{100 * ok / tot:.0f}%"></i></div>'
               f'<span><b>{bad}</b> με {esc(short(pr) if pr else "την ομάδα")} · <b>{ok}</b> με τον διαιτητή</span><em class="{k}">{word}</em></div>')
    else:
        bar = '<div class="pc-v"><span>Δεν έχουν τοποθετηθεί τηλεκριτικοί</span></div>'
    items = []
    for cr in CRITICS:
        o = p["ops"].get(cr["name"])
        if not o: continue
        lab, k = side_of(p, o)
        src = f' <a href="{esc(o["src"])}" rel="nofollow noopener" target="_blank">πηγή</a>' if o["src"].startswith("http") else ""
        should = f' Έπρεπε: {esc(o["should"])}.' if o["should"] and o["v"] != "Σωστή" else ""
        items.append(f'<li><b>{esc(cr["name"])}</b>{" <small>δημοσιογράφος</small>" if not is_tele(cr["name"]) else ""} <span class="cc {k} mini"><b>{esc(lab)}</b></span>'
                     f'{"<br>" + esc(o["why"]) if o["why"] else ""}{should}{src}</li>')
    vid = f'<p class="note"><a href="{esc(p["video"])}" rel="nofollow noopener" target="_blank">Δες τη φάση</a></p>' if p["video"].startswith("http") else ""
    desc = f'<p class="pc-x">{esc(p["desc"])}</p>' if p["desc"] else ""
    return (f'<article class="pc" id="{ph_anchor(p)}"><div class="pc-h"><b>{esc(p["min"])}\'</b> {esc(p["cat"])}{" <span class=\"pill\">VAR</span>" if p["var"] else ""}</div>'
            f'<div class="pc-d">Διαμαρτυρήθηκε: <b>{esc(pr or "—")}</b><br>Απόφαση: {esc(p["dec"])}</div>'
            f'{bar}<div class="pc-c">{chips}</div>'
            f'<details><summary>Τι είπε ο καθένας</summary>{desc}<ul class="ops">{"".join(items)}</ul>{vid}</details></article>')
def phase_cards(here, phases, newest_first=True, head="h3", howto=True):
    groups, seen = {}, []
    for p in phases:
        mid = p["m"]["id"]
        if mid not in groups: groups[mid] = []; seen.append(mid)
        groups[mid].append(p)
    if newest_first: seen = list(reversed(seen))
    out = []
    for mid in seen:
        ps = sorted(groups[mid], key=lambda p: minute_key({"min": p["min"]}))
        m = ps[0]["m"]; bm = BYID.get(mid)
        score = f' {bm["gh"]}–{bm["ga"]}' if bm else ""
        rp = round_path(m)
        title = f'{esc(m["home"])}–{esc(m["away"])}{score}'
        if rp in ROUNDPATHS and here != rp: title = f'<a href="{rel(here, rp)}">{title}</a>'
        sub = f'{round_label(m)} · Διαιτητής: {ref_link(here, m["ref"])}' if m.get("ref") else round_label(m)
        an = [a for a in ANN if a["m"]["id"] == mid]
        anl = ('<p class="an-flag">Επίσημη ανακοίνωση: ' + ", ".join(f'<a href="{rel(here, "tilekritiki/anakoinoseis/")}">{esc(a["team"])}</a>' for a in an) + '</p>') if an else ""
        out.append(f'<section class="pm"><{head}>{title}</{head}><p class="note">{sub}</p>{anl}<div class="pcs">{"".join(phase_card(here, p) for p in ps)}</div></section>')
    return "".join(out) + (HOWTO if howto else "")
HOWTO = ('<details class="howto"><summary>Πώς διαβάζεται</summary><p>Σε κάθε φάση φαίνεται ποια ομάδα διαμαρτυρήθηκε και τι αποφάσισε ο διαιτητής. '
         'Κάθε σχολιαστής πηγαίνει είτε με τον <b>διαιτητή</b> (έκρινε την απόφαση σωστή) είτε με την <b>ομάδα</b> που διαμαρτυρήθηκε (την έκρινε λάθος). '
         'Η μπάρα και το συμπέρασμα μετρούν μόνο τους τηλεκριτικούς. Οι δημοσιογράφοι φαίνονται με πιο αχνό χρώμα και δεν μετρούν.</p></details>')
def phase_table(here, phases):
    cols = [c for c in CRITICS if any(c["name"] in p["ops"] for p in phases)]
    tele = [c for c in cols if c["kind"] != "Δημοσιογράφος"]; jour = [c for c in cols if c["kind"] == "Δημοσιογράφος"]
    g = (f'<tr class="grp"><th colspan="4"></th>' + (f'<th colspan="{len(tele)}">Τηλεκριτικοί</th>' if tele else "")
         + (f'<th colspan="{len(jour)}" class="j">Δημοσιογράφοι</th>' if jour else "") + '</tr>')
    hh = ('<tr><th class="l">Φάση</th><th class="l">Διαμαρτυρήθηκε</th><th class="l">Απόφαση</th><th>Κατά τους τηλεκριτικούς</th>' + "".join(f'<th class="cn"><a href="{rel(here, "tilekritiki/" + c["slug"] + "/")}">{esc(c["name"])}</a></th>' for c in tele)
          + "".join(f'<th class="cn j"><a href="{rel(here, "tilekritiki/" + c["slug"] + "/")}">{esc(c["name"])}</a></th>' for c in jour) + '</tr>')
    rws = []
    for p in phases:
        cells = []
        for c in tele + jour:
            o = p["ops"].get(c["name"]); j = " j" if c["kind"] == "Δημοσιογράφος" else ""
            if o:
                pr = protester(p)
                if o["v"] == "Οριακή": lab, k = "≈", "mid"
                elif o["v"] == "Σωστή" or not pr: lab, k = ("Διαιτητής", "ref") if o["v"] == "Σωστή" else ("✗", "bad")
                else: lab, k = short(pr), "tm"
                tip = o["v"] + (f' · έπρεπε: {o["should"]}' if o["should"] else "") + (f' · {o["why"]}' if o["why"] else "")
                cells.append(f'<td class="v {k}{j}" title="{esc(tip)}">{esc(lab)}</td>')
            else:
                cells.append(f'<td class="v nil{j}">·</td>')
        dec = esc(p["dec"]) + (' <span class="pill">VAR</span>' if p["var"] else "")
        rws.append(f'<tr><td class="l">{ph_where(here, p)}<span class="sub">{esc(p["cat"])}</span></td><td class="l"><b>{esc(protester(p) or "—")}</b></td><td class="l">{dec}</td>{cons_cell(p)}{"".join(cells)}</tr>')
    return (f'<div class="tablewrap"><table class="t ph">{g}{hh}{"".join(rws)}</table></div>'
            '<p class="note">Σε κάθε κελί, με ποιον πήγε ο σχολιαστής: «Διαιτητής» αν έκρινε την απόφαση σωστή, η ομάδα που διαμαρτυρήθηκε αν την έκρινε λάθος. ≈ οριακή · · δεν τοποθετήθηκε. Η στήλη «Κατά τους τηλεκριτικούς» είναι η πλειοψηφία μόνο των τηλεκριτικών (σωστή–λάθος). Πέρασε τον δείκτη πάνω από ένα κελί για την αιτιολογία.</p>')
def phase_details(here, phases):
    out = []
    for p in phases:
        m = p["m"]
        items = []
        for c in CRITICS:
            o = p["ops"].get(c["name"])
            if not o: continue
            sym, k = VSYM[o["v"]]
            src = f' · <a href="{esc(o["src"])}" rel="nofollow noopener" target="_blank">πηγή</a>' if o["src"].startswith("http") else ""
            items.append(f'<li><span class="vs {k}">{sym} {o["v"]}</span> <a href="{rel(here, "tilekritiki/" + c["slug"] + "/")}"><b>{esc(c["name"])}</b></a>'
                         f'{" (" + esc(c["kind"].lower()) + ")" if c["kind"] == "Δημοσιογράφος" else ""}{": " + esc(o["why"]) if o["why"] else ""}'
                         f'{" Έπρεπε: " + esc(o["should"]) + "." if o["should"] and o["v"] != "Σωστή" else ""}{src}</li>')
        vid = f' · <a href="{esc(p["video"])}" rel="nofollow noopener" target="_blank">βίντεο</a>' if p["video"].startswith("http") else ""
        out.append(f'<div class="phx" id="{ph_anchor(p)}"><h3>{esc(m["home"])}–{esc(m["away"])} {esc(p["min"])}\': {esc(p["cat"])}</h3>'
                   f'<p class="note">Απόφαση: {esc(p["dec"])}{" (μετά από VAR)" if p["var"] else ""}{" · ωφελήθηκε: " + esc(p["ben"]) if p["ben"] else ""}{vid}</p>'
                   f'{"<p>" + esc(p["desc"]) + "</p>" if p["desc"] else ""}<ul class="ops">{"".join(items)}</ul></div>')
    return "".join(out)
def team_errors(team, phases):
    plus = minus = 0
    for p in phases:
        c, _, _ = consensus(p)
        if c == "Λάθος" and p["ben"]:
            if p["ben"] == team: plus += 1
            elif team in (p["m"]["home"], p["m"]["away"]): minus += 1
    return plus, minus
def _pct(x): return f"{round(100 * x)}%"
def _diff(a, b):
    if a is None or b is None: return None
    return round(100 * (a - b))
def _dcell(d):
    if d is None: return '<td>—</td>'
    k = "up" if d >= 10 else "dn" if d <= -10 else ""
    return f'<td class="dd {k}"><b>{"+" if d > 0 else "−" if d < 0 else ""}{abs(d)}</b></td>'
def lean_table(cname, mode):
    rws = []
    for t in lean_teams():
        n, mine, oth = lean(cname, t, mode)
        if not n: continue
        if n < MIN_N:
            rws.append((n, f'<tr><td class="l">{esc(t)}</td><td>{n}</td><td colspan="3" class="few">λίγα δεδομένα ακόμα</td></tr>'))
        else:
            rws.append((n + 1000, f'<tr><td class="l">{esc(t)}</td><td>{n}</td><td>{_pct(mine)}</td><td>{_pct(oth) if oth is not None else "—"}</td>{_dcell(_diff(mine, oth))}</tr>'))
    if not rws: return '<p class="note">Δεν υπάρχουν ακόμα φάσεις.</p>'
    col = "Δίκιο στην ομάδα" if mode == "prot" else "Σωστός ο διαιτητής"
    first = "Όταν διαμαρτύρεται" if mode == "prot" else "Όταν διαμαρτύρεται ο αντίπαλός της"
    return (f'<div class="tablewrap"><table class="t lean"><tr><th class="l">{first}</th><th>Φάσεις</th><th>{col}</th><th>Οι άλλοι τηλεκριτικοί</th><th>Διαφορά</th></tr>'
            + "".join(r for _, r in sorted(rws, key=lambda x: x[0] < 1000)) + '</table></div>')
def lean_map(here):
    teams = [t for t in lean_teams() if any(lean(c["name"], t, "all")[0] >= MIN_N for c in CRITICS)]
    if not teams:
        return (f'<h2>Με ποιον πάει κάθε σχολιαστής</h2><div class="empty">Ο χάρτης εμφανίζεται όταν ένας σχολιαστής έχει κρίνει τουλάχιστον {MIN_N} φάσεις '
                f'μιας ομάδας, από {MIN_M} διαφορετικούς αγώνες. Μέχρι τότε δεν βγάζουμε συμπέρασμα.</div>')
    hh = '<tr><th class="l">Σχολιαστής</th>' + "".join(f'<th title="{esc(t)}">{esc(short(t))}</th>' for t in teams) + '</tr>'
    tr = ""
    for c in CRITICS:
        cells = ""
        for t in teams:
            n, mine, oth = lean(c["name"], t, "all")
            d = _diff(mine, oth) if n >= MIN_N else None
            if d is None:
                cells += f'<td class="hm nil" title="{esc(t)}: {n} φάσεις">·</td>'
            else:
                a = min(abs(d), 40) / 40 * 55 + 8
                col = "var(--card)" if d > 0 else "#3B6FB6"
                cells += (f'<td class="hm" style="background:color-mix(in srgb,{col} {a:.0f}%,transparent)" '
                          f'title="{esc(t)}: {n} φάσεις · {_pct(mine)} υπέρ, οι άλλοι {_pct(oth)}">{"+" if d > 0 else "−" if d < 0 else ""}{abs(d)}</td>')
        tr += f'<tr><td class="l"><a href="{rel(here, "tilekritiki/" + c["slug"] + "/")}">{esc(c["name"])}</a></td>{cells}</tr>'
    return (f'<h2>Με ποιον πάει κάθε σχολιαστής</h2><p class="lead">Σε όλες τις φάσεις μιας ομάδας, πόσο πιο συχνά από τους άλλους τηλεκριτικούς ο σχολιαστής κρίνει υπέρ της, '
            f'είτε δίνοντάς της δίκιο όταν διαμαρτύρεται είτε βγάζοντας σωστό τον διαιτητή όταν διαμαρτύρεται ο αντίπαλος. Σε ποσοστιαίες μονάδες, στις ίδιες ακριβώς φάσεις.</p>'
            f'<div class="tablewrap"><table class="t hmap">{hh}{tr}</table></div>'
            f'<p class="note">Θετικό (κίτρινο): κρίνει υπέρ της ομάδας συχνότερα από τους άλλους. Αρνητικό (μπλε): σπανιότερα. · σημαίνει ότι δεν υπάρχουν ακόμα αρκετά δεδομένα. Πέρασε τον δείκτη πάνω από ένα κελί για τα νούμερα.</p>')
def critic_page(c):
    path = f'tilekritiki/{c["slug"]}/'
    mine = [p for p in PH if c["name"] in p["ops"]]
    n = len(mine); cnt = {k: sum(1 for p in mine if p["ops"][c["name"]]["v"] == k) for k in VSYM}
    agree = [p for p in mine if consensus(p)[0] in ("Σωστή", "Λάθος") and p["ops"][c["name"]]["v"] in ("Σωστή", "Λάθος")]
    ag = sum(1 for p in agree if p["ops"][c["name"]]["v"] == consensus(p)[0])
    pc = lambda x: f"{round(100 * x / n)}%" if n else "—"
    k = kpis([("Φάσεις", n, ""), ("Σωστή απόφαση", pc(cnt["Σωστή"]), ""), ("Λάθος απόφαση", pc(cnt["Λάθος"]), ""), ("Οριακή", pc(cnt["Οριακή"]), ""),
              ("Συμφωνία με πλειοψηφία", f"{round(100 * ag / len(agree))}%" if agree else "—", "")])
    body = f"""<p class="crumb"><a href="{rel(path, "tilekritiki/")}">Τηλεκριτική</a> / {esc(c["name"])}</p>
<h1>{esc(c["name"])}: τι λέει για τη διαιτησία</h1>
<p class="lead">{esc(c["kind"])}{" · " + esc(c["outlet"]) if c["outlet"] else ""}. Οι τοποθετήσεις του για τις αμφισβητούμενες φάσεις της Super League, με πηγή για καθεμία.</p>
{k}
<h2>Με ποιον πάει</h2>
<p class="lead">Πόσο συχνά ο {esc(c["name"])} κρίνει υπέρ κάθε ομάδας, σε σύγκριση με τους άλλους τηλεκριτικούς στις ίδιες ακριβώς φάσεις. Μετράνε μόνο οι φάσεις όπου είπε σωστή ή λάθος απόφαση.</p>
<h3>Όταν διαμαρτύρεται η ομάδα</h3>
{lean_table(c["name"], "prot")}
<h3>Όταν διαμαρτύρεται ο αντίπαλός της</h3>
{lean_table(c["name"], "opp")}
<p class="note">Διαφορά: ποσοστιαίες μονάδες πάνω ή κάτω από τους άλλους τηλεκριτικούς. Ποσοστό δείχνουμε από {MIN_N} φάσεις σε τουλάχιστον {MIN_M} αγώνες.</p>
<h2>Φάσεις</h2>
{phase_details(path, list(reversed(mine)))}"""
    page(path, f'{c["name"]}: ανάλυση διαιτησίας Super League · refstats.gr',
         f'Οι αναλύσεις του {c["name"]} για τις αμφισβητούμενες φάσεις της Super League: πότε συμφώνησε και πότε διαφώνησε με τον διαιτητή.', body, "0.6")
def ann_result(a):
    bm = BYID.get(a["m"]["id"])
    if not bm: return ""
    mine, opp = (bm["gh"], bm["ga"]) if a["team"] == bm["home"] else (bm["ga"], bm["gh"])
    return "Νίκη" if mine > opp else "Ήττα" if mine < opp else "Ισοπαλία"
def ann_item(here, a, show_match=True):
    m = a["m"]; bm = BYID.get(m["id"]); rp = round_path(m)
    title = f'{esc(m["home"])}–{esc(m["away"])}' + (f' {bm["gh"]}–{bm["ga"]}' if bm else "")
    if rp in ROUNDPATHS: title = f'<a href="{rel(here, rp)}">{title}</a>'
    who = " · ".join(x for x in [f'Διαιτητής: {ref_link(here, m["ref"])}' if m.get("ref") else "", f'VAR: {ref_link(here, m["var"])}' if m.get("var") else ""] if x)
    link = f' <a href="{esc(a["link"])}" rel="nofollow noopener" target="_blank">Η ανακοίνωση</a>' if a["link"].startswith("http") else ""
    res = ann_result(a)
    head = f'<b>{team_link(here, a["team"])}</b>' + (f' <span class="res r-{slugify(res)}">{res}</span>' if res else "")
    match = f'<div class="an-m">{title} · {round_label(m)}{" · " + who if who else ""}</div>' if show_match else ""
    return f'<article class="an"><div class="an-h">{head}<time>{fdate(a["date"])}</time></div>{match}<p>{esc(a["text"])}{link}</p></article>'
def ann_block(here, anns, h="h2", title="Επίσημες ανακοινώσεις για τη διαιτησία", show_match=True):
    if not anns: return ""
    return f'<{h}>{title}</{h}><div class="ans">{"".join(ann_item(here, a, show_match) for a in anns)}</div>'
def ann_page():
    path = "tilekritiki/anakoinoseis/"
    cnt = {}
    for a in ANN:
        c = cnt.setdefault(a["team"], {"n": 0, "Ήττα": 0, "Ισοπαλία": 0, "Νίκη": 0}); c["n"] += 1
        if ann_result(a): c[ann_result(a)] += 1
    tr = "".join(f'<tr><td class="l">{team_link(path, t)}</td><td>{c["n"]}</td><td>{c["Ήττα"]}</td><td>{c["Ισοπαλία"]}</td><td>{c["Νίκη"]}</td></tr>'
                 for t, c in sorted(cnt.items(), key=lambda x: (-x[1]["n"], x[0])))
    body = f"""<h1>Τηλεκριτική: ανακοινώσεις ομάδων</h1>
<p class="lead">Οι επίσημες ανακοινώσεις των ομάδων για τη διαιτησία μετά από αγώνες της Super League, με περίληψη και link στο πρωτότυπο.</p>
{tk_tabs(path, path)}
<div class="tablewrap"><table class="t"><tr><th class="l">Ομάδα</th><th>Σύνολο</th><th>Μετά από ήττα</th><th>ισοπαλία</th><th>νίκη</th></tr>{tr}</table></div>
<h2>Όλες οι ανακοινώσεις</h2><div class="ans">{"".join(ann_item(path, a) for a in ANN)}</div>
<p class="note">Οι περιλήψεις είναι δικές μας και αποδίδουν τις θέσεις των ομάδων χωρίς να τις υιοθετούμε.</p>"""
    page(path, "Ανακοινώσεις ομάδων για τη διαιτησία στη Super League · refstats.gr",
         "Όλες οι επίσημες ανακοινώσεις των ομάδων της Super League για τη διαιτησία μετά από αγώνες: ποια ομάδα, για ποιον αγώνα και διαιτητή, με link στο πρωτότυπο.", body, "0.7")
def tk_tabs(here, cur):
    t = [("tilekritiki/", "Φάσεις"), ("tilekritiki/sxoliastes/", "Σχολιαστές")] + ([("tilekritiki/anakoinoseis/", "Ανακοινώσεις")] if ANN else [])
    return '<nav class="subtabs">' + "".join(f'<a href="{rel(here, p)}"{" aria-current=\"page\"" if p == cur else ""}>{l}</a>' for p, l in t) + '</nav>'
def critic_stats(c):
    mine = [p for p in PH if c["name"] in p["ops"]]
    n = len(mine)
    ref = sum(1 for p in mine if p["ops"][c["name"]]["v"] == "Σωστή")
    agree = [p for p in mine if consensus(p)[0] in ("Σωστή", "Λάθος") and p["ops"][c["name"]]["v"] in ("Σωστή", "Λάθος")]
    ag = sum(1 for p in agree if p["ops"][c["name"]]["v"] == consensus(p)[0])
    return n, (f"{round(100 * ref / n)}%" if n else "—"), (f"{round(100 * ag / len(agree))}%" if agree else "—")
def tilekritiki_index():
    path = "tilekritiki/"
    cur = [p for p in PH if p["m"]["season"] == CUR] or PH
    wrong = sum(1 for p in cur if consensus(p)[0] == "Λάθος")
    groups = {}
    for p in cur:
        groups.setdefault((PHASE_ORDER.get(p["m"]["phase"], 9), p["m"]["round"], p["m"]["phase"]), []).append(p)
    secs = "".join(f'<h2>{round_label(v[0]["m"]).capitalize()}</h2>{phase_cards(path, v, howto=False)}' for k, v in sorted(groups.items(), reverse=True))
    body = f"""<h1>Τηλεκριτική</h1>
<p class="lead">Τι είπαν οι τηλεκριτικοί για τις αμφισβητούμενες φάσεις: {len(cur)} φάσ{"η" if len(cur) == 1 else "εις"}, {wrong} λάθος απόφασ{"η" if wrong == 1 else "εις"} κατά την πλειοψηφία τους.</p>
{tk_tabs(path, path)}
<p class="scope">Καταγράφουμε μόνο φάσεις που αμφισβητήθηκαν πραγματικά. Οι ξεκάθαρες αποφάσεις δεν μπαίνουν, ακόμα κι αν τις σχολίασαν οι τηλεκριτικοί. <a href="{rel(path, "methodologia/")}#tilekritiki">Πώς επιλέγουμε</a></p>
{HOWTO}
{secs}"""
    page(path, f"Τηλεκριτική Super League {CUR}: Βαρούχας, Κουτσιαύτης και άλλοι για τις φάσεις · refstats.gr",
         f"Οι αμφισβητούμενες φάσεις κάθε αγωνιστικής της Super League και τι είπαν οι τηλεκριτικοί διαιτησίας: σωστή ή λάθος απόφαση και γιατί.", body, "0.8")
    path = "tilekritiki/sxoliastes/"
    def rows(kind):
        tr = ""
        for c in [c for c in CRITICS if (c["kind"] != "Δημοσιογράφος") == (kind == "t")]:
            n, ref, ag = critic_stats(c)
            tr += f'<tr><td class="l"><a href="{rel(path, "tilekritiki/" + c["slug"] + "/")}">{esc(c["name"])}</a><span class="sub">{esc(c["outlet"])}</span></td><td>{n}</td><td>{ref}</td><td>{ag}</td></tr>'
        return tr
    hdr = '<tr><th class="l">{}</th><th>Φάσεις</th><th>Με τον διαιτητή</th><th>Με την πλειοψηφία</th></tr>'
    t, j = rows("t"), rows("j")
    tables = (f'<div class="tablewrap"><table class="t crit">{hdr.format("Τηλεκριτικοί")}{t}</table></div>' if t else "") + \
             (f'<div class="tablewrap"><table class="t crit j">{hdr.format("Δημοσιογράφοι")}{j}</table></div>' if j else "")
    body = f"""<h1>Τηλεκριτική: οι σχολιαστές</h1>
<p class="lead">Πόσο συχνά κάθε σχολιαστής δίνει δίκιο στον διαιτητή και πόσο συμφωνεί με την πλειοψηφία των τηλεκριτικών.</p>
{tk_tabs(path, path)}
{tables}
<p class="note">«Με τον διαιτητή»: ποσοστό φάσεων που έκρινε την απόφαση σωστή. «Με την πλειοψηφία»: πόσο συχνά η κρίση του (σωστή/λάθος) συμπίπτει με την πλειοψηφία των τηλεκριτικών.</p>
{lean_map(path)}"""
    page(path, "Τηλεκριτικοί διαιτησίας Super League: ποιος συμφωνεί με ποιον · refstats.gr",
         "Οι τηλεκριτικοί και οι δημοσιογράφοι που σχολιάζουν τη διαιτησία της Super League: πόσο συχνά δικαιώνουν τον διαιτητή και πώς κρίνουν τις φάσεις κάθε ομάδας.", body, "0.7")

def static_pages():
    page("methodologia/", "Μεθοδολογία · refstats.gr", "Πώς καταγράφει το refstats.gr τα στατιστικά διαιτησίας: τι μετράει ως πέναλτι, φάση VAR και ισοζύγιο διαιτησίας.", f"""<div class="prose">
<h1>Πώς μετράμε</h1>
<p>Καταγράφουμε αποφάσεις, όχι κρίσεις. Δεν λέμε αν ένα πέναλτι ήταν σωστό. Μετράμε ότι δόθηκε.</p>
<h2>Ισοζύγιο διαιτησίας</h2>
<p><code>(πέναλτι υπέρ + VAR υπέρ + κόκκινες υπέρ) − (πέναλτι κατά + VAR κατά + κόκκινες κατά)</code></p>
<p>Κόκκινες υπέρ είναι οι αποβολές παικτών του αντιπάλου και κόκκινες κατά οι αποβολές παικτών της ομάδας.</p>
<p>Ένα πέναλτι που δόθηκε μετά από VAR μετράει και στα πέναλτι και στις φάσεις VAR.</p>
<h2>Φάσεις VAR</h2>
<p>Μετράει μόνο η επέμβαση που άλλαξε την απόφαση του διαιτητή: πέναλτι που δόθηκε ή ακυρώθηκε, κόκκινη που δόθηκε ή ακυρώθηκε, γκολ που ακυρώθηκε ή κατοχυρώθηκε. Ένας έλεγχος που επιβεβαίωσε την απόφαση του γηπέδου δεν μετράει. Κάθε επέμβαση χρεώνεται υπέρ της ομάδας που ωφελήθηκε.</p>
<h2>Κάρτες και γκολ</h2>
<ul><li>Κόκκινες: απευθείας κόκκινες και αποβολές με δεύτερη κίτρινη. Η δεύτερη κίτρινη δεν μετράει στις κίτρινες.</li>
<li>Κάρτες σε προπονητές και πάγκο δεν μετράνε.</li>
<li>Ακυρωθέντα γκολ: γκολ της ομάδας που δεν μέτρησαν, είτε από τον διαιτητή ή τον βοηθό είτε μετά από VAR.</li></ul>
<h2>Τι δεν δείχνουν τα νούμερα</h2>
<p>Ένα θετικό ισοζύγιο δεν σημαίνει εύνοια. Μια ομάδα που επιτίθεται περισσότερο κερδίζει περισσότερα πέναλτι. Γι' αυτό στις σελίδες ομάδων και διαιτητών συγκρίνουμε κάθε ομάδα με τον δικό της μέσο όρο. Συνδυασμοί διαιτητή και ομάδας με λιγότερους από 5 αγώνες σημειώνονται ως μικρό δείγμα.</p>
<h2 id="tilekritiki">Τηλεκριτική</h2>
<h3>Ανακοινώσεις ομάδων</h3>
<p>Καταγράφουμε τις επίσημες ανακοινώσεις των ομάδων για τη διαιτησία που βγαίνουν μετά από αγώνα. Μετράνε μόνο οι ανακοινώσεις της ΠΑΕ που αγωνίζεται στη Super League, από το επίσημο site ή τα επίσημα social της· ανακοινώσεις ερασιτεχνικών τμημάτων, σωματείων ή συνδέσμων φιλάθλων δεν μπαίνουν, εκτός αν τις υιοθετήσει η ΠΑΕ. Δεν καταγράφουμε επίσης non-papers, «διαρροές» ή πληροφορίες από «κύκλους» της ομάδας, ούτε δηλώσεις και αναρτήσεις προέδρων, παραγόντων, προπονητών ή παικτών. Η περίληψη είναι δική μας και αποδίδει τις θέσεις της ομάδας χωρίς να τις υιοθετούμε· το πλήρες κείμενο βρίσκεται στο link της πηγής.</p>
<h3>Ποιες φάσεις μπαίνουν</h3>
<p>Δεν καταγράφουμε κάθε φάση που σχολίασαν οι τηλεκριτικοί, μόνο όσες αμφισβητήθηκαν πραγματικά. Μια φάση μπαίνει όταν ισχύει τουλάχιστον ένα από τα παρακάτω:</p>
<ul><li>τουλάχιστον ένας τηλεκριτικός έκρινε την απόφαση λάθος ή οριακή·</li>
<li>η απόφαση έκρινε ή επηρέασε σημαντικά το αποτέλεσμα και συζητήθηκε ευρέως·</li>
<li>μια ομάδα διαμαρτυρήθηκε επίσημα για αυτήν.</li></ul>
<p>Ξεκάθαρες αποφάσεις δεν μπαίνουν, ακόμα κι αν σχολιάστηκαν: ένα πέναλτι που ζητήθηκε ενώ η μπάλα βρήκε στο στήθος, ένα πέναλτι που δόθηκε για καθαρή ανατροπή, ένα γκολ που ακυρώθηκε από το VAR για εμφανές οφσάιντ. Γι' αυτό τα ποσοστά «Με τον διαιτητή» αφορούν μόνο δύσκολες φάσεις και δεν δείχνουν πόσο καλά σφύριξε συνολικά ένας διαιτητής.</p>
<p>Για τις αμφισβητούμενες φάσεις κάθε αγωνιστικής καταγράφουμε τι είπαν δημόσια οι τηλεκριτικοί διαιτησίας και δημοσιογράφοι που σχολιάζουν τη διαιτησία. Κάθε τοποθέτηση έχει πηγή και αποδίδεται με δικά μας λόγια σε μία πρόταση. «Σωστή» σημαίνει ότι ο σχολιαστής συμφώνησε με την τελική απόφαση, «Λάθος» ότι διαφώνησε και «Οριακή» ότι τη θεώρησε αμφίβολη ή δεν πήρε ξεκάθαρη θέση.</p>
<p>Το συμπέρασμα κάθε φάσης είναι η απλή πλειοψηφία μόνο των τηλεκριτικών· οι δημοσιογράφοι εμφανίζονται χωριστά και δεν μετρούν σε αυτό. Αν ένας σχολιαστής θεωρεί ότι η θέση του αποδόθηκε λάθος, τη διορθώνουμε.</p>
<p>Ομάδα που διαμαρτυρήθηκε είναι η αντίπαλη αυτής που ωφελήθηκε από την απόφαση. Όταν ένας σχολιαστής κρίνει την απόφαση σωστή, πηγαίνει με τον διαιτητή· όταν την κρίνει λάθος, δίνει δίκιο στην ομάδα που διαμαρτυρήθηκε.</p>
<p>Στο «Με ποιον πάει» συγκρίνουμε κάθε σχολιαστή με τους υπόλοιπους τηλεκριτικούς στις ίδιες ακριβώς φάσεις, ώστε να μη μετράει το αν μια ομάδα αδικήθηκε πράγματι πολλές φορές. Οι οριακές τοποθετήσεις δεν μετρούν, και ποσοστό δείχνουμε μόνο από {MIN_N} φάσεις σε τουλάχιστον {MIN_M} διαφορετικούς αγώνες. Τα νούμερα περιγράφουν τοποθετήσεις, δεν χαρακτηρίζουν πρόσωπα.</p>
<h2>Πηγές</h2>
<p>Ορισμοί της ΚΕΔ, επίσημα φύλλα αγώνα και βίντεο των φάσεων. Κάθε αγώνας και κάθε φάση VAR στη βάση έχει πηγή. Αν βρεις λάθος, στείλε μας την πηγή και θα το διορθώσουμε.</p>
</div>""", "0.4")
    if GA4:
        priv = """<p>Το refstats.gr δεν ζητά προσωπικά στοιχεία και δεν εμφανίζει διαφημίσεις.</p>
<h2>Μέτρηση επισκεψιμότητας</h2>
<p>Χρησιμοποιούμε το Google Analytics 4 για να μετράμε πόσοι επισκέπτονται τις σελίδες και από πού έρχονται. Το Google Analytics φορτώνεται και αποθηκεύει cookies <b>μόνο αν πατήσεις «Αποδοχή»</b> στο σχετικό μήνυμα. Αν πατήσεις «Απόρριψη», δεν φορτώνεται καθόλου. Μπορείς να αλλάξεις την επιλογή σου οποτεδήποτε από τον σύνδεσμο «Ρυθμίσεις cookies» στο κάτω μέρος κάθε σελίδας.</p>
<p>Τα δεδομένα επεξεργάζεται η Google σύμφωνα με τους <a href="https://policies.google.com/privacy" rel="noopener" target="_blank">όρους απορρήτου της</a>. Η επιλογή σου αποθηκεύεται μόνο στον browser σου.</p>"""
    else:
        priv = "<p>Το refstats.gr δεν χρησιμοποιεί cookies, δεν ζητά προσωπικά στοιχεία και δεν εμφανίζει διαφημίσεις.</p>"
    page("aporrito/", "Πολιτική απορρήτου · refstats.gr", "Πολιτική απορρήτου του refstats.gr.", f"""<div class="prose">
<h1>Πολιτική απορρήτου</h1>
{priv}
<h2>Γραμματοσειρές και φιλοξενία</h2>
<p>Η σελίδα φορτώνει γραμματοσειρές από τις Google Fonts, οπότε η Google λαμβάνει τη διεύθυνση IP του επισκέπτη κατά τη φόρτωσή τους. Η φιλοξενία γίνεται στο GitHub Pages, που κρατά τεχνικά αρχεία καταγραφής για λόγους ασφαλείας.</p>
</div>""", "0.1")

# ---------------------------------------------------------------- build
if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)
shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(OUT, "assets"))
home_page(CUR, "")
for s in SEASONS[1:]:
    home_page(s, f"sezon/{s}/")
ROUNDPATHS = {round_path(m) for m in MATCHES}
for t in sorted({t for m in MATCHES for t in (m["home"], m["away"])}):
    team_page(t)
refs_index()
for p in sorted({p for m in MATCHES for p in (m["ref"], m["var"]) if p}):
    ref_page(p)
for s in SEASONS:
    for first in rounds_of(season_ms(s)):
        round_page(s, first)
rounds_index()
if TK:
    tilekritiki_index()
if ANN:
    ann_page()
if PH:
    for c in CRITICS:
        critic_page(c)
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
for w in WARN: print("ΠΡΟΣΟΧΗ: " + w)
print(f"OK: {len(MATCHES)} αγώνες, {sum(len(m['var_items']) for m in MATCHES)} φάσεις VAR, {len(PH)} αμφισβητούμενες φάσεις, {len(PAGES)} σελίδες -> {OUT}")
