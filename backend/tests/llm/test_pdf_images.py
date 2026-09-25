"""PDF -> PNG rendering and PNG alpha flattening (real pypdfium2, no network)."""

import io
import struct
import zlib
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from app.llm.base import LLMError
from app.llm.pdf_images import (
    MAX_EDGE_PX,
    MAX_PAGES,
    encode_png_rgb,
    flatten_png_alpha,
    pdf_to_png_pages,
)

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def make_pdf(pages: int, width: float = 200, height: float = 300) -> bytes:
    document = pdfium.PdfDocument.new()
    for _ in range(pages):
        document.new_page(width, height)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(SIGNATURE)
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def rgba_png(rows: list[tuple[int, list[int]]], width: int, color: int = 6) -> bytes:
    """Hand-built 8-bit PNG; each row is (filter_type, already-filtered bytes)."""
    raw = b"".join(bytes([kind]) + bytes(data) for kind, data in rows)
    header = struct.pack(">IIBBBBB", width, len(rows), 8, color, 0, 0, 0)
    return (
        SIGNATURE
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


def decode_rgb(png: bytes, width: int, height: int) -> list[list[int]]:
    """Unfiltered (filter 0 only) RGB rows of a PNG written by ``encode_png_rgb``."""
    idat = b""
    pos = len(SIGNATURE)
    while pos < len(png):
        length, kind = struct.unpack(">I4s", png[pos : pos + 8])
        if kind == b"IDAT":
            idat += png[pos + 8 : pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = []
    for y in range(height):
        assert raw[y * stride] == 0
        rows.append(list(raw[y * stride + 1 : (y + 1) * stride]))
    return rows


def test_sample_sick_note_renders_one_png_page() -> None:
    pages = pdf_to_png_pages((SAMPLES / "sick-note-sample.pdf").read_bytes())
    assert len(pages) == 1
    assert pages[0].startswith(SIGNATURE)
    assert max(png_size(pages[0])) <= MAX_EDGE_PX


def test_page_cap() -> None:
    assert len(pdf_to_png_pages(make_pdf(5))) == MAX_PAGES == 3
    assert len(pdf_to_png_pages(make_pdf(5), max_pages=2)) == 2
    assert len(pdf_to_png_pages(make_pdf(1))) == 1


def test_longest_edge_is_capped() -> None:
    huge = make_pdf(1, width=2000, height=3000)  # 42 in tall: dpi scaling alone gives ~7000 px
    width, height = png_size(pdf_to_png_pages(huge)[0])
    assert max(width, height) <= MAX_EDGE_PX
    assert height > width  # aspect ratio kept


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a pdf at all",
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF",
        (SAMPLES / "sick-note-sample.pdf").read_bytes()[:200],  # truncated
    ],
)
def test_corrupt_pdf_raises_safe_llm_error(data: bytes, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG"), pytest.raises(LLMError) as info:
        pdf_to_png_pages(data)
    assert str(info.value) == "Could not read the PDF"
    assert "not a pdf at all" not in caplog.text


def test_encrypted_pdf_raises_llm_error() -> None:
    encrypted = (
        b"%PDF-1.6\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>\nendobj\n"
        b"4 0 obj\n<< /Filter /Standard /V 1 /R 2 /O (0123456789abcdef0123456789abcdef) "
        b"/U (0123456789abcdef0123456789abcdef) /P -4 >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R /Size 5 /Encrypt 4 0 R /ID [<00><00>] >>\n%%EOF"
    )
    with pytest.raises(LLMError, match="Could not read the PDF"):
        pdf_to_png_pages(encrypted)


def test_encode_png_rgb_roundtrip() -> None:
    pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9])  # 2x2
    png = encode_png_rgb(2, 2, 6, pixels)
    assert png_size(png) == (2, 2)
    assert decode_rgb(png, 2, 2) == [[255, 0, 0, 0, 255, 0], [0, 0, 255, 9, 9, 9]]


def test_flatten_composites_transparency_on_white() -> None:
    # Row 0 (filter None): transparent black, opaque red. Row 1 (filter Up, delta 0): the same.
    png = rgba_png([(0, [0, 0, 0, 0, 255, 0, 0, 255]), (2, [0] * 8)], width=2)
    flat = flatten_png_alpha(png)
    assert flat != png
    assert decode_rgb(flat, 2, 2) == [[255, 255, 255, 255, 0, 0]] * 2


def test_flatten_half_transparent_pixel() -> None:
    png = rgba_png([(0, [0, 0, 0, 128])], width=1)
    (row,) = decode_rgb(flatten_png_alpha(png), 1, 1)
    assert all(126 <= value <= 129 for value in row)


def test_flatten_opaque_rgba_and_grey_alpha() -> None:
    opaque = flatten_png_alpha(rgba_png([(0, [10, 20, 30, 255])], width=1))
    assert decode_rgb(opaque, 1, 1) == [[10, 20, 30]]
    grey = flatten_png_alpha(rgba_png([(0, [50, 255, 200, 0])], width=2, color=4))
    assert decode_rgb(grey, 2, 1) == [[50, 50, 50, 255, 255, 255]]


def test_flatten_handles_sub_filter() -> None:
    # Sub filter: second pixel = first + delta.
    png = rgba_png([(1, [10, 10, 10, 255, 5, 5, 5, 0])], width=2)
    (row,) = decode_rgb(flatten_png_alpha(png), 2, 1)
    assert row[:3] == [10, 10, 10]
    assert row[3:] == [15, 15, 15]  # 10 + 5 (Sub), alpha 255 + 0: opaque


def test_flatten_leaves_other_input_unchanged() -> None:
    rgb = encode_png_rgb(1, 1, 3, bytes([1, 2, 3]))
    assert flatten_png_alpha(rgb) is rgb  # already opaque (colour type 2)
    for data in (b"", b"GIF89a", b"\x89PNG\r\n\x1a\n" + b"garbage", SIGNATURE):
        assert flatten_png_alpha(data) == data
    interlaced = SIGNATURE + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 1))
    assert flatten_png_alpha(interlaced) == interlaced


def test_sample_pngs_become_opaque_rgb() -> None:
    data = (SAMPLES / "receipt-sample.png").read_bytes()
    flat = flatten_png_alpha(data)
    assert flat != data
    assert flat[25] == 2  # IHDR colour type: RGB, no alpha
    assert png_size(flat) == png_size(data)
