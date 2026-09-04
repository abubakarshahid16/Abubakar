import { useState } from "react";

import { Shell, useConnection, type ViewId } from "./components/Shell";
import { DisconnectedState } from "./components/states";
import { ChatView } from "./views/ChatView";
import { DashboardView } from "./views/DashboardView";
import { DocumentsView } from "./views/DocumentsView";
import { IngestionView } from "./views/IngestionView";

export default function App() {
  const [view, setView] = useState<ViewId>("documents");
  const { connection, recheck } = useConnection();

  return (
    <Shell view={view} onNavigate={setView} connection={connection}>
      {/* ONE connection-level error at a time. With the backend down this
          rendered its banner AND let the view render its own failed-request
          card, so an amber "backend is not running" and a red "HTTP 502"
          appeared together. The shell owns this condition; the view is not
          rendered at all while it holds. */}
      {connection.state === "offline" ? (
        <DisconnectedState onRetry={recheck} />
      ) : (
        <>
      {view === "documents" && (
        <DocumentsView connection={connection} onRetryConnection={recheck} />
      )}
      {view === "chat" && (
        <ChatView connection={connection} onRetryConnection={recheck} />
      )}
      {view === "ingestion" && (
        <IngestionView connection={connection} onRetryConnection={recheck} />
      )}
      {view === "dashboard" && (
        <DashboardView connection={connection} onRetryConnection={recheck} />
      )}
        </>
      )}
    </Shell>
  );
}
