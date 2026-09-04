import type { Connection } from "../components/Shell";
import { EmptyState } from "../components/states";

export function DocumentsView({
  connection,
}: {
  connection: Connection;
  onRetryConnection: () => void;
}) {
  return (
    <div>
      <h1 className="text-xl font-semibold text-slateish-200">Documents</h1>
      <p className="mt-1 text-sm text-slateish-400">
        Upload, inspect and verify what the system can actually search.
      </p>
      <div className="mt-6">
        {connection.state === "online" ? (
          <EmptyState title="Document list lands in B2." />
        ) : null}
      </div>
    </div>
  );
}
