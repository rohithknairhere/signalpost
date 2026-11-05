import {DataApp} from '@/components/signalpost';
import {loadDataset, loadIndex} from '@/lib/data-server';

export default function Page() {
  return <DataApp view="home" meta={loadDataset().meta} index={loadIndex()}/>;
}
