"""Image preparation for vision models that cannot read PDFs or alpha (in memory only).

``pdf_to_png_pages`` renders the first pages of a PDF with ``pypdfium2`` (bundled PDFium, no
system libraries); ``flatten_png_alpha`` composites a transparent PNG onto white, because
Ollama drops the alpha channel and a transparent-background screenshot then becomes black on
black (the model sees nothing). A tiny stdlib PNG codec is used, so neither Pillow nor
temporary files are needed.
"""

from __future__ import annotations

import logging
import struct
import zlib

from app.llm.base import LLMError

logger = logging.getLogger(__name__)

MAX_PAGES = 3
DPI = 170
MAX_EDGE_PX = 1600
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def encode_png_rgb(width: int, height: int, stride: int, pixels: bytes | bytearray) -> bytes:
    """Encode 8-bit RGB rows (``stride`` bytes apart) as a PNG."""
    row_bytes = width * 3
    rows = bytearray()
    for y in range(height):
        start = y * stride
        rows += b"\x00" + pixels[start : start + row_bytes]  # filter type 0 (None)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        _PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + _chunk(b"IEND", b"")
    )


MAX_FLATTEN_PIXELS = 3_000_000  # larger PNGs are passed through unchanged (pure-Python codec)


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> list[bytearray] | None:
    stride = width * bpp
    if len(raw) < height * (stride + 1):
        return None
    rows: list[bytearray] = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        kind = raw[pos]
        row = bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += stride + 1
        if kind == 1:  # Sub
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 255
        elif kind == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 255
        elif kind == 3:  # Average
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 255
        elif kind == 4:  # Paeth
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[i] = (row[i] + pred) & 255
        elif kind != 0:
            return None
        rows.append(row)
        prev = row
    return rows


def flatten_png_alpha(data: bytes) -> bytes:
    """Return an opaque RGB PNG (transparency composited on white) for 8-bit RGBA/grey+alpha
    PNGs. Anything else (no alpha, other formats, interlaced, huge, malformed) is returned
    unchanged, so this never makes an upload worse."""
    try:
        if not data.startswith(_PNG_SIGNATURE):
            return data
        pos = len(_PNG_SIGNATURE)
        header: tuple[int, ...] | None = None
        idat = bytearray()
        while pos + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[pos : pos + 8])
            body = data[pos + 8 : pos + 8 + length]
            pos += 12 + length
            if kind == b"IHDR":
                header = struct.unpack(">IIBBBBB", body)
            elif kind == b"IDAT":
                idat += body
            elif kind == b"IEND":
                break
        if header is None:
            return data
        width, height, depth, color, _comp, _filt, interlace = header
        if depth != 8 or color not in (4, 6) or interlace != 0:
            return data
        if width * height > MAX_FLATTEN_PIXELS or not idat:
            return data
        bpp = 4 if color == 6 else 2
        rows = _unfilter(zlib.decompress(bytes(idat)), width, height, bpp)
        if rows is None:
            return data
        out = bytearray()
        for row in rows:
            alpha = row[bpp - 1 :: bpp]
            if color == 6:
                channels = (row[0::4], row[1::4], row[2::4])
            else:
                grey = row[0::2]
                channels = (grey, grey, grey)
            if alpha.count(255) == width:
                rgb = bytearray(width * 3)
                for k, channel in enumerate(channels):
                    rgb[k::3] = channel
            else:
                rgb = bytearray(width * 3)
                for k, channel in enumerate(channels):
                    rgb[k::3] = bytes(
                        (c * a + 255 * (255 - a)) // 255
                        for c, a in zip(channel, alpha, strict=True)
                    )
            out += rgb
        return encode_png_rgb(width, height, width * 3, out)
    except Exception:
        return data


def pdf_to_png_pages(
    data: bytes, max_pages: int = MAX_PAGES, dpi: int = DPI, max_edge: int = MAX_EDGE_PX
) -> list[bytes]:
    """PNG bytes of the first ``max_pages`` pages. Raises ``LLMError`` for unreadable PDFs."""
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(bytes(data))
        try:
            pages: list[bytes] = []
            for index in range(min(len(document), max_pages)):
                page = document[index]
                try:
                    width_pt, height_pt = page.get_size()
                    scale = min(dpi / 72, max_edge / max(width_pt, height_pt))
                    bitmap = page.render(scale=scale, rev_byteorder=True, may_draw_forms=False)
                    try:
                        pages.append(
                            encode_png_rgb(
                                bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer)
                            )
                        )
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        finally:
            document.close()
    except Exception:
        # Never log the exception text or the bytes: a PDF may contain personal data.
        logger.warning("PDF could not be rendered for the vision model")
        raise LLMError("Could not read the PDF") from None
    if not pages:
        raise LLMError("Could not read the PDF")
    return pages
