#!/usr/bin/env python3
"""Sprint review progress for Team A/C.

Builds a self-contained, bilingual (EN/FA) HTML report with tabs, and an English Markdown copy:
  - Overall: progress per roadmap item, prerequisite releases, task lists,
  - Releases: open and released versions, with the Jira description,
  - one tab per sprint: estimated work done, how each item moved, and the tasks behind every number.

Configuration comes from environment variables or a .env file (see .env.example):
  JIRA_BASE_URL, JIRA_PAT (required), JIRA_PROJECT, JIRA_BOARD_ID, SPRINT_PREFIX, SPRINT_QUARTER,
  JIRA_STORY_POINTS_FIELD, JIRA_EPIC_LINK_FIELD, MAPPING_FILE, REPORT_OUT_DIR.
Items, epics and prerequisite releases come from mapping.json. Standard library only.

Usage:
  python sprint_progress.py --check
  python sprint_progress.py --open
  python sprint_progress.py --quarter 2026Q4 --include-future --lang fa --out-dir D:/reports
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- configuration
def env_candidates(explicit):
    """Where a .env file is looked for. Earlier files win; real environment variables win over all."""
    out = [explicit, os.environ.get("SPRINT_REVIEW_ENV"), os.path.join(os.getcwd(), ".env"),
           os.path.join(HERE, "..", ".env"), os.path.join(HERE, "..", "..", "..", ".env"),
           os.path.expanduser("~/.sprint-review.env")]
    return [os.path.abspath(p) for p in out if p]


def load_env(explicit=None):
    env = dict(os.environ)
    used = []
    for path in env_candidates(explicit):
        if not os.path.isfile(path) or path in used:
            continue
        used.append(path)
        for line in open(path, encoding="utf-8-sig"):
            if line.lstrip().startswith("#"):
                continue
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if not m:
                continue
            val = m.group(2)
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            elif " #" in val:
                val = val.split(" #", 1)[0].rstrip()
            env.setdefault(m.group(1), val)
    return env, used


_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--env-file")
ENV, ENV_USED = load_env(_pre.parse_known_args()[0].env_file)
BASE = (ENV.get("JIRA_BASE_URL") or "").rstrip("/")
TOKEN = ENV.get("JIRA_PAT") or ""
PROJECT = ENV.get("JIRA_PROJECT") or "TC"
SP_FIELD = ENV.get("JIRA_STORY_POINTS_FIELD") or ""  # resolved by name when empty


def require_config():
    missing = [k for k, v in (("JIRA_BASE_URL", BASE), ("JIRA_PAT", TOKEN)) if not v]
    if missing:
        sys.exit("Missing " + " and ".join(missing) + ". Copy .env.example to .env and fill it in "
                 "(or set the variables in the environment, or pass --env-file).")


# ---------------------------------------------------------------- Jira access
def get(path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        hint = {401: "the token is wrong or expired", 403: "the token cannot see this resource",
                404: "not found, check JIRA_PROJECT / JIRA_BOARD_ID"}.get(e.code, "")
        sys.exit(f"Jira answered HTTP {e.code} for {path.split('?')[0]}" + (f" — {hint}." if hint else "."))
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach {BASE}: {e.reason}")


def paged(path_fn, key):
    out, start = [], 0
    while True:
        d = get(path_fn(start))
        batch = d[key]
        out += batch
        start += len(batch)
        if not batch or d.get("isLast") or ("total" in d and start >= d["total"]):
            return out


def jql_issues(jql, fields):
    return paged(lambda s: "/rest/api/2/search?startAt=%d&maxResults=100&fields=%s&jql=%s" % (s, fields, urllib.parse.quote(jql)), "issues")


def field_id(name, override=""):
    if override:
        return override
    for f in get("/rest/api/2/field"):
        if f["name"] == name:
            return f["id"]
    sys.exit(f'Jira has no field named "{name}". Set its id in .env.')


def epic_link_field():
    return field_id("Epic Link", ENV.get("JIRA_EPIC_LINK_FIELD", ""))


# ------------------------------------------------------------------- helpers
def parse(ts):
    if not ts:
        return None
    return datetime.strptime(ts.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z")


def bucket(issue):
    c = issue["fields"]["status"]["statusCategory"]["key"]
    return "done" if c == "done" else "doing" if c == "indeterminate" else "todo"


def epic_of(issue, elf):
    f = issue["fields"]
    return (f.get("epic") or {}).get("key") or f.get(elf)


def match_item(issue, epic, items):
    versions = {v["name"] for v in issue["fields"].get("fixVersions", [])}
    for idx, it in enumerate(items):
        for s in it["sources"]:
            if s["epic"] == epic and (not s.get("fixVersions") or versions & set(s["fixVersions"])):
                return idx
    return None


def total(c):
    return c["done"] + c["doing"] + c["todo"]


def pct(d, t):
    return round(100 * d / t) if t else 0


def counts_of(tasks):
    c = {"done": 0, "doing": 0, "todo": 0}
    for t in tasks:
        c[t["bucket"]] += 1
    return c


def epics_label(it):
    parts = [s["epic"] + (" [" + "/".join(s["fixVersions"]) + "]" if s.get("fixVersions") else "") for s in it["sources"]]
    return ", ".join(dict.fromkeys(parts))


# ---------------------------------------------------------------- collection
def load_mapping():
    path = ENV.get("MAPPING_FILE") or os.path.join(HERE, "..", "mapping.json")
    cfg = json.load(open(path, encoding="utf-8"))
    cfg["board_id"] = int(ENV.get("JIRA_BOARD_ID") or cfg["board_id"])
    cfg["sprint_prefix"] = ENV.get("SPRINT_PREFIX") or cfg["sprint_prefix"]
    return cfg, os.path.abspath(path)


def collect(a):
    global SP_FIELD
    cfg, _ = load_mapping()
    SP_FIELD = field_id("Story Points", SP_FIELD)
    items = cfg["items"]
    elf = epic_link_field()
    epics = sorted({s["epic"] for it in items for s in it["sources"]})
    now = datetime.now(timezone.utc)

    sprints = paged(lambda s: f"/rest/agile/1.0/board/{cfg['board_id']}/sprint?startAt={s}&maxResults=50", "values")
    wanted = {"closed", "active"} | ({"future"} if a.include_future else set())
    sprints = [s for s in sprints if s["name"].startswith(cfg["sprint_prefix"]) and a.quarter in s["name"] and s["state"] in wanted]
    sprints.sort(key=lambda s: s["name"])

    fields = f"status,issuetype,fixVersions,summary,resolutiondate,assignee,{SP_FIELD},{elf},epic"
    epic_names = {}

    def epic_name(key):
        if key == "no epic":
            return ""
        if key not in epic_names:
            try:
                epic_names[key] = get(f"/rest/api/2/issue/{key}?fields=summary")["fields"]["summary"]
            except Exception:
                epic_names[key] = ""
        return epic_names[key]

    def keep(i):
        t = i["fields"]["issuetype"]
        return t["name"] != "Epic" and not t.get("subtask")

    def task(i):
        f = i["fields"]
        return {"key": i["key"], "summary": f["summary"], "status": f["status"]["name"], "bucket": bucket(i),
                "assignee": (f.get("assignee") or {}).get("displayName", "—"), "sp": f.get(SP_FIELD) or 0}

    def tally(issues):
        res = defaultdict(lambda: {"done": 0, "doing": 0, "todo": 0})
        unmapped, outside, by_item = [], defaultdict(list), defaultdict(list)
        for i in issues:
            e = epic_of(i, elf)
            idx = match_item(i, e, items)
            if idx is None:
                (unmapped if e in epics else outside[e or "no epic"]).append(task(i))
                continue
            res[idx][bucket(i)] += 1
            by_item[idx].append(task(i))
        return res, unmapped, dict(outside), by_item

    overall = [i for i in jql_issues('"Epic Link" in (%s)' % ",".join(epics), fields) if keep(i)]
    res, unmapped, _, ov_tasks = tally(overall)

    # releases: the ones we track, any other open version, and every released version
    vers = {v["name"]: v for v in get(f"/rest/api/2/project/{PROJECT}/versions")}
    rel_names = list(dict.fromkeys(cfg["release_overview"] + [r for it in items for r in it.get("prerequisite_releases", [])]))
    rel_names += [n for n, v in vers.items() if n not in rel_names]
    rel = {}
    for name in rel_names:
        c = {"done": 0, "doing": 0, "todo": 0}
        for i in jql_issues('project = %s AND fixVersion = "%s"' % (PROJECT, name), "status,issuetype"):
            if keep(i):
                c[bucket(i)] += 1
        rel[name] = c

    out_items = []
    for idx, it in enumerate(items):
        out_items.append({
            "n": idx + 1, "title": it["title"], "title_fa": it.get("title_fa", it["title"]),
            "group": it["group"], "group_fa": it.get("group_fa", it["group"]), "team": it.get("team", ""),
            "epics": epics_label(it) or "no epic", "counts": res.get(idx),
            "prereqs": [{"name": r, "counts": rel[r]} for r in it.get("prerequisite_releases", [])], "tasks": ov_tasks.get(idx, []),
            "notes": it.get("prerequisites", ""), "notes_fa": it.get("prerequisites_fa", it.get("prerequisites", "")),
        })

    out_sprints = []
    for sp in sprints:
        iss = [i for i in paged(lambda s: f"/rest/agile/1.0/sprint/{sp['id']}/issue?startAt={s}&maxResults=100&fields={fields}", "issues") if keep(i)]
        start, end = parse(sp.get("startDate")), parse(sp.get("endDate"))
        end_eff = min(end, now) if end else now
        sres, sunm, soff, s_tasks = tally(iss)
        sp_tot = sum(i["fields"].get(SP_FIELD) or 0 for i in iss)
        sp_done = sum(i["fields"].get(SP_FIELD) or 0 for i in iss if bucket(i) == "done")
        rows = []
        for idx, it in enumerate(items):
            if idx not in sres:
                continue
            t = d0 = d1 = 0
            for i in overall:
                if match_item(i, epic_of(i, elf), items) != idx:
                    continue
                t += 1
                rd = parse(i["fields"].get("resolutiondate")) if bucket(i) == "done" else None
                if rd:
                    d0 += rd < start
                    d1 += rd <= end_eff
            rows.append({"n": idx + 1, "title": it["title"], "title_fa": it.get("title_fa", it["title"]), "counts": sres[idx],
                         "from": pct(d0, t), "to": pct(d1, t), "d0": d0, "d1": d1, "t": t, "tasks": s_tasks.get(idx, [])})
        out_sprints.append({
            "name": sp["name"], "state": sp["state"], "start": start, "end": end,
            "sp_done": sp_done, "sp_total": sp_tot, "est_n": sum(1 for i in iss if i["fields"].get(SP_FIELD)),
            "tasks": len(iss), "tasks_done": sum(1 for i in iss if bucket(i) == "done"),
            "rows": rows, "unmatched": sunm,
            "outside": [{"epic": k, "name": epic_name(k), "tasks": v} for k, v in sorted(soff.items())],
        })

    return {
        "generated": datetime.now().astimezone(), "quarter": a.quarter, "prefix": cfg["sprint_prefix"], "items": out_items, "unmapped": unmapped, "sprints": out_sprints,
        "releases": [{"name": n, "counts": rel[n], "desc": (vers.get(n) or {}).get("description", ""),
                      "released": (vers.get(n) or {}).get("released", False), "date": (vers.get(n) or {}).get("releaseDate", "")} for n in rel_names],
    }


# ------------------------------------------------------------------- Markdown
def md_bar(c, n=12):
    t = total(c)
    if not t:
        return "░" * n
    d = round(n * c["done"] / t)
    p = min(n - d, round(n * c["doing"] / t))
    return "▓" * d + "▒" * p + "░" * (n - d - p)


def md_cell(c):
    if not c or not total(c):
        return "—"
    return f"{md_bar(c)} {pct(c['done'], total(c))}% ({c['done']}✓ {c['doing']}⏳ {c['todo']}○ / {total(c)})"


def render_md(D):
    L = []
    w = L.append
    keys = lambda ts: ", ".join(t["key"] for t in ts)
    w("# Sprint review progress — Team A/C")
    w("")
    w(f"Generated {D['generated']:%Y-%m-%d %H:%M} · quarter {D['quarter']} · ✓ done, ⏳ in progress, ○ not started · counted in tasks (epics and sub-tasks excluded).")
    w("")
    w("## 1) Overall result per roadmap item")
    w("")
    w("| # | Roadmap item | Epics | Prerequisite releases | Done | Overall progress |")
    w("|---|---|---|---|---|---|")
    for it in D["items"]:
        c = it["counts"]
        pre = "<br>".join(f"{p['name']}: {pct(p['counts']['done'], total(p['counts']))}%" for p in it["prereqs"]) or "—"
        w(f"| {it['n']} | {it['title']} | {it['epics']} | {pre} | {str(pct(c['done'], total(c))) + '%' if c and total(c) else '—'} | {md_cell(c)} |")
    notes = [it for it in D["items"] if it["notes"]]
    if notes:
        w("")
        w("Notes on prerequisites:")
        for it in notes:
            w(f"- #{it['n']}: {it['notes']}")
    if D["unmapped"]:
        w("")
        w(f"Tasks in roadmap epics whose fix version matches no item ({len(D['unmapped'])}): " + keys(D["unmapped"]))
    for title, flag in (("2) Open releases", False), ("3) Released", True)):
        w("")
        w(f"## {title}")
        w("")
        w("| Release | Done | Progress |")
        w("|---|---|---|")
        for r in D["releases"]:
            if r["released"] == flag:
                t = total(r["counts"])
                w(f"| {r['name']} | {str(pct(r['counts']['done'], t)) + '%' if t else '—'} | {md_cell(r['counts'])} |")
    w("")
    w("## 4) Sprints — where we started and where we got")
    for s in D["sprints"]:
        w("")
        w(f"### {s['name']} ({s['state']}, {s['start']:%Y-%m-%d} → {s['end']:%Y-%m-%d})")
        w("")
        w(f"- Estimated work done: **{pct(s['sp_done'], s['sp_total'])}%** ({s['sp_done']:g} of {s['sp_total']:g} Story Points; {s['est_n']} of {s['tasks']} tasks have an estimate)")
        w(f"- Tasks done: **{pct(s['tasks_done'], s['tasks'])}%** ({s['tasks_done']} of {s['tasks']})")
        w("")
        w("| # | Roadmap item | In this sprint | Item start → end |")
        w("|---|---|---|---|")
        for r in s["rows"]:
            w(f"| {r['n']} | {r['title']} | {md_cell(r['counts'])} | {r['from']}% → {r['to']}% ({r['d0']} → {r['d1']} of {r['t']}) |")
        if s["unmatched"]:
            w("")
            w(f"- In a roadmap epic but no matching fix version ({len(s['unmatched'])}): " + keys(s["unmatched"]))
        if s["outside"]:
            w("- Outside the roadmap table: " + "; ".join(f"{o['epic']}: {keys(o['tasks'])}" for o in s["outside"]))
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------- HTML
CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--mute:#667085;--line:#e4e7ec;--done:#2f9e6e;--doing:#e0a526;--todo:#d5dae1;--accent:#3466d6;--chip:#eef2f8;--done-bg:#e3f4ec;--doing-bg:#fbf0d4;--todo-bg:#eceff3}
@media (prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1a2029;--ink:#e6e9ee;--mute:#98a2b3;--line:#2a323d;--done:#3fbf8a;--doing:#e8b84a;--todo:#38414d;--accent:#7ba3ff;--chip:#232b36;--done-bg:#173528;--doing-bg:#3a3014;--todo-bg:#272e38}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,"Segoe UI",Tahoma,Roboto,Helvetica,Arial,sans-serif}
html[lang=en] .fa,html[lang=fa] .en{display:none}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:0 0 6px}h3{font-size:15px;margin:18px 0 6px}
.sub{color:var(--mute);font-size:13px}
.lang{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;flex:none}
.lang button{appearance:none;border:0;background:var(--card);color:var(--mute);font:inherit;font-weight:700;font-size:12px;padding:6px 12px;cursor:pointer}
.lang button[aria-pressed=true]{background:var(--accent);color:#fff}
.tabs{position:sticky;top:0;z-index:5;display:flex;gap:4px;overflow-x:auto;background:var(--bg);padding:12px 0 0;margin-top:14px;border-bottom:1px solid var(--line)}
.tab{appearance:none;border:0;background:none;color:var(--mute);font:inherit;font-weight:600;padding:9px 14px;border-radius:8px 8px 0 0;cursor:pointer;white-space:nowrap;border-bottom:3px solid transparent}
.tab:hover{color:var(--ink)}.tab[aria-selected=true]{color:var(--accent);border-bottom-color:var(--accent)}
.tab:focus-visible,.ico:focus-visible,.lang button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.tab small{font-weight:500;color:var(--mute);margin-inline-start:6px}
.panel{display:none;padding-top:18px}.panel.on{display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:14px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.kpi b{display:block;font-size:26px;line-height:1.1}.kpi span{color:var(--mute);font-size:12px}
table{width:100%;border-collapse:collapse}th,td{text-align:start;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-size:12px;font-weight:600;letter-spacing:.03em}.en th,th .en{text-transform:uppercase}
tr:last-child>td{border-bottom:0}.tw{overflow-x:auto}
.bar{display:flex;height:9px;border-radius:5px;overflow:hidden;background:var(--todo);min-width:110px}
.bar i{display:block;height:100%}.bar .d{background:var(--done)}.bar .p{background:var(--doing)}
.pc{font-weight:600}.mute{color:var(--mute)}.small{font-size:12px}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;margin-inline-end:4px;margin-bottom:4px;font-size:12px;white-space:nowrap}
.grp td{background:var(--chip);color:var(--mute);font-size:12px;font-weight:600}
.arrow{white-space:nowrap}.up{color:var(--done);font-weight:600}
.badge{font-size:11px;border-radius:999px;padding:2px 9px;margin-inline-start:8px;font-weight:600;vertical-align:middle}
.b-active,.b-released{background:var(--accent);color:#fff}.b-closed{background:var(--todo);color:var(--ink)}.b-future,.b-unreleased{background:var(--chip);color:var(--mute)}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 0}.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-inline-end:5px;vertical-align:-1px}
details{margin-top:10px}summary{cursor:pointer;color:var(--mute);font-size:13px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.nowrap{white-space:nowrap}.ltr{direction:ltr;unicode-bidi:isolate;display:inline-block}
.ico{appearance:none;border:1px solid var(--line);background:var(--card);color:var(--mute);border-radius:6px;width:26px;height:26px;padding:0;margin-inline-start:8px;cursor:pointer;vertical-align:middle;display:inline-flex;align-items:center;justify-content:center}
.ico:hover,.ico[aria-expanded=true]{color:var(--accent);border-color:var(--accent)}
.ico svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
tr.more>td{background:var(--bg);padding:12px 14px}tr.more[hidden]{display:none}
.desc{white-space:pre-wrap;max-width:860px}
table.tl th,table.tl td{padding:6px 8px;font-size:13px}table.tl{background:var(--card);border:1px solid var(--line);border-radius:8px}
.st{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:600;white-space:nowrap}
.st-done{background:var(--done-bg);color:var(--done)}.st-doing{background:var(--doing-bg);color:var(--doing)}.st-todo{background:var(--todo-bg);color:var(--mute)}
@media (max-width:640px){.wrap{padding:14px 12px 48px}.hide-s{display:none}}
@media print{body{background:#fff}.tabs,.ico,.lang{display:none}.panel{display:block!important;page-break-before:always}.card,.kpi{break-inside:avoid}tr.more{display:none}}
"""

