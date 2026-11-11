import { useEffect, useState } from "react";

import { agentSwitch } from "../../../api/agentReview";
import type { AgentStatus } from "../../../types/api";

/** The one switch, read once. `null` while unknown or while the switch is
 *  off: both draw nothing of the feature. */
export function useAgentSwitch(): AgentStatus | null {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  useEffect(() => {
    let live = true;
    void agentSwitch().then((s) => { if (live) setStatus(s.state === "on" ? s.status : null); });
    return () => { live = false; };
  }, []);
  return status;
}
