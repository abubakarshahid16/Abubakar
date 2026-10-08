"""W7 "the Documents page makes one request, and says what is true about OCR":
each entry deletes one fix; backend/tests/test_w7_documents_list_classification.py
and the frontend tests must notice."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_B = "tests/test_w7_documents_list_classification.py"
_TAG = ("w7", "honesty")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M2901", phase=2901,
             description="the document list no longer carries the classification",
             path=APP / "main.py",
             anchor='        doc["classification"] = {\n',
             replacement='        doc["_unused"] = {\n',
             target=_B, keyword="list_carries or never_classified or only_the_documents", tags=_TAG),
    Mutation(id="M2902", phase=2902,
             description="the classification batch makes one query per document again",
             path=APP / "classification.py",
             anchor="    ids = list(dict.fromkeys(document_ids))\n    out: dict[str, dict] = {}\n    conn = connect()\n    for start in range(0, len(ids), 500):",
             replacement="    ids = list(dict.fromkeys(document_ids))\n    out: dict[str, dict] = {}\n    conn = connect()\n    for start in range(0, len(ids), 1):",
             target=_B, keyword="fixed_number_of_classification_queries", tags=_TAG),
    Mutation(id="M2903", phase=2903,
             description="a never-classified document gets no empty record on the list",
             path=APP / "main.py",
             anchor="(classifications.get(row[\"id\"]) or classification_mod.empty_record(row[\"id\"]))",
             replacement="(classifications.get(row[\"id\"]) or {})",
             target=_B, keyword="never_classified", tags=_TAG),
    Mutation(id="M2904", phase=2904, runner="vitest",
             description="the Documents page asks for a classification per document again",
             path=FRONTEND_SRC / "components" / "classification" / "useDocumentClassifications.ts",
             anchor="      if (doc.classification) out[doc.id] = doc.classification;\n",
             replacement="      void fetch(`/api/documents/${doc.id}/classification`);\n",
             target="src/views/DocumentsView.test.tsx", keyword="one request for the documents page", tags=_TAG),
    Mutation(id="M2905", phase=2905, runner="vitest",
             description="a finished document waiting for OCR says it is reading scanned pages again",
             path=FRONTEND_SRC / "components" / "documentStatus.ts",
             anchor='          label: `finished, ${nf.format(waiting)} page${waiting === 1 ? "" : "s"} waiting for OCR`,\n',
             replacement='          label: "reading scanned pages",\n',
             target="src/components/documentStatus.test.ts", keyword="partially-processed", tags=_TAG),
)