JS = """
(function(){
  var root=document.documentElement,tabs=[].slice.call(document.querySelectorAll('.tab')),panels=[].slice.call(document.querySelectorAll('.panel')),langBtns=[].slice.call(document.querySelectorAll('.lang button'));
  function labels(){[].slice.call(document.querySelectorAll('[data-en]')).forEach(function(b){var t=b.getAttribute('data-'+root.lang);b.title=t;b.setAttribute('aria-label',t);});}
  function setLang(l,save){
    root.lang=l;root.dir=l==='fa'?'rtl':'ltr';
    langBtns.forEach(function(b){b.setAttribute('aria-pressed',b.dataset.lang===l);});
    document.title=l==='fa'?'\\u06af\\u0632\\u0627\\u0631\\u0634 \\u067e\\u06cc\\u0634\\u0631\\u0641\\u062a \\u0627\\u0633\\u067e\\u0631\\u06cc\\u0646\\u062a \\u2014 Team A/C':'Sprint review \\u2014 Team A/C';
    labels();
    if(save){try{localStorage.setItem('sr-lang',l);}catch(e){}}
  }
  function show(id,push){
    if(!document.getElementById('tab-'+id)){id=tabs[0].dataset.tab;}
    tabs.forEach(function(t){t.setAttribute('aria-selected',t.dataset.tab===id);t.tabIndex=t.dataset.tab===id?0:-1;});
    panels.forEach(function(p){p.classList.toggle('on',p.id==='tab-'+id);});
    if(push){try{history.replaceState(null,'','#'+id);}catch(e){}}
  }
  langBtns.forEach(function(b){b.addEventListener('click',function(){setLang(b.dataset.lang,true);});});
  tabs.forEach(function(t,i){
    t.addEventListener('click',function(){show(t.dataset.tab,true);});
    t.addEventListener('keydown',function(ev){
      var j=ev.key==='ArrowRight'?i+1:ev.key==='ArrowLeft'?i-1:null;
      if(j===null)return;ev.preventDefault();var n=tabs[(j+tabs.length)%tabs.length];n.focus();show(n.dataset.tab,true);
    });
  });
  document.addEventListener('click',function(ev){
    var b=ev.target.closest('.ico');if(!b)return;
    var row=document.getElementById(b.dataset.toggle);if(!row)return;
    var open=row.hidden;row.hidden=!open;b.setAttribute('aria-expanded',open);
  });
  var saved=null;try{saved=localStorage.getItem('sr-lang');}catch(e){}
  setLang(saved==='fa'||saved==='en'?saved:(root.dataset.default||'en'),false);
  show((location.hash||'').slice(1)||tabs[0].dataset.tab,false);
})();
"""

