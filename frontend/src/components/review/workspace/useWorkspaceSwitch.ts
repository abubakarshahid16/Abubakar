/**
 * OWNER: builder A. The "Try new design" switch.
 * On = routing.WORKSPACE_IS_DEFAULT || this browser opted in. Storage is
 * wrapped in try/catch: a private window throws on read and on write.
 */
import { useCallback, useState } from "react";

import { WORKSPACE_IS_DEFAULT } from "../../../routing";
import { WORKSPACE_OPT_IN_KEY } from "./workspaceRoute";

export function readWorkspaceOptIn(): boolean {
  try {
    return localStorage.getItem(WORKSPACE_OPT_IN_KEY) === "on";
  } catch {
    return false;
  }
}

export function writeWorkspaceOptIn(on: boolean): void {
  try {
    if (on) localStorage.setItem(WORKSPACE_OPT_IN_KEY, "on");
    else localStorage.removeItem(WORKSPACE_OPT_IN_KEY);
  } catch {
    /* storage unavailable: the choice lasts this page only */
  }
}

export function useWorkspaceSwitch(isDefault: boolean = WORKSPACE_IS_DEFAULT): {
  on: boolean; optedIn: boolean; setOptIn: (on: boolean) => void;
} {
  const [optedIn, setOptedIn] = useState(readWorkspaceOptIn);
  const setOptIn = useCallback((next: boolean) => { writeWorkspaceOptIn(next); setOptedIn(next); }, []);
  return { on: isDefault || optedIn, optedIn, setOptIn };
}
