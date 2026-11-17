import { Layout } from '../common/Layout';
import { RAGChatPanel } from '../common/RAGChatPanel';

export function Chat() {
  return (
    <Layout contentContainerClassName="h-[calc(100vh-90px)] max-w-none px-0 py-0">
      <div className="h-full">
        <RAGChatPanel />
      </div>
    </Layout>
  );
}