ICON_INFO = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5h.01"/></svg>'
ICON_LIST = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/></svg>'
STATE_FA = {"active": "فعال", "closed": "بسته‌شده", "future": "آینده"}


def e(s):
    return html.escape(str(s))


def bi(en, fa=None):
    """Both languages, the stylesheet shows one. Text is escaped here."""
    return f'<span class="en">{e(en)}</span><span class="fa">{e(fa if fa is not None else en)}</span>'


def bi_raw(en, fa):
    return f'<span class="en">{en}</span><span class="fa">{fa}</span>'


def issue_link(k):
    return f'<a href="{e(BASE)}/browse/{e(k)}">{e(k)}</a>'


def h_bar(c):
    t = total(c) if c else 0
    if not t:
        return '<span class="mute">—</span>'
    d, p = 100 * c["done"] / t, 100 * c["doing"] / t
    en = f'{c["done"]} done · {c["doing"]} in progress · {c["todo"]} to do · {t} tasks'
    fa = f'{c["done"]} انجام‌شده · {c["doing"]} در حال انجام · {c["todo"]} شروع‌نشده · {t} تسک'
    return (f'<div class="bar"><i class="d" style="width:{d:.1f}%"></i><i class="p" style="width:{p:.1f}%"></i></div>'
            f'<div class="small"><span class="pc">{pct(c["done"], t)}%</span> <span class="mute">· {bi(en, fa)}</span></div>')


