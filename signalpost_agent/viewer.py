"""Static, self-contained profile viewer written next to every run.

Open site/index.html in any browser (desktop or phone): search by name or number,
filter by what was found, open a company to see its sourced summary, every claim
with its source link and date, what changed, and compare companies side by side.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

KEEP = ("organisation_number", "name", "summary", "families", "claims", "evidence", "changes", "synthesis", "refresh", "run", "website_research")


def _slim(envelope: dict[str, Any]) -> dict[str, Any]:
    row = {key: envelope.get(key) for key in KEEP}
    research = row.get("website_research") or {}
    row["website_research"] = {"verdict": research.get("verdict"), "attempts": [
        {key: item.get(key) for key in ("url", "source", "verdict", "signals")} for item in research.get("attempts", [])[:6]
    ]}
    return row


def web_dataset(envelopes: list[dict[str, Any]], report: dict[str, Any]) -> dict[str, Any]:
    """Dataset consumed by the JBOX web app (public/data/profiles.json)."""
    meta = {key: report.get(key) for key in ("run_id", "completed_at", "input_count", "agent")}
    meta["requests"] = (report.get("operations") or {}).get("requests") or 0
    companies = []
    for envelope in envelopes:
        row = _slim(envelope)
        row["name"] = row.get("name") or row["organisation_number"]
        row["summary"] = row.get("summary") or (row.get("synthesis") or {}).get("summary") or ""
        row["refresh"] = {**(row.get("refresh") or {}), "mode": (row.get("refresh") or {}).get("mode", "first_observation"), "previous_snapshot": (row.get("refresh") or {}).get("previous_snapshot")}
        row["run"] = {"run_id": (row.get("run") or {}).get("run_id") or meta["run_id"], "completed_at": (row.get("run") or {}).get("completed_at") or meta["completed_at"]}
        companies.append(row)
    return {"meta": meta, "companies": companies}


def write_viewer(path: Path, envelopes: list[dict[str, Any]], report: dict[str, Any], web_data: Path | None = None) -> None:
    if web_data is not None:
        web_data.parent.mkdir(parents=True, exist_ok=True)
        web_data.write_text(json.dumps(web_dataset(envelopes, report), ensure_ascii=False), encoding="utf-8")
    data = [_slim(envelope) for envelope in envelopes]
    meta = {key: report.get(key) for key in ("run_id", "started_at", "completed_at", "input_count", "runtime_seconds", "agent")}
    meta["requests"] = (report.get("operations") or {}).get("requests")
    payload = json.dumps({"meta": meta, "companies": data}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(f"Signalpost profiles · {meta.get('run_id')}")), encoding="utf-8")
    (path.parent / "profiles.json").write_text(json.dumps({"meta": meta, "companies": data}, ensure_ascii=False), encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f5f1;--panel:#fff;--ink:#16181d;--muted:#5d6370;--line:#e3e1da;--accent:#1f5f8b;--ok:#1e7a46;--warn:#9a6a00;--bad:#a33a2a;--chip:#eef0f3;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--panel:#1b1e23;--ink:#e8e9ec;--muted:#9aa1ad;--line:#2b2f36;--accent:#7cb7e0;--ok:#5fc48c;--warn:#e0b25a;--bad:#ef8b7a;--chip:#252a31}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--accent)}header{padding:18px 20px 8px;max-width:1200px;margin:0 auto}h1{font-size:20px;margin:0}header p{margin:4px 0 0;color:var(--muted);font-size:13px}
.wrap{max-width:1200px;margin:0 auto;padding:0 16px 40px;display:grid;grid-template-columns:340px 1fr;gap:16px}
@media (max-width:860px){.wrap{grid-template-columns:1fr}.list{max-height:none!important}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px}
.controls{padding:12px;display:flex;flex-direction:column;gap:8px;border-bottom:1px solid var(--line)}
input,select{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
.list{max-height:calc(100vh - 210px);overflow:auto}.item{padding:10px 12px;border-bottom:1px solid var(--line);cursor:pointer;display:flex;gap:8px;align-items:flex-start}
.item:hover,.item.active{background:var(--chip)}.item .n{font-weight:600;font-size:14px}.item .s{color:var(--muted);font-size:12px}.item input{width:auto;margin-top:3px}
.dots{display:flex;gap:3px;margin-top:4px}.dot{width:8px;height:8px;border-radius:50%;background:var(--line)}.dot.available{background:var(--ok)}.dot.ambiguous{background:var(--warn)}.dot.failed,.dot.blocked{background:var(--bad)}
.detail{padding:18px 20px;min-width:0}.detail h2{margin:0;font-size:22px}.sub{color:var(--muted);font-size:13px}
.summary{margin:14px 0;padding:12px 14px;background:var(--chip);border-radius:8px}.cite{font-size:11px;vertical-align:super;margin-left:2px;text-decoration:none}
.fams{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}.fam{font-size:12px;padding:3px 8px;border-radius:99px;background:var(--chip);border:1px solid var(--line)}
.fam.available{border-color:var(--ok);color:var(--ok)}.fam.ambiguous{border-color:var(--warn);color:var(--warn)}.fam.failed,.fam.blocked{border-color:var(--bad);color:var(--bad)}
section{margin-top:18px}section h3{font-size:15px;margin:0 0 6px;border-bottom:1px solid var(--line);padding-bottom:4px;display:flex;justify-content:space-between;gap:8px}
section h3 small{font-weight:400;color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13.5px}td{padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}td:first-child{width:34%;color:var(--muted)}
.src{font-size:12px;white-space:nowrap}.ev{font-family:var(--mono);font-size:11px;color:var(--muted)}.empty{color:var(--muted);font-style:italic;font-size:13px}
.ev-row:target{outline:2px solid var(--accent)}.badge{font-size:11px;padding:1px 6px;border-radius:4px;background:var(--chip);color:var(--muted);margin-left:4px}
.cmp{overflow:auto}.cmp table td:first-child{width:auto;min-width:150px}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button{padding:8px 12px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink);font:inherit;cursor:pointer}button:hover{border-color:var(--accent)}
details summary{cursor:pointer;color:var(--muted);font-size:13px}
</style>
</head>
<body>
<header><h1>Signalpost company profiles</h1><p id="meta"></p></header>
<div class="wrap">
  <div class="panel">
    <div class="controls">
      <input id="q" type="search" placeholder="Search name or organisation number" aria-label="Search">
      <select id="f" aria-label="Filter">
        <option value="">All companies</option>
        <option value="official_website">Verified website</option>
        <option value="company_profiles">Social / video profiles</option>
        <option value="hiring">Hiring</option>
        <option value="annual_accounts">Filed accounts</option>
        <option value="changes">Changed since last run</option>
        <option value="ambiguous">Has ambiguous matches</option>
      </select>
      <div class="toolbar"><button id="cmpBtn" disabled>Compare selected</button><span class="sub" id="count"></span></div>
    </div>
    <div class="list" id="list" role="listbox"></div>
  </div>
  <div class="panel detail" id="detail"></div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA=JSON.parse(document.getElementById('data').textContent);const C=DATA.companies;
const FAM={legal_identity:'Legal identity',public_brand:'Public brand',annual_accounts:'Annual accounts',account_history:'Account history',leadership:'Leadership',registered_workplaces:'Workplaces',official_website:'Website',company_profiles:'Profiles',website_contact:'Contact',hiring:'Hiring',public_activity:'Activity',ratings_reviews:'Ratings'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sel=new Set();let current=null;
document.getElementById('meta').textContent=`Run ${DATA.meta.run_id} · ${DATA.meta.input_count} companies · completed ${DATA.meta.completed_at} · ${DATA.meta.requests} requests · ${DATA.meta.agent}`;
function fmt(v){if(v==null)return'';if(typeof v==='object'&&!Array.isArray(v)&&'amount'in v){return `${v.currency||''} ${Number(v.amount).toLocaleString('nb-NO')}`}
 if(Array.isArray(v)){if(!v.length)return'';if(typeof v[0]!=='object')return esc(v.join(', '));return '<details><summary>'+v.length+' items</summary>'+v.map(x=>'<div>'+Object.entries(x).filter(([k,y])=>y!=null&&y!==''&&k!=='evidence_id').map(([k,y])=>`<span class="badge">${esc(k)}</span> ${String(y).startsWith('http')?`<a href="${esc(y)}" target="_blank" rel="noopener">${esc(y)}</a>`:esc(typeof y==='object'?JSON.stringify(y):y)}`).join(' ')+'</div>').join('')+'</details>'}
 if(typeof v==='object')return esc(Object.entries(v).filter(([k,y])=>y!=null).map(([k,y])=>`${k}: ${typeof y==='object'?JSON.stringify(y):y}`).join(' · '));
 const s=String(v);return s.startsWith('http')?`<a href="${esc(s)}" target="_blank" rel="noopener">${esc(s)}</a>`:esc(s)}
function has(c,f){if(f==='changes')return (c.changes||[]).some(x=>x.material);if(f==='ambiguous')return Object.values(c.families||{}).some(x=>x.availability==='ambiguous');return (c.families?.[f]?.availability)==='available'}
function renderList(){const q=document.getElementById('q').value.trim().toLowerCase();const f=document.getElementById('f').value;
 const rows=C.filter(c=>(!q||(c.name||'').toLowerCase().includes(q)||c.organisation_number.includes(q.replace(/\s/g,'')))&&(!f||has(c,f)));
 document.getElementById('count').textContent=`${rows.length} shown`;
 document.getElementById('list').innerHTML=rows.map(c=>`<div class="item ${current===c.organisation_number?'active':''}" data-org="${c.organisation_number}" role="option"><input type="checkbox" ${sel.has(c.organisation_number)?'checked':''} aria-label="select for compare"><div><div class="n">${esc(c.name||c.organisation_number)}</div><div class="s">${c.organisation_number} · ${esc((c.claims||[]).find(x=>x.field==='municipality')?.value||'')}</div><div class="dots">${Object.keys(FAM).map(k=>`<span class="dot ${c.families?.[k]?.availability||''}" title="${FAM[k]}: ${c.families?.[k]?.availability||''}"></span>`).join('')}</div></div></div>`).join('');}
function show(org){current=org;const c=C.find(x=>x.organisation_number===org);if(!c)return;renderList();history.replaceState(null,'','#'+org);
 const ev=Object.fromEntries((c.evidence||[]).map(e=>[e.id,e]));const n={};let i=0;const ref=id=>{if(!(id in n))n[id]=++i;return `<a class="cite" href="#${id}">[${n[id]}]</a>`};
 const sum=(c.synthesis?.sentences||[]).map(s=>esc(s.text)+s.evidence_ids.map(ref).join('')).join(' ');
 const fam=Object.entries(c.families||{}).map(([k,v])=>`<span class="fam ${v.availability}" title="${esc(v.reason)}">${FAM[k]||k}: ${v.availability.replace('_',' ')}</span>`).join('');
 const groups={};(c.claims||[]).forEach(cl=>{(groups[cl.family]=groups[cl.family]||[]).push(cl)});
 const secs=Object.keys(FAM).map(k=>{const st=c.families?.[k]||{};const rows=(groups[k]||[]).map(cl=>`<tr><td>${esc(cl.field.replace(/_/g,' '))}${cl.reporting_period?`<div class="badge">${esc(cl.reporting_period)}</div>`:''}${cl.carried_forward?'<div class="badge">carried forward</div>':''}</td><td>${fmt(cl.value)}</td><td class="src">${cl.evidence_ids.map(ref).join('')}</td></tr>`).join('');
  return `<section><h3>${FAM[k]}<small>${esc(st.availability||'')}${st.reason?' — '+esc(st.reason):''}</small></h3>${rows?`<table>${rows}</table>`:`<div class="empty">Nothing published for this section.</div>`}</section>`}).join('');
 const ch=(c.changes||[]).filter(x=>x.material);const chHtml=ch.length?`<table>${ch.map(x=>`<tr><td>${esc(x.type)}</td><td>${esc(x.summary)}</td><td class="src">${(x.evidence_ids||[]).map(ref).join('')}</td></tr>`).join('')}</table>`:`<div class="empty">${c.refresh?.previous_snapshot?'No material changes since '+esc(c.refresh.previous_snapshot):'First observation — no earlier snapshot.'}</div>`;
 const unk=(c.synthesis?.unknowns||[]).map(u=>`<li>${esc(u.label)}: <b>${esc(u.availability.replace('_',' '))}</b> — ${esc(u.reason||'')}</li>`).join('');
 const evRows=Object.keys(n).map(id=>{const e=ev[id]||{};return `<tr class="ev-row" id="${id}"><td>[${n[id]}] <span class="ev">${id}</span></td><td><a href="${esc(e.source_url)}" target="_blank" rel="noopener">${esc(e.source_url)}</a><div class="sub">${esc(e.source_class)} · retrieved ${esc(e.retrieved_at)}${e.reporting_period?' · period '+esc(e.reporting_period):''}${e.claim_span?' · '+esc(e.claim_span):''}</div><div class="ev">sha256 ${esc((e.content_sha256||'').slice(0,16))}…</div></td></tr>`}).join('');
 document.getElementById('detail').innerHTML=`<h2>${esc(c.name)}</h2><div class="sub">Org. nr ${c.organisation_number} · <a href="https://virksomhet.brreg.no/nb/oppslag/enheter/${c.organisation_number}" target="_blank" rel="noopener">Brønnøysund record</a> · run ${esc(c.run?.run_id)} · ${esc(c.run?.completed_at)}</div>
 <div class="summary">${sum||esc(c.summary||'')}</div><div class="fams">${fam}</div>
 <section><h3>What changed<small>${esc(c.refresh?.mode||'')}</small></h3>${chHtml}</section>${secs}
 <section><h3>Unknown or unverified</h3>${unk?`<ul>${unk}</ul>`:'<div class="empty">Every section has published data.</div>'}</section>
 <section><h3>Sources<small>${Object.keys(n).length} cited</small></h3><table>${evRows}</table></section>`;
 if(innerWidth<860)document.getElementById('detail').scrollIntoView({behavior:'smooth'});}
function compare(){const cs=[...sel].map(o=>C.find(x=>x.organisation_number===o)).filter(Boolean);const val=(c,f)=>{const cl=(c.claims||[]).find(x=>x.field===f);return cl?fmt(cl.value):'<span class="empty">—</span>'};
 const F=[['legal_form','Legal form'],['municipality','Municipality'],['industry','Industry'],['founded_date','Founded'],['registered_employees','Employees'],['accounts_year','Accounts year'],['revenue','Revenue'],['operating_result','Operating result'],['annual_result','Net result'],['equity','Equity'],['revenue_change_yoy','Revenue change'],['chief_executive','CEO'],['board_chair','Chair'],['workplace_count','Workplaces'],['official_website','Website'],['linkedin_profile','LinkedIn'],['facebook_profile','Facebook'],['active_job_posting_count','Active jobs'],['latest_activity_date','Latest activity']];
 document.getElementById('detail').innerHTML=`<h2>Compare ${cs.length} companies</h2><div class="cmp"><table><tr><td></td>${cs.map(c=>`<td><a href="#${c.organisation_number}" onclick="show('${c.organisation_number}');return false"><b>${esc(c.name)}</b></a><div class="sub">${c.organisation_number}</div></td>`).join('')}</tr>${F.map(([f,l])=>`<tr><td>${l}</td>${cs.map(c=>`<td>${val(c,f)}</td>`).join('')}</tr>`).join('')}</table></div>`;}
document.getElementById('list').addEventListener('click',e=>{const it=e.target.closest('.item');if(!it)return;const org=it.dataset.org;if(e.target.type==='checkbox'){e.target.checked?sel.add(org):sel.delete(org);document.getElementById('cmpBtn').disabled=sel.size<2;return}show(org)});
document.getElementById('cmpBtn').onclick=compare;document.getElementById('q').oninput=renderList;document.getElementById('f').onchange=renderList;
renderList();const h=location.hash.slice(1);show(/^\d{9}$/.test(h)?h:C[0]?.organisation_number);
</script>
</body>
</html>
"""
