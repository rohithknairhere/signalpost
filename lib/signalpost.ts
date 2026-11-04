export const families = ['legal_identity','public_brand','annual_accounts','account_history','leadership','registered_workplaces','official_website','company_profiles','website_contact','hiring','public_activity'] as const;
export const labels: Record<string,string> = {legal_identity:'Legal identity',public_brand:'Public brand',annual_accounts:'Annual accounts',account_history:'Account history',leadership:'Leadership',registered_workplaces:'Workplaces',official_website:'Website',company_profiles:'Social & video profiles',website_contact:'Contact',hiring:'Hiring',public_activity:'Dated activity',workforce:'Workforce',ratings_reviews:'Customer ratings',chief_executive:'CEO',founded_date:'Founded',registered_employees:'Employees (registry)',full_time_equivalents:'Workforce (FTE)',revenue_change_yoy:'Revenue change',active_job_posting_count:'Open job ads',latest_activity_date:'Latest activity',linkedin_profile:'LinkedIn',facebook_profile:'Facebook',instagram_profile:'Instagram',youtube_profile:'YouTube',tiktok_profile:'TikTok',x_profile:'X'};
export type Availability = 'available'|'not_available'|'blocked'|'not_applicable'|'ambiguous'|'failed';
export type Value = string|number|boolean|null|Value[]|{[key:string]:Value};
export type Claim = {id:string;family:string;field:string;key?:string;value:Value;reporting_period?:string;as_of?:string;confidence:string|number;carried_forward?:boolean;evidence_ids:string[]};
export type Evidence={id:string;source_url:string;source_class:string;retrieved_at:string;content_sha256:string;claim_span?:string;reporting_period?:string};
export type Company={organisation_number:string;name:string;summary:string;run:{run_id:string;completed_at:string};families:Record<string,{availability:Availability;reason:string}>;claims:Claim[];evidence:Evidence[];synthesis:{sentences:{text:string;evidence_ids:string[]}[];unknowns:{family:string;label:string;availability:Availability;reason:string}[]};changes:{type:string;family:string;field:string;summary:string;material:boolean;evidence_ids:string[]}[];refresh:{mode:string;previous_snapshot:string|null}};
export type Dataset={meta:{run_id:string;completed_at:string;input_count:number;requests:number;agent:string};companies:Company[]};
export const human=(s:string)=> labels[s] || s.replace(/_/g,' ').replace(/^./,c=>c.toUpperCase());
export const safeUrl=(s:string)=>/^https?:\/\//i.test(s)?s:undefined;
export const status=(c:Company,f:string)=>c.families[f]||{availability:'not_available' as Availability,reason:'No information for this family in this snapshot.'};
export function findClaim(c:Company,...fields:string[]){return c.claims.filter(x=>fields.includes(x.key||'')||fields.includes(x.field)).sort((a,b)=>String(b.reporting_period||b.as_of||'').localeCompare(String(a.reporting_period||a.as_of||'')))[0]}
export function evidenceIds(c:Company){return [...new Set([...c.synthesis.sentences.flatMap(x=>x.evidence_ids),...c.claims.flatMap(x=>x.evidence_ids),...c.changes.flatMap(x=>x.evidence_ids)])]}
export const sourceAnchor=(id:string)=>'source-'+encodeURIComponent(id);
export function validDataset(x:unknown):x is Dataset {if(!x||typeof x!=='object')return false;const d=x as Dataset;return !!d.meta&&Array.isArray(d.companies)&&d.companies.every(c=>/^\d{9}$/.test(c.organisation_number)&&typeof c.name==='string'&&c.run&&c.families&&Array.isArray(c.claims)&&c.claims.every(x=>Array.isArray(x.evidence_ids))&&Array.isArray(c.evidence)&&c.synthesis&&Array.isArray(c.synthesis.sentences)&&Array.isArray(c.synthesis.unknowns)&&Array.isArray(c.changes)&&c.refresh)}
export const comparison:[string,string,string[]][]=[['Legal form','legal_identity',['legal_form']],['Municipality','legal_identity',['municipality']],['Industry','legal_identity',['industry']],['Founded','legal_identity',['founded','foundation_date','founded_date']],['Employees (registry)','legal_identity',['registered_employees','employees']],['Workforce (FTE)','workforce',['full_time_equivalents','average_employees']],['Accounts year','annual_accounts',['accounts_year']],['Revenue','annual_accounts',['revenue']],['Operating result','annual_accounts',['operating_result']],['Net result','annual_accounts',['annual_result','net_result']],['Equity','annual_accounts',['equity']],['Revenue change','account_history',['revenue_change','revenue_change_yoy']],['CEO','leadership',['ceo','chief_executive']],['Board chair','leadership',['board_chair']],['Workplaces','registered_workplaces',['workplace_count','workplaces','registered_workplaces']],['Website','official_website',['website','official_website']],['LinkedIn','company_profiles',['linkedin','linkedin_profile']],['Facebook','company_profiles',['facebook','facebook_profile']],['Instagram','company_profiles',['instagram','instagram_profile']],['Open job ads','hiring',['active_job_posting_count']],['Customer rating','ratings_reviews',['customer_rating']],['Latest activity','public_activity',['latest_activity','latest_activity_date']]];