def h_pre(p):
    return f'<span class="chip">{e(p["name"])} · {pct(p["counts"]["done"], total(p["counts"]))}%</span>'


def icon_btn(target, en, fa, svg):
    return (f'<button type="button" class="ico" data-toggle="{e(target)}" data-en="{e(en)}" data-fa="{e(fa)}" '
            f'aria-expanded="false" aria-label="{e(en)}" title="{e(en)}">{svg}</button>')


def task_rows(tasks, ncols, rid):
    if not tasks:
        return f'<tr class="more" hidden id="{e(rid)}"><td colspan="{ncols}"><span class="mute">{bi("No tasks.", "تسکی نیست.")}</span></td></tr>'
    order = {"doing": 0, "todo": 1, "done": 2}
    rows = "".join(
        f'<tr><td class="nowrap">{issue_link(t["key"])}</td><td>{e(t["summary"])}</td><td><span class="st st-{t["bucket"]}">{e(t["status"])}</span></td>'
        f'<td class="hide-s">{e(t["assignee"])}</td><td class="nowrap">{("%g" % t["sp"]) if t["sp"] else "—"}</td></tr>'
        for t in sorted(tasks, key=lambda t: (order[t["bucket"]], t["key"])))
    head = (f'<th>{bi("Task", "تسک")}</th><th>{bi("Summary", "عنوان")}</th><th>{bi("Status", "وضعیت")}</th>'
            f'<th class="hide-s">{bi("Assignee", "مسئول")}</th><th>{bi("SP", "امتیاز")}</th>')
    return (f'<tr class="more" hidden id="{e(rid)}"><td colspan="{ncols}"><div class="tw"><table class="tl"><thead><tr>{head}</tr></thead>'
            f'<tbody>{rows}</tbody></table></div></td></tr>')


