import {DataApp} from '@/components/signalpost';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import type {Dataset} from '@/lib/signalpost';
export async function generateStaticParams(){const d:Dataset=JSON.parse(await readFile(path.join(process.cwd(),'public/data/profiles.json'),'utf8'));return d.companies.map(c=>({orgnr:c.organisation_number}))}
export default async function Page({params}:{params:Promise<{orgnr:string}>}){return <DataApp view="company" org={(await params).orgnr}/>}
