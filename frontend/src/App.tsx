import { useState } from "react";

import { Shell, useConnection, type ViewId } from "./components/Shell";
import { DisconnectedState, NotBuiltYet } from "./components/states";
import { ChatView } from "./views/ChatView";
import { DashboardView } from "./views/DashboardView";
import { DocumentsView } from "./views/DocumentsView";

export default function App() {
  const [view, setView] = useState<ViewId>("documents");
  const { connection, recheck } = useConnection();

  return (
    <Shell view={view} onNavigate={setView} connection={connection}>
      {connection.state === "offline" && (
        <div className="mb-6">
          <DisconnectedState onRetry={recheck} />
        </div>
      )}

      {view === "documents" && (
        <DocumentsView connection={connection} onRetryConnection={recheck} />
      )}
      {view === "chat" && (
        <ChatView connection={connection} onRetryConnection={recheck} />
      )}
      {view === "ingestion" && <NotBuiltYet name="Ingestion" />}
      {view === "dashboard" && (
        <DashboardView connection={connection} onRetryConnection={recheck} />
      )}
    </Shell>
  );
}
