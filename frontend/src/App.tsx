import { useState } from "react";

import { Shell, useConnection, type ViewId } from "./components/Shell";
import { DisconnectedState, NotBuiltYet } from "./components/states";
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
      {view === "chat" && <NotBuiltYet name="Chat" />}
      {view === "ingestion" && <NotBuiltYet name="Ingestion" />}
      {view === "dashboard" && <NotBuiltYet name="Dashboard" />}
    </Shell>
  );
}
