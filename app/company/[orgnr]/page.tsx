import type {Metadata} from 'next';
import {notFound} from 'next/navigation';
import {DataApp} from '@/components/signalpost';
import {loadCompany, loadDataset} from '@/lib/data-server';

export function generateStaticParams() {
  return loadDataset().companies.map(c => ({orgnr: c.organisation_number}));
}

export async function generateMetadata({params}: {params: Promise<{orgnr: string}>}): Promise<Metadata> {
  const c = loadCompany((await params).orgnr);
  if (!c) return {title: 'Company not found'};
  const description = (c.synthesis.sentences[0]?.text || c.summary || `Sourced profile of ${c.name}.`).slice(0, 200);
  return {
    title: `${c.name} (${c.organisation_number})`,
    description,
    openGraph: {title: `${c.name} · Signalpost`, description, type: 'article'},
    twitter: {card: 'summary', title: `${c.name} · Signalpost`, description},
  };
}

export default async function Page({params}: {params: Promise<{orgnr: string}>}) {
  const data = loadDataset();
  const company = loadCompany((await params).orgnr);
  if (!company) notFound();
  return <DataApp view="company" meta={data.meta} company={company} total={data.companies.length}/>;
}