def list_btn(rid):
    return icon_btn(rid, "Show tasks", "نمایش تسک‌ها", ICON_LIST)


def other_table(sections, first_head, idp):
    """Rows of (label_html, tasks) with a progress bar and a task list behind a button."""
    out = [f'<div class="card tw"><table><thead><tr><th>{first_head}</th><th style="min-width:230px">{bi("Progress", "پیشرفت")}</th></tr></thead><tbody>']
    for n, (label, tasks) in enumerate(sections):
        rid = f"{idp}-{n}"
        out.append(f'<tr><td>{label}{list_btn(rid)}</td><td>{h_bar(counts_of(tasks))}</td></tr>{task_rows(tasks, 2, rid)}')
    out.append('</tbody></table></div>')
    return "".join(out)


def render_html(D, default_lang):
    sprints = D["sprints"]
    active = next((s for s in sprints if s["state"] == "active"), sprints[-1] if sprints else None)
    items = D["items"]
    with_epic = [i for i in items if i["counts"] and total(i["counts"])]
    t_all = sum(total(i["counts"]) for i in with_epic)
    d_all = sum(i["counts"]["done"] for i in with_epic)
    short = lambda n: re.sub(r"^" + re.escape(D["prefix"]) + r"\s*\d{4}", "", n) or n

    P = []
    w = P.append
    w(f'<!doctype html><html lang="{default_lang}" dir="{"rtl" if default_lang == "fa" else "ltr"}" data-default="{default_lang}"><head><meta charset="utf-8">'
      f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sprint review — Team A/C</title><style>{CSS}</style></head><body><div class="wrap">')
    gen = f"{D['generated']:%Y-%m-%d %H:%M}"
    q = D["quarter"]
    w('<div class="top"><div>'
      f'<h1>{bi("Sprint review progress — Team A/C", "گزارش پیشرفت اسپرینت — Team A/C")}</h1>'
      f'<div class="sub">{bi(f"Quarter {q} · generated {gen} · counted in tasks (epics and sub-tasks excluded)", f"فصل {q} · تولید‌شده در {gen} · شمارش بر اساس تعداد تسک (اپیک و ساب‌تسک حذف شده)")}</div></div>'
      '<div class="lang" role="group" aria-label="Language"><button type="button" data-lang="en" aria-pressed="true">EN</button><button type="button" data-lang="fa" aria-pressed="false">FA</button></div></div>')
    w('<div class="legend small">'
      f'<span><i style="background:var(--done)"></i>{bi("Done", "انجام‌شده")}</span>'
      f'<span><i style="background:var(--doing)"></i>{bi("In progress / QA", "در حال انجام (شامل QA)")}</span>'
      f'<span><i style="background:var(--todo)"></i>{bi("Not started", "شروع‌نشده")}</span></div>')

    w('<div class="tabs" role="tablist">')
    w(f'<button type="button" class="tab" role="tab" data-tab="overall">{bi("Overall", "کلی")}</button>')
    w(f'<button type="button" class="tab" role="tab" data-tab="releases">{bi("Releases", "ریلیزها")}</button>')
    for n, s in enumerate(sprints):
        w(f'<button type="button" class="tab" role="tab" data-tab="s{n + 1}">{bi("Sprint " + short(s["name"]), "اسپرینت " + short(s["name"]))}'
          f'<small>{bi(s["state"], STATE_FA.get(s["state"], s["state"]))}</small></button>')
    w('</div>')

    # ---- Overall
    w(f'<section class="panel" id="tab-overall" role="tabpanel"><h2>{bi("Overall result per roadmap item", "نتیجه کلی هر آیتم نقشه‌راه")}</h2>')
    w('<div class="cards">')
    if active:
        an, spd, spt, td, nt = active["name"], active["sp_done"], active["sp_total"], active["tasks_done"], active["tasks"]
        w(f'<div class="kpi"><b>{pct(spd, spt)}%</b><span>'
          f'{bi(f"Estimated work done in {an} ({spd:g} of {spt:g} SP)", f"کار تخمین‌زده‌شدهٔ انجام‌شده در {an} ({spd:g} از {spt:g} امتیاز)")}</span></div>')
        w(f'<div class="kpi"><b>{pct(td, nt)}%</b><span>'
          f'{bi(f"Tasks done in {an} ({td} of {nt})", f"تسک‌های انجام‌شده در {an} ({td} از {nt})")}</span></div>')
    w(f'<div class="kpi"><b>{pct(d_all, t_all)}%</b><span>{bi(f"Overall, all roadmap items with an epic ({d_all} of {t_all} tasks)", f"پیشرفت کلی آیتم‌هایی که اپیک دارند ({d_all} از {t_all} تسک)")}</span></div>')
    w(f'<div class="kpi"><b>{len(with_epic)} / {len(items)}</b><span>{bi("Roadmap items that have tasks in Jira", "آیتم‌های نقشه‌راه که در Jira تسک دارند")}</span></div></div>')
    w(f'<div class="card tw"><table><thead><tr><th>#</th><th>{bi("Roadmap item", "آیتم نقشه‌راه")}</th><th>{bi("Prerequisite releases", "ریلیزهای پیش‌نیاز")}</th>'
      f'<th style="min-width:230px">{bi("Overall progress", "پیشرفت کلی")}</th></tr></thead><tbody>')
    last = None
    for it in items:
        if it["group"] != last:
            last = it["group"]
            w(f'<tr class="grp"><td colspan="4">{bi(it["group"], it["group_fa"])}</td></tr>')
        pre = "".join(h_pre(p) for p in it["prereqs"]) or '<span class="mute">—</span>'
        note = (f'<details><summary>{bi("Notes", "یادداشت‌ها")}</summary><div class="small mute">{bi(it["notes"], it["notes_fa"])}</div></details>') if it["notes"] else ""
        sub = f'<div class="small mute"><span class="ltr">{e(it["epics"])}</span>{(" · " + e(it["team"])) if it["team"] else ""}</div>{note}'
        if it["counts"] and total(it["counts"]):
            prog = h_bar(it["counts"])
        else:
            prog = f'<span class="mute small">{bi("No epic linked", "اپیکی وصل نیست") if it["epics"] == "no epic" else bi("No tasks yet", "هنوز تسکی نیست")}</span>'
        rid = f'ov-{it["n"]}'
        btn = list_btn(rid) if it["tasks"] else ""
        more = task_rows(it["tasks"], 4, rid) if it["tasks"] else ""
        w(f'<tr><td class="nowrap">{it["n"]}</td><td>{bi(it["title"], it["title_fa"])}{btn}{sub}</td><td>{pre}</td><td>{prog}</td></tr>{more}')
    w('</tbody></table></div>')
    if D["unmapped"]:
        w(other_table([(bi("In a roadmap epic but no matching fix version", "در اپیک نقشه‌راه ولی بدون نسخهٔ ریلیز مطابق"), D["unmapped"])],
                      bi("Other work", "سایر کارها"), "ovx"))
    w('</section>')

    # ---- Releases
    w(f'<section class="panel" id="tab-releases" role="tabpanel"><h2>{bi("Release progress", "پیشرفت ریلیزها")}</h2>'
      f'<div class="sub">{bi("Use the i button to read the release description from Jira.", "برای دیدن توضیحات ریلیز در Jira روی دکمهٔ i بزنید.")}</div>')
    for heading, flag in ((bi("Open and upcoming releases", "ریلیزهای باز و پیش‌رو"), False), (bi("Released", "ریلیزهای انجام‌شده"), True)):
        group = [(n, r) for n, r in enumerate(D["releases"]) if r["released"] == flag]
        if not group:
            continue
        w(f'<h3>{heading}</h3><div class="card tw"><table><thead><tr><th>{bi("Release", "ریلیز")}</th><th style="min-width:230px">{bi("Progress", "پیشرفت")}</th></tr></thead><tbody>')
        for n, r in group:
            rid = f"rel-{n}"
            badge = f'<span class="badge b-{"released" if r["released"] else "unreleased"}">{bi("Released", "ریلیز‌شده") if r["released"] else bi("Unreleased", "ریلیز‌نشده")}</span>'
            w(f'<tr><td class="nowrap">{e(r["name"])}{icon_btn(rid, "Show Jira description", "نمایش توضیحات Jira", ICON_INFO)}{badge}</td><td>{h_bar(r["counts"])}</td></tr>')
            date = f'<div class="small mute">{bi("Release date", "تاریخ ریلیز")}: {e(r["date"])}</div>' if r["date"] else ""
            desc = e(r["desc"]) if r["desc"] else f'<span class="mute">{bi("No description in Jira.", "توضیحاتی در Jira ثبت نشده است.")}</span>'
            w(f'<tr class="more" hidden id="{rid}"><td colspan="2"><div class="desc">{desc}</div>{date}</td></tr>')
        w('</tbody></table></div>')
    w('</section>')

    # ---- Sprints
    for n, s in enumerate(sprints):
        w(f'<section class="panel" id="tab-s{n + 1}" role="tabpanel"><h2>{e(s["name"])}<span class="badge b-{e(s["state"])}">{bi(s["state"], STATE_FA.get(s["state"], s["state"]))}</span> '
          f'<span class="sub">{s["start"]:%d %b} → {s["end"]:%d %b %Y}</span></h2>')
        w(f'<div class="sub">{bi("Estimated work = Story Points. Scope is read now, so tasks added or removed during the sprint are included. “Item start → end” is the overall done % of the item’s epics at sprint start and at sprint end (or now, for an active sprint). Use the list button to see the tasks behind a row.", "کار تخمین‌زده‌شده = Story Point. دامنهٔ اسپرینت همین حالا خوانده می‌شود، پس تسک‌هایی که حین اسپرینت اضافه یا حذف شده‌اند هم حساب می‌شوند. «شروع → پایان آیتم» درصد انجام‌شدهٔ کلی اپیک‌های آیتم در شروع و پایان اسپرینت است (برای اسپرینت فعال تا همین حالا). با دکمهٔ فهرست، تسک‌های پشت هر ردیف را ببینید.")}</div>')
        spd, spt, est, nt, td = s["sp_done"], s["sp_total"], s["est_n"], s["tasks"], s["tasks_done"]
        w('<div class="cards">')
        w(f'<div class="kpi"><b>{pct(spd, spt)}%</b><span>'
          f'{bi(f"Estimated work done ({spd:g} of {spt:g} SP; {est} of {nt} tasks estimated)", f"کار تخمین‌زده‌شدهٔ انجام‌شده ({spd:g} از {spt:g} امتیاز؛ {est} از {nt} تسک تخمین دارند)")}</span></div>')
        w(f'<div class="kpi"><b>{pct(td, nt)}%</b><span>{bi(f"Tasks done ({td} of {nt})", f"تسک‌های انجام‌شده ({td} از {nt})")}</span></div></div>')
        w(f'<div class="card tw"><table><thead><tr><th>#</th><th>{bi("Roadmap item", "آیتم نقشه‌راه")}</th><th style="min-width:230px">{bi("In this sprint", "در این اسپرینت")}</th>'
          f'<th>{bi("Item start → end", "شروع → پایان آیتم")}</th></tr></thead><tbody>')
        for r in s["rows"]:
            gain = r["to"] - r["from"]
            change = bi(f"+{gain} pt", f"+{gain} واحد") if gain > 0 else bi("no change", "بدون تغییر")
            d0, d1, tt = r["d0"], r["d1"], r["t"]
            cls = "up" if gain > 0 else "mute"
            move = (f'<span class="arrow ltr">{r["from"]}% → <b>{r["to"]}%</b></span> <span class="{cls}">{change}</span>'
                    f'<div class="small mute">{bi(f"{d0} → {d1} of {tt} tasks", f"{d0} → {d1} از {tt} تسک")}</div>')
            rid = f's{n + 1}-{r["n"]}'
            w(f'<tr><td>{r["n"]}</td><td>{bi(r["title"], r["title_fa"])}{list_btn(rid)}</td><td>{h_bar(r["counts"])}</td><td>{move}</td></tr>{task_rows(r["tasks"], 4, rid)}')
        w('</tbody></table></div>')
        sections = []
        if s["unmatched"]:
            sections.append((bi("In a roadmap epic but no matching fix version", "در اپیک نقشه‌راه ولی بدون نسخهٔ ریلیز مطابق"), s["unmatched"]))
        for o in s["outside"]:
            name = f' — {e(o["name"])}' if o["name"] else ""
            if o["epic"] == "no epic":
                label = bi_raw("Outside the roadmap table · No epic", "خارج از جدول نقشه‌راه · بدون اپیک")
            else:
                key = f'<span class="ltr">{e(o["epic"])}</span>{name}'
                label = bi_raw("Outside the roadmap table · " + key, "خارج از جدول نقشه‌راه · " + key)
            sections.append((label, o["tasks"]))
        if sections:
            w(f'<h3>{bi("Other work in this sprint", "سایر کارهای این اسپرینت")}</h3>')
            w(other_table(sections, bi("Group", "گروه"), f"s{n + 1}x"))
        w('</section>')
    w(f'</div><script>{JS}</script></body></html>')
    return "".join(P)


# ---------------------------------------------------------------------- main
def check():
    """Print what the script will use, so a wrong .env is obvious before a long run."""
    me = get("/rest/api/2/myself")
    cfg, mapping = load_mapping()
    proj = get(f"/rest/api/2/project/{PROJECT}")
    board = get(f"/rest/agile/1.0/board/{cfg['board_id']}")
    print(f"Jira        {BASE}")
    print(f"Signed in   {me.get('displayName')} ({me.get('name') or me.get('emailAddress')})")
    print(f"Env files   {', '.join(ENV_USED) or 'none (using environment variables)'}")
    print(f"Project     {PROJECT} — {proj['name']}")
    print(f"Board       {cfg['board_id']} — {board['name']} ({board['type']})")
    print(f"Sprints     name starts with '{cfg['sprint_prefix']}'")
    print(f"Story Pts   {field_id('Story Points', SP_FIELD)}")
    print(f"Epic Link   {epic_link_field()}")
    print(f"Mapping     {mapping} ({len(cfg['items'])} items)")
    print("OK")


def main():
    ap = argparse.ArgumentParser(description="Team A/C sprint review progress report")
    now = datetime.now()
    ap.add_argument("--env-file", help="path to a .env file (default: ./.env, the repo root, or ~/.sprint-review.env)")
    ap.add_argument("--check", action="store_true", help="test the connection and the configuration, then exit")
    ap.add_argument("--quarter", default=ENV.get("SPRINT_QUARTER") or f"{now.year}Q{(now.month - 1) // 3 + 1}",
                    help="sprint name must contain this (default: SPRINT_QUARTER or the current quarter)")
    ap.add_argument("--include-future", action="store_true", help="also report future sprints")
    ap.add_argument("--format", choices=("both", "html", "md"), default="both")
    ap.add_argument("--lang", choices=("en", "fa"), default="en", help="language the HTML report opens in (the EN/FA button switches it)")
    ap.add_argument("--out-dir", default=os.path.expanduser(ENV.get("REPORT_OUT_DIR") or "~/sprint-review"), help="where the report files are written")
    ap.add_argument("--open", action="store_true", help="open the HTML report in the default browser")
    a = ap.parse_args()
    require_config()
    if a.check:
        return check()

    D = collect(a)
    os.makedirs(a.out_dir, exist_ok=True)
    stem = os.path.join(a.out_dir, f"sprint-review-{a.quarter}-{D['generated']:%Y-%m-%d}")
    written = []
    if a.format in ("both", "html"):
        open(stem + ".html", "w", encoding="utf-8").write(render_html(D, a.lang))
        written.append(stem + ".html")
    if a.format in ("both", "md"):
        open(stem + ".md", "w", encoding="utf-8").write(render_md(D))
        written.append(stem + ".md")

    print(f"Sprint review — Team A/C · {a.quarter} · {D['generated']:%Y-%m-%d %H:%M}\n")
    print(f"{'#':>2}  {'Done':>5}  {'Tasks':>7}  Roadmap item")
    for it in D["items"]:
        c = it["counts"]
        if c and total(c):
            print(f"{it['n']:>2}  {pct(c['done'], total(c)):>4}%  {c['done']:>3}/{total(c):<3}  {it['title'][:78]}")
        else:
            print(f"{it['n']:>2}  {'—':>5}  {'':>7}  {it['title'][:78]}")
    for s in D["sprints"]:
        print(f"\n{s['name']} ({s['state']}): estimated work {pct(s['sp_done'], s['sp_total'])}% ({s['sp_done']:g}/{s['sp_total']:g} SP) · tasks {pct(s['tasks_done'], s['tasks'])}% ({s['tasks_done']}/{s['tasks']})")
    print("\nReport files:")
    for p in written:
        print("  " + p.replace("\\", "/"))
    if a.open and written and written[0].endswith(".html") and hasattr(os, "startfile"):
        os.startfile(written[0])


main()
