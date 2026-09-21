/**
 * An image that needs the caller's bearer token.
 *
 * Browsers attach no Authorization header to `<img src>`, so every page-image
 * route rendered that way broke the moment authentication was required. This
 * hook fetches with the header, hands back an object URL, and revokes it when
 * the URL changes or the component unmounts. `failed` is true when the server
 * refused or the network failed, so a caller can say so instead of showing the
 * browser's broken-image glyph beside a citation it just asked the reader to
 * trust.
 */
import { useEffect, useState } from "react";

import { fetchImageObjectUrl } from "../api/client";

export interface AuthedImage {
  src: string | null;
  loading: boolean;
  failed: boolean;
  answerLocated: boolean | null;
}

export function useAuthedImage(url: string | null): AuthedImage {
  const [state, setState] = useState<AuthedImage>({
    src: null,
    loading: url !== null,
    failed: false,
    answerLocated: null,
  });

  useEffect(() => {
    if (url === null) {
      setState({ src: null, loading: false, failed: false, answerLocated: null });
      return;
    }
    let cancelled = false;
    let created: string | null = null;
    setState({ src: null, loading: true, failed: false, answerLocated: null });
    void fetchImageObjectUrl(url).then((result) => {
      if (cancelled) {
        if (result.url) URL.revokeObjectURL(result.url);
        return;
      }
      created = result.url;
      setState({
        src: result.url,
        loading: false,
        failed: result.url === null,
        answerLocated: result.answerLocated,
      });
    });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [url]);

  return state;
}
