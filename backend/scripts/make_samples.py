"""Regenerate the fictional sample documents in ``backend/samples/`` (no extra dependencies).

    uv run python scripts/make_samples.py

PDFs are written by hand (standard Helvetica, English only); PNGs are rendered from those PDFs
with macOS ``sips`` (so this part needs macOS). Everything is fictional and marked
"SAMPLE - FICTIONAL". ``*.fake.pdf`` files carry a ``FAKE-DOC:`` line for the offline provider.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "samples"

Line = tuple[int, int, str]  # (font size, y, text)


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines: list[Line], marker: dict[str, object] | None = None) -> bytes:
    """A one-page A5-ish PDF with standard Helvetica text; optional FAKE-DOC comment line."""
    ops = ["BT"]
    for size, y, text in lines:
        ops.append(f"/F1 {size} Tf 1 0 0 1 36 {y} Tm ({_esc(text)}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 595] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    if marker is not None:
        out += b"% FAKE-DOC: " + json.dumps(marker).encode("ascii") + b"\n"
    offsets = []
    for number, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


SICK_LINES: list[Line] = [
    (11, 560, "SAMPLE - FICTIONAL  (not a real medical document)"),
    (18, 520, "Sample Family Clinic (fictional)"),
    (10, 504, "1 Example Road, Sample District, Hong Kong  |  Tel: 0000 0000"),
    (16, 460, "MEDICAL CERTIFICATE"),
    (11, 420, "Date of issue: 24 September 2026"),
    (11, 395, "This is to certify that Amy Lau (fictional patient)"),
    (11, 378, "attended this clinic on 24 September 2026 and is unfit for work"),
    (11, 361, "from 24 September 2026 to 25 September 2026 (both dates inclusive),"),
    (11, 344, "a total of 2 days of sick leave."),
    (11, 300, "Diagnosis: acute upper respiratory tract infection"),
    (11, 200, "Dr. Sample Doctor (fictional)   Reg. No. 000000"),
    (9, 60, "SAMPLE - FICTIONAL. Generated for software testing only."),
]


def receipt_lines(with_date: bool) -> list[Line]:
    lines: list[Line] = [
        (11, 560, "SAMPLE - FICTIONAL  (not a real receipt)"),
        (18, 520, "Sample Noodle House (fictional)"),
        (10, 504, "1 Example Street, Sample District, Hong Kong"),
        (12, 470, "RECEIPT No. 000123"),
    ]
    if with_date:
        lines.append((11, 450, "Date: 20 September 2026   Time: 12:41"))
    lines += [
        (11, 410, "Beef brisket noodles          1 x   48.00"),
        (11, 394, "Iced lemon tea                 1 x   28.00"),
        (11, 360, "Subtotal                                   HK$ 76.00"),
        (11, 344, "Service charge 10%                     HK$  7.60"),
        (14, 310, "TOTAL PAID                              HK$ 83.60"),
        (11, 285, "Payment: cash"),
        (9, 60, "SAMPLE - FICTIONAL. Generated for software testing only."),
    ]
    return lines


def sips(args: list[str]) -> None:
    subprocess.run(["sips", *args], check=True, capture_output=True)


def main() -> None:
    if shutil.which("sips") is None:
        raise SystemExit("sips (macOS) is required to render the PNG samples")
    OUT.mkdir(exist_ok=True)
    sick = make_pdf(SICK_LINES)
    (OUT / "sick-note-sample.pdf").write_bytes(sick)
    (OUT / "sick-note-sample.fake.pdf").write_bytes(
        make_pdf(
            SICK_LINES,
            {
                "doc_type": "sick_note",
                "person_name": "Amy Lau",
                "provider_name": "Sample Family Clinic",
                "issue_date": "2026-09-24",
                "rest_start_date": "2026-09-24",
                "rest_end_date": "2026-09-25",
                "days_advised": 2,
            },
        )
    )
    (OUT / "receipt-sample.fake.pdf").write_bytes(
        make_pdf(
            receipt_lines(True),
            {
                "doc_type": "receipt",
                "provider_name": "Sample Noodle House",
                "receipt_date": "2026-09-20",
                "total_amount": 83.6,
                "currency": "HKD",
                "suggested_claim_type": "meal",
            },
        )
    )
    (OUT / "receipt-incomplete.fake.pdf").write_bytes(
        make_pdf(
            receipt_lines(False),
            {
                "doc_type": "receipt",
                "provider_name": "Sample Noodle House",
                "total_amount": 83.6,
                "currency": "HKD",
                "suggested_claim_type": "meal",
                "unreadable_fields": ["receipt_date"],
            },
        )
    )
    (OUT / "unreadable.fake.pdf").write_bytes(
        make_pdf(
            [(11, 560, "SAMPLE - FICTIONAL  (blurry, unreadable photo stand-in)")],
            {"doc_type": "unreadable", "readable": False},
        )
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for name, with_date in (("receipt-sample", True), ("receipt-incomplete", False)):
            pdf = tmpdir / f"{name}.pdf"
            pdf.write_bytes(make_pdf(receipt_lines(with_date)))
            sips(["-s", "format", "png", str(pdf), "--out", str(OUT / f"{name}.png")])
            sips(["--resampleWidth", "620", str(OUT / f"{name}.png")])
        # Unreadable image: a receipt shrunk to a few pixels and blown up again.
        tiny, blurry = tmpdir / "tiny.png", OUT / "unreadable-blurry.png"
        sips(["--resampleWidth", "14", str(OUT / "receipt-sample.png"), "--out", str(tiny)])
        sips(["--resampleWidth", "620", str(tiny), "--out", str(blurry)])
    for path in sorted(OUT.iterdir()):
        print(f"{path.name:32s}{path.stat().st_size:>8d} bytes")


if __name__ == "__main__":
    main()
