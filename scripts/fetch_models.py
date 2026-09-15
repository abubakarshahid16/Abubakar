"""Stage the local models.

Model weights never enter Git (see .gitignore), so a fresh machine - or a CI
runner - has to fetch them. This is the one script that reaches the network,
and it downloads MODELS only. No client document, chunk, question or answer
ever leaves the machine; that rule is unaffected by this.

    python scripts/fetch_models.py            # all, skipping what is present
    python scripts/fetch_models.py --force    # re-download

Exits non-zero if anything the application requires is still missing
afterwards, so CI fails loudly rather than running a suite that silently
skips half its assertions.

Three model families are staged: the e5-small embedder, the cross-encoder
reranker, and the OCR detector/recogniser/classifier.

The OCR weights are here for a specific reason. RapidOCR resolves an unset
`model_path` by downloading from modelscope.cn on FIRST CONSTRUCTION, into
site-packages. That makes a fresh or air-gapped machine fail at the first
recognition rather than at install, which is the worst possible moment, and
it puts a 6.9 MB dependency on a network this deployment does not have. They
are 10 MB in total; there is no reason not to vendor them beside the other
two, and `app.config` points RapidOCR at these paths explicitly so the
download path is never reached.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "backend" / "models"

#: (destination, repo, [files]) - only the files the application actually
#: opens. The full snapshot carries several unused ONNX variants and the
#: fp32 weights, which together are most of a gigabyte.
TARGETS = [
    (
        "e5-small",
        "intfloat/multilingual-e5-small",
        [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "sentencepiece.bpe.model",
        ],
    ),
    (
        "e5-small/onnx",
        "intfloat/multilingual-e5-small",
        ["onnx/model_qint8_avx512_vnni.onnx"],
    ),
    (
        "reranker",
        "Xenova/ms-marco-MiniLM-L-6-v2",
        [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
        ],
    ),
    (
        "reranker/onnx",
        "Xenova/ms-marco-MiniLM-L-6-v2",
        ["onnx/model_quantized.onnx"],
    ),
]

#: OCR weights. Not on the Hub, so these are plain URLs rather than
#: hf_hub_download targets, and each is pinned by SHA-256 - the transport is
#: the only thing standing between a download and an ONNX session, and an
#: unverified 4 MB blob feeding a model is not something to take on trust.
#:
#: The RapidOCR release tag is pinned in the URL (v3.9.2). An unpinned
#: "latest" would let the recogniser change under a passing test suite.
#:
#: BOTH candidate configurations are staged, because the engine choice is
#: open pending one question: whether the client documents contain Arabic.
#:   - multilingual: PP-OCRv6 det_tiny + PP-OCRv6 rec_tiny
#:   - English-only: PP-OCRv6 det_tiny + PP-OCRv5 en rec_mobile
#: The detector and the direction classifier are shared by both, so staging
#: both costs one extra 7.9 MB recogniser.
OCR_BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx"
OCR_TARGETS = [
    (
        "ocr/PP-OCRv6_det_tiny.onnx",
        f"{OCR_BASE}/PP-OCRv6/det/PP-OCRv6_det_tiny.onnx",
        "f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5",
    ),
    (
        "ocr/PP-OCRv6_rec_tiny.onnx",
        f"{OCR_BASE}/PP-OCRv6/rec/PP-OCRv6_rec_tiny.onnx",
        "e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b",
    ),
    (
        "ocr/en_PP-OCRv5_rec_mobile.onnx",
        f"{OCR_BASE}/PP-OCRv5/rec/en_PP-OCRv5_rec_mobile.onnx",
        "c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8",
    ),
    (
        "ocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        f"{OCR_BASE}/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    ),
]

#: What must exist for the application to work. Checked after downloading, so
#: a partial fetch is a failure rather than a surprise at runtime.
REQUIRED = [
    "e5-small/tokenizer.json",
    "e5-small/onnx/model_qint8_avx512_vnni.onnx",
    "reranker/tokenizer.json",
    "reranker/onnx/model_quantized.onnx",
    # OCR. Listed here so --verify-only fails on a machine that would
    # otherwise reach modelscope.cn at the first recognition instead.
    "ocr/PP-OCRv6_det_tiny.onnx",
    "ocr/PP-OCRv6_rec_tiny.onnx",
    "ocr/en_PP-OCRv5_rec_mobile.onnx",
    "ocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
]

#: Checked by --verify-only as well as after a fetch. A file of the right name
#: and the wrong content is a worse failure than a missing one, because it
#: runs.
CHECKSUMS = {rel: sha for rel, _url, sha in OCR_TARGETS}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch_ocr(force: bool) -> None:
    for rel, url, expected in OCR_TARGETS:
        target = MODELS / rel
        if target.exists() and not force:
            print(f"  present  {rel}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"  fetching {rel}")
        # Written to a .part first so an interrupted download cannot leave a
        # truncated file that later passes an exists() check.
        part = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url, timeout=120) as resp:
            part.write_bytes(resp.read())
        got = sha256_of(part)
        if got != expected:
            part.unlink(missing_ok=True)
            raise SystemExit(
                f"\nCHECKSUM MISMATCH for {rel}\n"
                f"  expected {expected}\n  got      {got}\n"
                "Refusing to stage it. This is either a corrupted transfer or "
                "a changed upstream artefact; neither should reach an ONNX "
                "session unexamined."
            )
        part.replace(target)


def fetch(force: bool) -> None:
    from huggingface_hub import hf_hub_download

    for dest, repo, files in TARGETS:
        # The repo layout is mirrored under backend/models/<dir>. The
        # destination root comes from the target entry rather than being
        # inferred from the repo name, because the application opens these by
        # path and a guess that drifts is a runtime error.
        root = MODELS / dest.split("/")[0]
        for filename in files:
            target = root / filename
            if target.exists() and not force:
                print(f"  present  {target.relative_to(MODELS)}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"  fetching {repo}/{filename}")
            path = hf_hub_download(repo_id=repo, filename=filename)
            target.write_bytes(Path(path).read_bytes())


def verify() -> tuple[list[str], list[str]]:
    """Missing files, and staged files whose content is not what we pinned."""
    missing = [rel for rel in REQUIRED if not (MODELS / rel).exists()]
    corrupt = [
        rel
        for rel, expected in CHECKSUMS.items()
        if (MODELS / rel).exists() and sha256_of(MODELS / rel) != expected
    ]
    return missing, corrupt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-download everything")
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="check what is staged without downloading",
    )
    args = ap.parse_args()

    MODELS.mkdir(parents=True, exist_ok=True)
    if not args.verify_only:
        fetch(args.force)
        fetch_ocr(args.force)

    missing, corrupt = verify()
    if missing:
        print("\nMISSING after fetch:")
        for rel in missing:
            print(f"  {rel}")
        print(
            "\nThe application cannot run without these. A test suite run "
            "against a partial staging silently skips its assertions rather "
            "than failing, which is worse than not running it."
        )
    if corrupt:
        print("\nWRONG CONTENT (SHA-256 does not match the pinned value):")
        for rel in corrupt:
            print(f"  {rel}")
        print(
            "\nA file of the right name and the wrong content is worse than a "
            "missing one, because it runs. Delete it and re-fetch with --force."
        )
    if missing or corrupt:
        return 1

    total = sum(f.stat().st_size for f in MODELS.rglob("*") if f.is_file())
    print(f"\nall required model files present ({total / 1e6:.0f} MB staged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
