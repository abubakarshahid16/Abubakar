/**
 * OWNER: builder B. Who is signed in, for "signed by <name>" in the sign
 * preview. The existing `/auth/me` read; null while not known or when sign-in
 * is off (never a made-up name).
 *
 * v2.1 round 2: `useSigner` also says whether sign-in is off (the server
 * answers `required: false`), so the preview can say "signer not known
 * (sign-in is off)" instead of promising a name it does not have.
 */
import { useEffect, useState } from "react";

import { auth } from "../../../../api/client";

export interface Signer {
  name: string | null;
  /** True when sign-in is off; null while not known. */
  signInOff: boolean | null;
}

export function useSigner(): Signer {
  const [signer, setSigner] = useState<Signer>({ name: null, signInOff: null });
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await auth.me();
        if (!live || !r.ok) return;
        const user = r.data.user;
        setSigner({
          name: user ? user.display_name || user.email || null : null,
          signInOff: r.data.required === false,
        });
      } catch {
        /* not known: the preview says nothing about who signs */
      }
    })();
    return () => { live = false; };
  }, []);
  return signer;
}

export function useSignerName(): string | null {
  return useSigner().name;
}
