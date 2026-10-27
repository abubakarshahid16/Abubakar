"""Order 252 (PR 1372): native crash stacks go to a file; PyMuPDF reader sites share one lock; the
vector cache never shares a temporary file."""

from __future__ import annotations

from ._base import APP, Mutation

_SITES = "tests/test_252_pdf_guard_sites.py"
_LOG = "tests/test_252_crash_log.py"
_VC = "tests/test_vectorcache.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1372-01",
        phase=1372,
        description="the table finder opens PDFs without the PyMuPDF lock again",
        path=APP / "tables.py",
        anchor="        with pdf_guard.held(), pymupdf.open(stored_path) as doc:\n",
        replacement="        with pymupdf.open(stored_path) as doc:\n",
        target=_SITES,
        keyword="tables",
        tags=_TAGS,
    ),
    Mutation(
        id="M1372-02",
        phase=1372,
        description="the PDF condition check opens PDFs without the PyMuPDF lock again",
        path=APP / "datasheets.py",
        anchor="        with pdf_guard.held(), pymupdf.open(stored_path) as doc:\n            if doc.needs_pass:\n",
        replacement="        with pymupdf.open(stored_path) as doc:\n            if doc.needs_pass:\n",
        target=_SITES,
        keyword="pdf_condition",
        tags=_TAGS,
    ),
    Mutation(
        id="M1372-03",
        phase=1372,
        description="the vision reader renders its page without the PyMuPDF lock",
        path=APP / "vision_reader.py",
        anchor="        with pdf_guard.held():\n            packet = packet_for(render(page), page_no)\n",
        replacement="        if True:\n            packet = packet_for(render(page), page_no)\n",
        target=_SITES,
        keyword="vision_reader_takes_the_lock",
        tags=_TAGS,
    ),
    Mutation(
        id="M1372-04",
        phase=1372,
        description="the server no longer turns crash stacks on at start",
        path=APP.parent / "run.py",
        anchor='    crash_log.enable(settings.data_dir / "logs" / "native-crash.log")\n',
        replacement="    pass\n",
        target=_LOG,
        keyword="server_start_turns_it_on",
        tags=_TAGS,
    ),
    Mutation(
        id="M1372-05",
        phase=1372,
        description="the vector cache writes its temporary file under a name every process shares",
        path=APP / "vectorcache.py",
        anchor='    tmp = data_path.with_suffix(f".f32.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")\n',
        replacement='    tmp = data_path.with_suffix(".f32.tmp")\n',
        target=_VC,
        keyword="private_temporary_name",
        tags=_TAGS,
    ),
    Mutation(
        id="M1372-06",
        phase=1372,
        description="the vector cache sweep removes a temporary file another process is writing",
        path=APP / "vectorcache.py",
        anchor="            if (temporary and young) or (path.name.startswith(keep) and not temporary):\n",
        replacement="            if path.name.startswith(keep) and not temporary:\n",
        target=_VC,
        keyword="fresh_temporary_file",
        tags=_TAGS,
    ),
)
