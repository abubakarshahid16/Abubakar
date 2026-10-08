/**
 * Server-Sent Events, read from a `fetch` body.
 *
 * `EventSource` cannot be used: it only GETs and cannot send the bearer
 * header, and the answer route is a POST that must carry both the question
 * and the token (the token never goes into a URL - CLAUDE.md rule 2). So the
 * stream is read as bytes and cut into events here.
 *
 * Only what the chat stream sends is understood: `event:` and `data:` lines,
 * an event ending at a blank line. A `data:` that is not JSON is dropped
 * rather than guessed at - every event this backend sends is JSON.
 */
export interface SseEvent {
  event: string;
  data: unknown;
}

export class SseParser {
  private buffer = "";

  /** Feed a chunk of text; get back every event it completed. */
  push(chunk: string): SseEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const out: SseEvent[] = [];
    let end = this.buffer.indexOf("\n\n");
    while (end !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const parsed = parseBlock(block);
      if (parsed) out.push(parsed);
      end = this.buffer.indexOf("\n\n");
    }
    return out;
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // a comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}
