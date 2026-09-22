"""Generate synthetic PDFs for tests and manual checks. No client data."""
import sys
import pymupdf

def make(path: str, pages: int = 5) -> None:
    doc = pymupdf.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 96), f"Section {i}.0  Synthetic Equipment Notes", fontsize=14)
        page.insert_text((72, 130),
            f"Pump P-{100+i}A shall be inspected at intervals not exceeding {1000*i} operating hours.",
            fontsize=10)
        page.insert_text((72, 150),
            f"Vibration limits per API 610 shall not exceed {2.0 + i*0.5:.1f} mm/s RMS.",
            fontsize=10)
        page.insert_text((72, 760), f"Page {i}", fontsize=8)
    doc.save(path)
    doc.close()
    print(f"wrote {path} ({pages} pages)")

if __name__ == "__main__":
    make(sys.argv[1] if len(sys.argv) > 1 else "synthetic.pdf",
         int(sys.argv[2]) if len(sys.argv) > 2 else 5)
