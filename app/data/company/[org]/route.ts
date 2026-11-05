import {loadCompany, loadDataset} from '@/lib/data-server';

export const dynamic = 'force-static';

export function generateStaticParams() {
  return loadDataset().companies.map(c => ({org: c.organisation_number}));
}

/** One company's full profile (claims and evidence), used by the compare page. */
export async function GET(_request: Request, {params}: {params: Promise<{org: string}>}) {
  const company = loadCompany((await params).org);
  if (!company) return Response.json({error: 'not found'}, {status: 404});
  return Response.json(company);
}
