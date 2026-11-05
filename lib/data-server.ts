import {readFileSync} from 'node:fs';
import path from 'node:path';
import {toIndexEntry, type Dataset, type IndexEntry} from '@/lib/signalpost';

let cached: Dataset | undefined;

/** The agent's web dataset, read once at build/render time on the server. */
export function loadDataset(): Dataset {
  if (!cached) cached = JSON.parse(readFileSync(path.join(process.cwd(), 'public/data/profiles.json'), 'utf8')) as Dataset;
  return cached;
}

export function loadIndex(): IndexEntry[] {
  return loadDataset().companies.map(toIndexEntry);
}

export function loadCompany(org: string) {
  return loadDataset().companies.find(c => c.organisation_number === org);
}