const isObj=(v:Value):v is {[key:string]:Value}=>!!v&&typeof v==='object'&&!Array.isArray(v);
const num=(v:Value)=>typeof v==='number'?v:typeof v==='string'&&v.trim()!==''&&!isNaN(Number(v))?Number(v):undefined;

export function money(amount:number,currency='NOK'){const a=Math.abs(amount);const s=a>=1e9?(amount/1e9).toLocaleString('en-GB',{maximumFractionDigits:1})+' bn':a>=1e6?(amount/1e6).toLocaleString('en-GB',{maximumFractionDigits:1})+' m':amount.toLocaleString('en-GB',{maximumFractionDigits:0});return `${currency} ${s}`}

export function niceDate(iso:string){const m=/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso);if(!m)return iso;const d=new Date(Date.UTC(+m[1],+m[2]-1,+m[3]));const day=d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});return m[4]?`${day}, ${m[4]}:${m[5]} UTC`:day}

/** A short human reading of a claim value, or undefined when the generic view is better. */
export function formatValue(field:string,value:Value):string|undefined{
  if(value===null||value===undefined)return undefined;
  if(field==='legal_form'&&isObj(value))return `${value.label??''}${value.code?` (${value.code})`:''}`.trim();
  if(field==='industry'&&Array.isArray(value))return value.map(v=>isObj(v)?`${v.code??''} ${v.label??''}`.trim():String(v)).join('; ');
  if((field==='full_time_equivalents'||field==='average_employees')&&isObj(value)){const n=num(value.value);return n===undefined?undefined:`${n.toLocaleString('en-GB')} FTE${value.year?` (${value.year})`:''}`}
  if(field==='customer_rating'&&isObj(value)){const v=num(value.value),c=num(value.count);return v===undefined?undefined:`${v.toFixed(1)} / ${value.best??5}${c!==undefined?` · ${c} review${c===1?'':'s'}`:''}`}
  if(field==='revenue_change_yoy'&&isObj(value)){const p=num(value.change_pct);return p===undefined?undefined:`${p>0?'+':p<0?'−':''}${Math.abs(p).toLocaleString('en-GB',{maximumFractionDigits:1})} % (${value.from_year}→${value.to_year})`}
  if((field==='accountant'||field==='auditor')&&isObj(value))return String(value.name??'');
  if(isObj(value)&&typeof value.amount==='number')return money(value.amount,String(value.currency??'NOK'));
  if(typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value))return niceDate(value);
  if(field==='workplace_municipalities'&&Array.isArray(value))return value.join(', ');
  if(field==='filed_account_years'&&Array.isArray(value)&&value.length)return `${value.length} years (${value[value.length-1]}–${value[0]})`;
  if(field==='verification_signals'&&Array.isArray(value))return value.map(v=>String(v).replace(/_/g,' ')).join(' · ');
  return undefined;
}

/** Plain text of a value for comparing and searching. */
export function plain(field:string,value:Value):string{const f=formatValue(field,value);if(f!==undefined)return f;if(value===null||value===undefined)return '';if(typeof value==='object')return JSON.stringify(value);return String(value)}

const CLASS_LABELS:Record<string,string>={official_registry:'Official register record',official_roles:'Official roles register',official_subunits:'Official register: workplaces',official_annual_accounts:'Official annual accounts',official_annual_account_copies:'Official list of filed accounts',official_annual_account_copy:'Filed annual report (PDF)',company_owned_website:"Company's own website",official_registry_bulk:'Official register (daily bulk file)',official_public_api_nav:'Public job ad (NAV, official API)',third_party_directory_fagfolkguiden:'Business directory (third party)',open_knowledge_base_wikidata:'Open knowledge base'};

/** Who published a source and what kind of source it is. */
export function describeSource(e:Evidence):{publisher:string;kind:string;human?:string}{
  let host='';let path='';try{const u=new URL(e.source_url);host=u.hostname.replace(/^www\./,'');path=u.pathname}catch{}
  const kind=CLASS_LABELS[e.source_class]||human(e.source_class);
  const org=/(\d{9})/.exec(e.source_url)?.[1];
  if(host==='data.brreg.no'&&path.startsWith('/regnskapsregisteret'))return {publisher:'Brønnøysund Register Centre · Register of Company Accounts',kind,human:org?`https://virksomhet.brreg.no/nb/oppslag/enheter/${org}`:undefined};
  if(host==='data.brreg.no')return {publisher:'Brønnøysund Register Centre · Central Coordinating Register',kind,human:org?`https://virksomhet.brreg.no/nb/oppslag/enheter/${org}`:undefined};
  if(host.endsWith('nav.no'))return {publisher:'NAV · public job ads',kind};
  if(host.endsWith('wikidata.org'))return {publisher:'Wikidata',kind};
  if(host.endsWith('fagfolkguiden.no'))return {publisher:'Fagfolkguiden',kind};
  return {publisher:host||e.source_url,kind};
}

/** How much the snapshot found for a company (families with available facts). */
export const coverageCount=(c:Company)=>families.filter(f=>status(c,f).availability==='available').length;
