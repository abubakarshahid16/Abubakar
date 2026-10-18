/** Section 1: the pages, from `page_coverage` (with its `reading` record and
 *  `pages_ai_not_read`) and `requirement_split.reader`. */
import type { ReviewRunSummary } from "../../../types/api";
import { pageList } from "../reviewFormat";
import { NOT_RECORDED, pageFacts, pagesMeaning, readerOf } from "./howData";
import { Fact, FactList, HowSection, type HowSectionMeta } from "./HowPrimitives";

export const PAGES_META: HowSectionMeta = {
  id: "pages", number: 1, title: "Pages",
  explains: "How many pages the document has and how many of them the review actually read; a page it did not read may still hold the value it was looking for.",
};

export function PagesSection({ run }: { run: ReviewRunSummary }) {
  const p = pageFacts(run);
  const reader = readerOf(run);
  const timedOut = p.timedOut.value;
  const notRead = p.notRead.value;
  const aiNotRead = p.aiNotRead.value;
  return (
    <HowSection meta={PAGES_META}>
      <FactList label="Pages">
        <Fact label="Pages in the document" fact={p.total} testId="pages-total" />
        <Fact label="Read into fields by the code reader" fact={p.readByCode} testId="pages-code"
          detail={p.readByCodePages.length ? `(pages ${pageList(p.readByCodePages)})` : undefined} />
        {p.aiOff ? (
          <Fact label="Read by the AI reader" testId="pages-ai"
            fact={{ value: "AI reader off", source: "requirement_split.reader.engine" }}
            detail={`- not asked; pages given to the readers: ${p.aiPages.value ?? NOT_RECORDED} (requirement_split.reader.pages)`} />
        ) : (
          <Fact label="Read by the AI reader" fact={p.readByAi} testId="pages-ai"
            detail={p.aiPages.value !== null ? `of ${p.aiPages.value} (requirement_split.reader.pages)` : undefined} />
        )}
        <Fact label="Not read by the AI reader" testId="pages-ai-not-read"
          fact={{ value: aiNotRead === null ? null : aiNotRead.length, source: p.aiNotRead.source }}
          detail={aiNotRead && aiNotRead.length ? `(pages ${pageList(aiNotRead)})` : undefined} />
        <Fact label="AI reader timed out on" testId="pages-timed-out"
          fact={{ value: timedOut === null ? null : timedOut.length, source: p.timedOut.source }}
          detail={timedOut && timedOut.length ? `(pages ${pageList(timedOut)})` : undefined} />
        <Fact label="Not read into fields" testId="pages-not-read"
          fact={{ value: notRead === null ? null : notRead.length, source: p.notRead.source }}
          detail={notRead && notRead.length ? `(pages ${pageList(notRead)})` : undefined} />
        <Fact label="Scanned pages without OCR" fact={p.withoutOcr} testId="pages-no-ocr"
          detail={p.ocrDone.value !== null ? `(OCR done on ${p.ocrDone.value}, from ${p.ocrDone.source})` : undefined} />
        <Fact label="Reading status" testId="pages-reading"
          fact={{ value: p.reading ? p.reading.status : null, source: "page_coverage.reading.status" }}
          detail={p.reading && p.reading.incomplete_pages.length
            ? `(pages ${pageList(p.reading.incomplete_pages)} not read in full, from page_coverage.reading.incomplete_pages)` : undefined} />
      </FactList>
      {notRead && notRead.length > 0 && (
        <ul data-testid="pages-not-read-reasons" className="list-disc ps-5 text-sm text-slateish-300">
          {notRead.map((page) => (
            <li key={page}>Page {page}: {p.notReadReasons[String(page)] ?? "no reason recorded"}</li>
          ))}
        </ul>
      )}
      {aiNotRead && aiNotRead.length > 0 && (
        <ul data-testid="pages-ai-not-read-reasons" className="list-disc ps-5 text-sm text-slateish-300">
          {aiNotRead.map((page) => (
            <li key={page}>Page {page}: {p.aiNotReadReasons[String(page)] ?? "no reason recorded"}</li>
          ))}
        </ul>
      )}
      {reader && reader.engine !== "off" && reader.code_only && Object.keys(reader.code_only).length > 0 && (
        <p className="text-sm text-slateish-300">
          Left to the code readers by the AI reader (from requirement_split.reader.code_only):{" "}
          {Object.entries(reader.code_only).map(([page, why]) => `page ${page} (${why})`).join("; ")}.
        </p>
      )}
      <p data-testid="pages-meaning" className="text-sm text-slateish-200">
        <span className="font-medium">What this means:</span> {pagesMeaning(run)}
      </p>
    </HowSection>
  );
}
