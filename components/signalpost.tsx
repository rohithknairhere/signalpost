'use client';
import {createContext,useCallback,useContext,useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {Search,ArrowUpRight,ArrowRight,Moon,Sun,Check,SlidersHorizontal,ArrowLeft,ExternalLink,FileText,GitCompareArrows,X,ChevronLeft,ChevronRight,Plus,Quote,ShieldCheck} from 'lucide-react';
import {families,human,status,findClaim,evidenceIds,safeUrl,sourceAnchor,comparison,formatValue,plain,describeSource,niceDate,type Company,type Value,type Claim,type IndexEntry,type Meta,type Availability} from '@/lib/signalpost';

const B = process.env.NEXT_PUBLIC_BASE_PATH || '';
export const logo = 'https://keystone.jboxai.com/project-assets/bvtpbeiegkxcvfpmod0f6yjf/id0k8z9cfjt3uxn1f9ak8kq2/5b2ede2f59b2c81b635fa939f792bf59b281aefefab6f3e2d62e115615357f83/5b2ede2f59b2c81b.svg';
const period = (p: string) => { const m = /^(\d{4})-01-01\/(\d{4})-12-31$/.exec(p); return m && m[1] === m[2] ? `Financial year ${m[1]}` : `Period ${p}`; };
const titleCase = (s: string) => s.toLocaleLowerCase('nb').replace(/(^|[\s-])(\p{L})/gu, (_, a: string, b: string) => a + b.toLocaleUpperCase('nb'));
const spacedOrg = (n: string) => n.replace(/(\d{3})(\d{3})(\d{3})/, '$1 $2 $3');

/* ------------------------------------------------------------------ source panel */

type SourceRef = {c: Company; id: string};
const SourceContext = createContext<(ref: SourceRef) => void>(() => {});

function SourcePanel({open, onClose, onMove}: {open?: SourceRef; onClose: () => void; onMove: (id: string) => void}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    document.body.classList.add('sheet-open');
    return () => { document.removeEventListener('keydown', onKey); document.body.classList.remove('sheet-open'); };
  }, [open, onClose]);
  if (!open) return null;
  const {c, id} = open;
  const ids = evidenceIds(c);
  const index = ids.indexOf(id);
  const ev = c.evidence.find(e => e.id === id);
  const facts = c.claims.filter(cl => cl.evidence_ids.includes(id));
  const who = ev ? describeSource(ev) : undefined;
  return (
    <div className="sheet-layer" onClick={onClose}>
      <aside className="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title" onClick={e => e.stopPropagation()}>
        <header className="sheet-head">
          <div>
            <span className="eyebrow">SOURCE {index + 1} OF {ids.length} · {c.name}</span>
            <h2 id="sheet-title">{who?.publisher || 'Source not included'}</h2>
          </div>
          <button ref={closeRef} className="icon-button" aria-label="Close source" onClick={onClose}><X size={18}/></button>
        </header>
        {ev && who ? (
          <div className="sheet-body">
            <div className="source-facts">
              <span className="pill"><ShieldCheck size={13}/>{who.kind}</span>
              <span className="pill">Retrieved {niceDate(ev.retrieved_at)}</span>
              {ev.reporting_period && <span className="pill">{period(ev.reporting_period)}</span>}
            </div>
            {ev.claim_span && <blockquote><Quote size={16}/><span>{ev.claim_span}</span></blockquote>}
            <div className="sheet-actions">
              {safeUrl(ev.source_url) && <a className="button" href={ev.source_url} target="_blank" rel="noreferrer">Open original source <ArrowUpRight size={15}/></a>}
              {who.human && <a className="button ghost" href={who.human} target="_blank" rel="noreferrer">Official register page <ExternalLink size={14}/></a>}
            </div>
            <p className="source-url"><code>{ev.source_url}</code></p>
            <h3>Facts from this source <span className="count">{facts.length}</span></h3>
            {facts.length ? (
              <ul className="fact-list">
                {facts.slice(0, 12).map(cl => <li key={cl.id}><span>{human(cl.field)}</span><strong><ValueView field={cl.field} value={cl.value}/></strong></li>)}
                {facts.length > 12 && <li className="more">and {facts.length - 12} more on the company page</li>}
              </ul>
            ) : <p>This source supports the summary text.</p>}
            <details className="fingerprint">
              <summary>Content fingerprint</summary>
              <p>SHA-256 of the page exactly as it was retrieved. If the page changes, a new run records a different fingerprint.</p>
              <code>{ev.content_sha256}</code>
            </details>
          </div>
        ) : <div className="sheet-body"><p>Evidence reference {id} was not included in this snapshot.</p></div>}
        <footer className="sheet-foot">
          <button className="ghost" disabled={index <= 0} onClick={() => onMove(ids[index - 1])}><ChevronLeft size={16}/>Previous</button>
          <a href={`${B}/company/${c.organisation_number}/#sources`}>All {ids.length} sources</a>
          <button className="ghost" disabled={index >= ids.length - 1} onClick={() => onMove(ids[index + 1])}>Next<ChevronRight size={16}/></button>
        </footer>
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------------ shell */

export function Shell({children}: {children: ReactNode}) {
  const [dark, setDark] = useState(false);
  const [source, setSource] = useState<SourceRef>();
  const lastFocus = useRef<HTMLElement | null>(null);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- theme is only known in the browser
  useEffect(() => { try { const d = localStorage.getItem('signalpost-theme'); setDark(d ? d === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches); } catch { /* storage unavailable */ } }, []);
  useEffect(() => { document.documentElement.dataset.theme = dark ? 'dark' : 'light'; }, [dark]);
  const openSource = useCallback((ref: SourceRef) => { lastFocus.current = document.activeElement as HTMLElement; setSource(ref); }, []);
  const close = useCallback(() => { setSource(undefined); setTimeout(() => lastFocus.current?.focus(), 0); }, []);
  return (
    <SourceContext.Provider value={openSource}>
      <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <div className="top-inner">
          <a href={B + '/'} className="brand"><img src={logo} width="32" height="32" alt=""/>Signalpost<span className="beta">COMPANY INTELLIGENCE</span></a>
          <nav aria-label="Main">
            <a href={B + '/'} className="navlink">Directory</a>
            <a href={B + '/compare/'} className="navlink">Compare</a>
            <button className="icon-button" aria-label={dark ? 'Use light theme' : 'Use dark theme'} onClick={() => { setDark(!dark); try { localStorage.setItem('signalpost-theme', !dark ? 'dark' : 'light'); } catch { /* ignore */ } }}>{dark ? <Sun size={18}/> : <Moon size={18}/>}</button>
          </nav>
        </div>
      </header>
      {children}
      <footer className="bottom">
        <a className="brand" href={B + '/'}>Signalpost</a>
        <span>Read-only snapshot. Every fact links to its source.</span>
        <span>Built with JBOX</span>
      </footer>
      <SourcePanel open={source} onClose={close} onMove={id => source && setSource({c: source.c, id})}/>
    </SourceContext.Provider>
  );
}

/* ------------------------------------------------------------------ values and citations */

export function ValueView({value, field = ''}: {value: Value; field?: string}) {
  const formatted = formatValue(field, value);
  if (formatted !== undefined) return <>{formatted}</>;
  if (value === null || value === undefined) return <>—</>;
  if (typeof value === 'string') return safeUrl(value) ? <a href={value} target="_blank" rel="noreferrer" className="ext">{value.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')} <ArrowUpRight size={12}/></a> : <>{value}</>;
  if (typeof value === 'number') return <>{value.toLocaleString('en-GB')}</>;
  if (typeof value === 'boolean') return <>{value ? 'Yes' : 'No'}</>;
  if (Array.isArray(value)) return value.length ? <details><summary>{value.length} {value.length === 1 ? 'item' : 'items'} · show</summary><ul className="value-list">{value.map((v, i) => <li key={i}><ValueView value={v}/></li>)}</ul></details> : <>None</>;
  return <dl className="object">{Object.entries(value).map(([k, v]) => <div key={k}><dt>{human(k)}</dt><dd><ValueView field={k} value={v}/></dd></div>)}</dl>;
}

export function Citations({c, ids}: {c: Company; ids: string[]}) {
  const open = useContext(SourceContext);
  const all = evidenceIds(c);
  if (!ids.length) return <span className="citations" title="No evidence reference supplied">[no source]</span>;
  return (
    <span className="citations">
      {ids.map(id => c.evidence.some(e => e.id === id)
        ? <button type="button" key={id} className="cite" aria-label={`Show source ${all.indexOf(id) + 1} for ${c.name}`} title="Show where this came from" onClick={() => open({c, id})}>{all.indexOf(id) + 1}</button>
        : <span key={id} title={id}>[unresolved]</span>)}
    </span>
  );
}

function ClaimValue({c, claim, family}: {c: Company; claim?: Claim; family: string}) {
  if (claim && claim.value !== null) return <><ValueView field={claim.field} value={claim.value}/><Citations c={c} ids={claim.evidence_ids}/>{claim.reporting_period && <small className="badge">{period(claim.reporting_period)}</small>}</>;
  return <span className="missing">—<small>{status(c, family).reason}</small></span>;
}

export function Status({c, f, compact = false}: {c: Company; f: string; compact?: boolean}) {
  const s = status(c, f);
  return <span tabIndex={compact ? -1 : 0} className={`${compact ? 'dot' : 'status'} ${s.availability}`} aria-label={`${human(f)}: ${human(s.availability)}. ${s.reason}`} title={`${human(f)} · ${human(s.availability)}: ${s.reason}`}>{!compact && <><i/>{human(f)}<small>{human(s.availability)}</small></>}</span>;
}

/* ------------------------------------------------------------------ app shell with snapshot details */

export function DataApp({view, meta, index = [], company, total = 0}: {view: 'home' | 'company' | 'compare'; meta: Meta; index?: IndexEntry[]; company?: Company; total?: number}) {
  return (
    <Shell>
      {view === 'home' ? <Home index={index}/> : view === 'compare' ? <Compare index={index}/> : <Profile c={company} total={total}/>}
      <div className="run wrap">
        <span className="eyebrow">SNAPSHOT DETAILS</span>
        <span>Run <code>{meta.run_id}</code></span>
        <span>Completed {niceDate(meta.completed_at)}</span>
        <span>{meta.input_count} companies · {meta.requests.toLocaleString('en-GB')} requests</span>
        <span>{meta.agent}</span>
      </div>
    </Shell>
  );
}

/* ------------------------------------------------------------------ search helpers */

const norm = (s: string) => s.toLocaleLowerCase('nb').normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/ø/g, 'o').replace(/æ/g, 'ae').replace(/[^a-z0-9]/g, '');
const haystack = (e: IndexEntry) => norm([e.name, e.organisation_number, e.municipality, e.industry, e.ceo, e.domain].join(' '));
const matches = (e: IndexEntry, q: string) => q.split(/\s+/).map(norm).filter(Boolean).every(t => haystack(e).includes(t));

/* ------------------------------------------------------------------ directory */

const filters = ['Verified website', 'Social profiles', 'Hiring', 'Customer ratings', 'Filed accounts', 'Has ambiguous matches'];
const DOT_LABELS: Record<Availability, string> = {available: 'found', ambiguous: 'unproven', failed: 'failed', blocked: 'blocked', not_available: 'none found', not_applicable: 'not applicable'};

function Home({index}: {index: IndexEntry[]}) {
  const [q, setQ] = useState('');
  const [active, setActive] = useState<string[]>([]);
  const [sort, setSort] = useState<'coverage' | 'name' | 'revenue'>('coverage');
  const [selected, setSelected] = useState<string[]>([]);
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const p = new URLSearchParams(location.search);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read once from the URL after hydration
    if (p.get('q')) setQ(p.get('q') || '');
    try { const s = JSON.parse(sessionStorage.getItem('signalpost-compare') || '[]'); if (Array.isArray(s)) setSelected(s.filter((x: unknown) => typeof x === 'string').slice(0, 3)); } catch { /* ignore */ }
    const onKey = (e: KeyboardEvent) => { if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') { e.preventDefault(); searchRef.current?.focus(); } };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
  useEffect(() => { try { sessionStorage.setItem('signalpost-compare', JSON.stringify(selected)); } catch { /* ignore */ } }, [selected]);
  const updateQuery = (value: string) => { setQ(value); const url = new URL(location.href); if (value) url.searchParams.set('q', value); else url.searchParams.delete('q'); history.replaceState(null, '', url); };
  const ranked = useMemo(() => [...index].sort((a, b) => b.coverage - a.coverage || a.name.localeCompare(b.name, 'nb')), [index]);
  const results = useMemo(() => {
    const list = index.filter(e => matches(e, q) && active.every(f => e.flags.includes(f)));
    return list.sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name, 'nb') : sort === 'revenue' ? (b.revenue ?? -Infinity) - (a.revenue ?? -Infinity) : b.coverage - a.coverage || a.name.localeCompare(b.name, 'nb'));
  }, [index, q, active, sort]);
  const examples = useMemo(() => {
    const top = ranked[0];
    const places = new Map<string, number>();
    index.forEach(e => e.municipality && places.set(e.municipality, (places.get(e.municipality) || 0) + 1));
    const place = [...places.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    const other = ranked.find(e => e !== top && e.flags.includes('Verified website'));
    return [top && {label: titleCase(top.name.replace(/\s+(AS|ASA|SA|DA)$/i, '')), q: top.name}, place && {label: titleCase(place), q: place}, other && {label: spacedOrg(other.organisation_number), q: other.organisation_number}].filter(Boolean) as {label: string; q: string}[];
  }, [index, ranked]);
  const exampleCompare = ranked.filter(e => e.flags.includes('Verified website')).slice(0, 2).map(e => e.organisation_number);
  const toggle = (org: string, on: boolean) => setSelected(on ? [...selected, org].slice(0, 3) : selected.filter(n => n !== org));
  const byOrg = (o: string) => index.find(e => e.organisation_number === o);
  return (
    <main id="main" className="wrap">
      <section className="intro">
        <div className="eyebrow"><span className="live-dot"/> NORWEGIAN COMPANY INTELLIGENCE</div>
        <h1>A clearer picture.<br/><em>Every fact, a source.</em></h1>
        <p>Find a Norwegian company, open its profile, and tap any number to see exactly where it came from.</p>
      </section>
      <section className="directory" aria-label="Company directory">
        <div className="searchbox">
          <Search size={22}/>
          <label className="sr-only" htmlFor="search">Search by name, organisation number, municipality, industry or CEO</label>
          <input id="search" ref={searchRef} type="search" autoComplete="off" value={q} onChange={e => updateQuery(e.target.value)} placeholder="Company, org. number, place or industry"/>
          {q ? <button className="text-button" onClick={() => updateQuery('')}>Clear</button> : <kbd className="desktop-only">/</kbd>}
        </div>
        <div className="examples">
          <span>Try</span>
          {examples.map(x => <button key={x.q} className="example" onClick={() => updateQuery(x.q)}>{x.label}</button>)}
          {exampleCompare.length === 2 && <a className="example-link" href={`${B}/compare/?orgs=${exampleCompare.join(',')}`}><GitCompareArrows size={14}/>See an example comparison</a>}
        </div>
        <div className="filters">
          <span className="filter-label"><SlidersHorizontal size={14}/> Show only</span>
          {filters.map(f => <button key={f} aria-pressed={active.includes(f)} className={`chip ${active.includes(f) ? 'selected' : ''}`} onClick={() => setActive(active.includes(f) ? active.filter(x => x !== f) : [...active, f])}>{active.includes(f) && <Check size={12}/>} {f}</button>)}
          {active.length > 0 && <button className="text-button" onClick={() => setActive([])}>Clear filters</button>}
        </div>
        <div className="list-heading">
          <div>
            <h2 aria-live="polite">{results.length === index.length ? 'All companies' : 'Matching companies'} <span>{results.length}</span></h2>
            <p>Tick up to 3 companies to compare them side by side.</p>
          </div>
          <label className="sort">Sort by
            <select value={sort} onChange={e => setSort(e.target.value as typeof sort)}>
              <option value="coverage">Most information</option>
              <option value="revenue">Revenue</option>
              <option value="name">Name A–Z</option>
            </select>
          </label>
        </div>
        <div className="table-head"><span>COMPANY</span><span>INDUSTRY · PLACE</span><span>WHAT WE FOUND</span></div>
        <div className="company-list">
          {results.map(e => {
            const on = selected.includes(e.organisation_number);
            return (
              <article className={`company-row ${on ? 'picked' : ''}`} key={e.organisation_number}>
                <div className="company-name">
                  <label className="pick" title={on ? 'Remove from comparison' : 'Add to comparison'}>
                    <input type="checkbox" aria-label={`Compare ${e.name}`} checked={on} disabled={selected.length === 3 && !on} onChange={ev => toggle(e.organisation_number, ev.target.checked)}/>
                  </label>
                  <div>
                    <a href={B + '/company/' + e.organisation_number + '/'}>{e.name}<ArrowUpRight size={15}/></a>
                    <code>{spacedOrg(e.organisation_number)}</code>
                  </div>
                </div>
                <div className="municipality"><span className="industry">{e.industry.replace(/^[\d.]+\s*/, '') || '—'}</span><span>{e.municipality || '—'}</span></div>
                <div className="coverage" aria-label={`${e.coverage} of ${families.length} kinds of information found`}>
                  <span className="coverage-dots" aria-hidden="true">{e.dots.map((d, i) => <span key={i} className={`dot ${d}`} title={`${human(families[i])}: ${DOT_LABELS[d]}`}/>)}</span>
                  <span className="coverage-text">{e.coverage}/{families.length}</span>
                </div>
              </article>
            );
          })}
        </div>
        {!results.length && <div className="empty"><Search/><h3>No matching companies</h3><p>Try part of the name, the 9-digit number, a place or an industry.</p><button onClick={() => { updateQuery(''); setActive([]); }}>Reset search</button></div>}
        <div className="list-foot">
          <span>{results.length} of {index.length} companies in this snapshot</span>
          <div className="legend"><span><i className="dot available"/>Found</span><span><i className="dot ambiguous"/>Unproven</span><span><i className="dot failed"/>Blocked / failed</span><span><i className="dot not_available"/>None / not applicable</span></div>
        </div>
      </section>
      <aside className="method-note">
        <div className="note-icon"><FileText size={21}/></div>
        <div><h3>Evidence, not assumptions.</h3><p>Every fact carries a numbered source. Tap a number to see the original page, when it was read, and every other fact it supports.</p></div>
      </aside>
      {selected.length > 0 && (
        <div className="tray" role="region" aria-label="Comparison selection">
          <div className="tray-inner">
            <div className="tray-items">
              {selected.map(o => <span className="tray-chip" key={o}>{byOrg(o)?.name || o}<button aria-label={`Remove ${byOrg(o)?.name || o}`} onClick={() => toggle(o, false)}><X size={13}/></button></span>)}
              {selected.length < 3 && <span className="tray-hint">{selected.length === 1 ? 'Tick one more to compare' : 'You can add one more'}</span>}
            </div>
            <a className={`button ${selected.length < 2 ? 'disabled' : ''}`} aria-disabled={selected.length < 2} href={selected.length >= 2 ? B + '/compare/?orgs=' + selected.join(',') : undefined}><GitCompareArrows size={16}/>Compare {selected.length}</a>
          </div>
        </div>
      )}
    </main>
  );
}

/* ------------------------------------------------------------------ company picker */

function CompanyPicker({index, exclude, onPick, label}: {index: IndexEntry[]; exclude: string[]; onPick: (org: string) => void; label: string}) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const found = index
    .filter(e => !exclude.includes(e.organisation_number) && matches(e, q))
    .sort((a, b) => b.coverage - a.coverage)
    .slice(0, 6);
  return (
    <div className="picker" onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false); }}>
      <div className="picker-input">
        <Plus size={16}/>
        <input aria-label={label} placeholder={label} value={q} onFocus={() => setOpen(true)} onChange={e => { setQ(e.target.value); setOpen(true); }}/>
      </div>
      {open && (
        <ul className="picker-list" role="listbox" aria-label="Matching companies">
          {found.map(e => <li key={e.organisation_number}><button type="button" role="option" aria-selected="false" onClick={() => { onPick(e.organisation_number); setQ(''); setOpen(false); }}><strong>{e.name}</strong><small>{spacedOrg(e.organisation_number)} · {e.municipality || '—'}</small></button></li>)}
          {!found.length && <li className="none">No matching company</li>}
        </ul>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ compare */

const companyCache = new Map<string, Promise<Company>>();
function fetchCompany(org: string) {
  if (!companyCache.has(org)) {
    companyCache.set(org, fetch(`${B}/data/company/${org}`).then(r => { if (!r.ok) throw Error(`Could not load ${org}`); return r.json() as Promise<Company>; }));
  }
  return companyCache.get(org)!;
}

function Compare({index}: {index: IndexEntry[]}) {
  const [orgs, setOrgs] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [loaded, setLoaded] = useState<Record<string, Company>>({});
  const [failed, setFailed] = useState('');
  const [onlyDiff, setOnlyDiff] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- read once from the URL after hydration
  useEffect(() => { setOrgs([...new Set((new URLSearchParams(location.search).get('orgs') || '').split(',').filter(Boolean))]); setReady(true); }, []);
  const known = orgs.filter(o => index.some(e => e.organisation_number === o)).slice(0, 3);
  const invalid = orgs.filter(n => !index.some(e => e.organisation_number === n));
  useEffect(() => {
    let live = true;
    known.filter(o => !loaded[o]).forEach(o => fetchCompany(o)
      .then(c => { if (live) setLoaded(prev => ({...prev, [o]: c})); })
      .catch(e => { if (live) setFailed(e.message); }));
    return () => { live = false; };
  }, [known.join(','), loaded]); // eslint-disable-line react-hooks/exhaustive-deps
  const update = (next: string[]) => { setOrgs(next); const url = new URL(location.href); if (next.length) url.searchParams.set('orgs', next.join(',')); else url.searchParams.delete('orgs'); history.replaceState(null, '', url); };
  const selected = known.map(o => loaded[o]).filter((c): c is Company => !!c);
  const waiting = known.length > selected.length && !failed;
  const nameOf = (o: string) => index.find(e => e.organisation_number === o)?.name || o;
  const rows = comparison.map(([label, f, aliases]) => {
    const claims = selected.map(c => findClaim(c, ...aliases));
    const texts = claims.map(cl => cl ? plain(cl.field, cl.value) : '');
    return {label, f, claims, same: selected.length > 1 && texts.every(t => t === texts[0]), empty: texts.every(t => !t)};
  });
  const shown = rows.filter(r => !(onlyDiff && (r.same || r.empty)));
  return (
    <main id="main" className="wrap compare-page" style={{['--n' as string]: Math.max(1, selected.length)}}>
      <a className="back" href={B + '/'}><ArrowLeft size={14}/>Company directory</a>
      <div className="eyebrow">SIDE BY SIDE</div>
      <h1>Compare companies.</h1>
      <p className="lead">The same questions for each company, with the source behind every answer.</p>
      {invalid.length > 0 && <p role="alert" className="panel">Not in this snapshot: {invalid.join(', ')}.</p>}
      {failed && <p role="alert" className="panel">{failed}. <button className="text-button" onClick={() => { companyCache.clear(); setFailed(''); setLoaded({}); }}>Try again</button></p>}
      <div className="compare-controls">
        <div className="compare-chips">
          {known.map(o => <span className="tray-chip" key={o}>{nameOf(o)}<button aria-label={`Remove ${nameOf(o)}`} onClick={() => update(orgs.filter(x => x !== o))}><X size={13}/></button></span>)}
        </div>
        {known.length < 3 && <CompanyPicker index={index} exclude={orgs} onPick={o => update([...known, o].slice(0, 3))} label={known.length ? 'Add a company to compare' : 'Search for a company to compare'}/>}
        {selected.length > 1 && <label className="toggle"><input type="checkbox" checked={onlyDiff} onChange={e => setOnlyDiff(e.target.checked)}/> Only show differences</label>}
      </div>
      {!ready ? (
        <p className="empty" aria-live="polite">Loading the comparison…</p>
      ) : !known.length ? (
        <div className="empty"><GitCompareArrows/><h2>Pick two or three companies</h2><p>Search above, or tick companies in the directory.</p><a className="button" href={B + '/'}>Browse companies <ArrowRight size={16}/></a></div>
      ) : waiting ? (
        <p className="empty" aria-live="polite">Loading {known.length} {known.length === 1 ? 'company' : 'companies'}…</p>
      ) : (
        <>
          <div className="compare-heads" aria-hidden="true">{selected.map(c => <a key={c.organisation_number} href={B + '/company/' + c.organisation_number + '/'}>{c.name}</a>)}</div>
          <div className="table-scroll" role="region" aria-label="Company comparison" tabIndex={0}>
            <table className="compare-table">
              <thead><tr><th scope="col">Fact</th>{selected.map(c => <th scope="col" key={c.organisation_number}><a href={B + '/company/' + c.organisation_number + '/'}>{c.name}<ArrowUpRight size={14}/></a><code>{spacedOrg(c.organisation_number)}</code></th>)}</tr></thead>
              <tbody>
                {shown.map(r => (
                  <tr key={r.label} className={r.same ? 'same' : ''}>
                    <th scope="row">{r.label}{r.same && !r.empty && <small className="badge">Same</small>}</th>
                    {selected.map((c, i) => <td key={c.organisation_number} data-company={c.name}><ClaimValue c={c} claim={r.claims[i]} family={r.f}/></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {onlyDiff && !shown.length && <p className="panel">No differences in the compared facts.</p>}
          <p className="reason">Figures are shown as filed, without currency conversion. Check the reporting period before comparing amounts.</p>
        </>
      )}
    </main>
  );
}

/* ------------------------------------------------------------------ profile */

const KEY_FACTS: [string, string, string[]][] = [
  ['Industry', 'legal_identity', ['industry']],
  ['Municipality', 'legal_identity', ['municipality']],
  ['Founded', 'legal_identity', ['founded_date']],
  ['CEO', 'leadership', ['chief_executive']],
  ['Website', 'official_website', ['official_website']],
  ['Employees (registry)', 'legal_identity', ['registered_employees']],
  ['Revenue', 'annual_accounts', ['revenue']],
  ['Net result', 'annual_accounts', ['annual_result']],
  ['Equity', 'annual_accounts', ['equity']],
];

function Profile({c, total}: {c?: Company; total: number}) {
  useEffect(() => { if (location.hash) { const el = document.getElementById(decodeURIComponent(location.hash.slice(1))); el?.scrollIntoView(); el?.focus(); } }, [c]);
  const open = useContext(SourceContext);
  if (!c) return <main id="main" className="wrap empty"><h1>Company not in this snapshot</h1><p>Check the organisation number or choose a company from the directory.</p><a className="button" href={B + '/'}>Back to directory</a></main>;
  const keys = [...new Set([...families, ...Object.keys(c.families), ...c.claims.map(x => x.family), ...c.synthesis.unknowns.map(x => x.family)])];
  const changes = c.changes.filter(x => x.material);
  const ids = evidenceIds(c);
  return (
    <main id="main" className="wrap profile">
      <a className="back" href={B + '/'}><ArrowLeft size={14}/>Company directory</a>
      <header className="profile-header">
        <div className="eyebrow">COMPANY PROFILE</div>
        <h1>{c.name}</h1>
        <div className="meta">
          <code>{spacedOrg(c.organisation_number)}</code>
          <a href={`https://virksomhet.brreg.no/nb/oppslag/enheter/${c.organisation_number}`} target="_blank" rel="noreferrer">Official register <ExternalLink size={13}/></a>
          <span>Researched {niceDate(c.run.completed_at)}</span>
        </div>
        <div className="profile-actions">
          <a className="button" href={`${B}/compare/?orgs=${c.organisation_number}`}><GitCompareArrows size={16}/>Compare<span className="desktop-only">&nbsp;with another company</span></a>
          <a className="button ghost" href="#sources"><FileText size={15}/>{ids.length} sources</a>
        </div>
      </header>
      <section className="key-facts" aria-label="Key facts">
        {KEY_FACTS.map(([label, f, fields]) => {
          const cl = findClaim(c, ...fields);
          return <div key={label}><span className="eyebrow">{label}</span><strong>{cl && cl.value !== null ? <><ValueView field={cl.field} value={cl.value}/><Citations c={c} ids={cl.evidence_ids}/></> : <span className="missing-inline" title={status(c, f).reason}>Not found</span>}</strong>{cl?.reporting_period && <small>{period(cl.reporting_period)}</small>}</div>;
        })}
      </section>
      <section className="summary-card">
        <div className="eyebrow">THE EVIDENCE BRIEF</div>
        <div className="synthesis">{c.synthesis.sentences.length ? c.synthesis.sentences.map((s, i) => <span key={i}>{s.text}<Citations c={c} ids={s.evidence_ids}/>{' '}</span>) : <p>No sourced synthesis in this snapshot.</p>}</div>
      </section>
      <section className="changes panel"><h2>What changed</h2>{changes.length ? changes.map((x, i) => <p key={i}><span className="badge">{human(x.type)}</span> {x.summary}<Citations c={c} ids={x.evidence_ids}/></p>) : <p>{c.refresh.previous_snapshot ? 'No material changes since ' + c.refresh.previous_snapshot : 'First observation of this company.'}</p>}</section>
      <div className="statuses">{keys.map(f => <Status c={c} f={f} key={f}/>)}</div>
      <div className="profile-body">
        <nav className="section-nav" aria-label="Sections of this profile">
          <div className="eyebrow">IN THIS PROFILE</div>
          {keys.map(f => <a key={f} href={'#family-' + f}>{human(f)}</a>)}
          <a href="#unknowns">Unknown or unproven</a>
          <a href="#sources">Sources ({ids.length})</a>
        </nav>
        <div className="sections">
          {keys.map(f => (
            <section id={'family-' + f} key={f} className="family-section">
              <div className="section-title"><h2>{human(f)}</h2><span className={'badge ' + status(c, f).availability}>{human(status(c, f).availability)}</span></div>
              <p className="reason">{status(c, f).reason}</p>
              {c.claims.filter(x => x.family === f).map(cl => (
                <div className="claim-row" key={cl.id}>
                  <div>{human(cl.field)}{cl.key && <small>{human(cl.key)}</small>}</div>
                  <div><ClaimValue c={c} claim={cl} family={f}/>{cl.carried_forward && <div className="claim-meta"><span className="badge">Carried forward from the previous run</span></div>}</div>
                </div>
              ))}
            </section>
          ))}
          <section id="unknowns" className="family-section">
            <h2>Unknown or unproven</h2>
            {c.synthesis.unknowns.length ? c.synthesis.unknowns.map((u, i) => <div className="unknown" key={i}><strong>{u.label}</strong><span className="badge">{human(u.availability)}</span><p>{u.reason}</p></div>) : <p>No unknowns recorded in this snapshot.</p>}
          </section>
          <section id="sources" className="family-section">
            <div className="eyebrow">THE AUDIT TRAIL</div>
            <h2>Sources</h2>
            <p className="reason">The original pages behind this profile. Open one to see what it says and which facts it supports.</p>
            {ids.map((id, i) => {
              const ev = c.evidence.find(e => e.id === id);
              const who = ev ? describeSource(ev) : undefined;
              const n = c.claims.filter(cl => cl.evidence_ids.includes(id)).length;
              return (
                <article key={id} tabIndex={-1} className="source" id={sourceAnchor(id)}>
                  <div className="source-number">{i + 1}</div>
                  {ev && who ? (
                    <div>
                      <strong className="source-title">{who.publisher}</strong>
                      <div className="source-meta"><span>{who.kind}</span><span>Retrieved {niceDate(ev.retrieved_at)}</span>{ev.reporting_period && <span>{period(ev.reporting_period)}</span>}<span>{n} fact{n === 1 ? '' : 's'}</span></div>
                      <div className="source-links"><button className="ghost small" onClick={() => open({c, id})}>Details</button><a href={safeUrl(ev.source_url)} target="_blank" rel="noreferrer">Open original <ArrowUpRight size={13}/></a></div>
                    </div>
                  ) : <p>Evidence reference {id} was not included in this snapshot.</p>}
                </article>
              );
            })}
            {!ids.length && <p>No cited evidence supplied.</p>}
          </section>
        </div>
      </div>
      <p className="reason">One of {total} companies in this snapshot.</p>
    </main>
  );
}
