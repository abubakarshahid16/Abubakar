/**
 * OWNER: builder B. Who is signed in, for "signed by <name>" in the sign
 * preview. The existing `/auth/me` read; null while not known or when sign-in
 * is off (never a made-up name).
 */
import { useEffect, useState } from "react";

import { auth } from "../../../../api/client";

export function useSignerName(): string | null {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await auth.me();
        if (live && r.ok && r.data.user) setName(r.data.user.display_name || r.data.user.email || null);
      } catch {
        /* not known: the preview says nothing about who signs */
      }
    })();
    return () => { live = false; };
  }, []);
  return name;
}
