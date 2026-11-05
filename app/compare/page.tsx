import type {Metadata} from 'next';
import {DataApp} from '@/components/signalpost';
import {loadDataset, loadIndex} from '@/lib/data-server';

export const metadata: Metadata = {
  title: 'Compare companies',
  description: 'Compare Norwegian companies side by side, with the source behind every answer.',
  openGraph: {title: 'Compare companies | Signalpost', description: 'Compare Norwegian companies side by side, with the source behind every answer.'},
};

export default function Page() {
  return <DataApp view="compare" meta={loadDataset().meta} index={loadIndex()}/>;
}
