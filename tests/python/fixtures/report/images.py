"""Tiny valid test images built in code (nothing downloaded). PNGs are generated; the JPEG, GIF and WebP are small real files
kept as base64 so the structural checks are exercised on genuine data."""
import base64
import struct
import zlib


def _chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def png(rgb=(255, 0, 0), size=16, alpha=False):
    """A solid-colour PNG. Different colours give different bytes, so PDFs cannot merge them.
    alpha=True writes an RGBA image whose opacity fades across the rows, so a PDF needs a soft mask for it."""
    if alpha:
        raw = b"".join(b"\x00" + b"".join(bytes(rgb) + bytes([40 + (200 * y) // max(1, size - 1)]) for _ in range(size)) for y in range(size))
        colour_type = 6
    else:
        raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
        colour_type = 2
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, colour_type, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


JPEG = base64.b64decode(
    (
    "/9j/4AAQSkZJRgABAQAASABIAAD/4QBMRXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAA6ABAAMAAAABAAEAAKACAAQA"
    "AAABAAAABKADAAQAAAABAAAABAAAAAD/7QA4UGhvdG9zaG9wIDMuMAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmA"
    "CZjs+EJ+/8AAEQgABAAEAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQE"
    "AAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldY"
    "WVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk"
    "5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMR"
    "BAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdo"
    "aWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz"
    "9PX29/j5+v/bAEMAAgICAgICAwICAwUDAwMFBgUFBQUGCAYGBgYGCAoICAgICAgKCgoKCgoKCgwMDAwMDA4ODg4ODw8PDw8PDw8P"
    "D//bAEMBAgICBAQEBwQEBxALCQsQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEP/dAAQA"
    "Af/aAAwDAQACEQMRAD8A+Q6KKK/Cz/VQ/9k="
)
)
GIF = base64.b64decode(
    (
    "R0lGODdhBAAEAJEAAAAAAMgeHv///wAAACH5BAQAAAAALAAAAAAEAAQAAAIEjI8ZBQA7"
)
)
WEBP = base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")
NOT_AN_IMAGE = b"<html>this is a saved error page, not a picture</html>"

def png_from_raw(width, height, raw, ctype=2, depth=8, interlace=0, palette=False, idat=None):
    """A PNG with the given (already filter-prefixed) pixel stream; idat overrides the compressed bytes."""
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, interlace))
    if palette: out += _chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")
    return out + _chunk(b"IDAT", zlib.compress(raw) if idat is None else idat) + _chunk(b"IEND", b"")


def jpeg_without_scan_data():
    sof = b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    sos = b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    return b"\xff\xd8" + sof + sos + b"\xff\xd9"


def gif_with(*blocks):
    """A GIF89a, 1x1, no colour table, followed by the given raw blocks and a trailer."""
    return b"GIF89a\x01\x00\x01\x00\x00\x00\x00" + b"".join(blocks) + b";"


# One truncated or hollow file per type: each has the right first bytes and must still be rejected.
TRUNCATED = {
    "png-signature-only": b"\x89PNG\r\n\x1a\n",
    "png-cut-in-the-middle": png((1, 2, 3))[:60],
    "png-no-iend": png((1, 2, 3))[:-12],
    "png-no-idat": b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)) + _chunk(b"IEND", b""),
    "png-zero-size": b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 0, 0, 8, 2, 0, 0, 0)) + _chunk(b"IDAT", zlib.compress(b"")) + _chunk(b"IEND", b""),
    "png-bad-checksum": bytearray(png((1, 2, 3)))[:-1] + b"\x00",
    "jpeg-soi-only": b"\xff\xd8\xff",
    "jpeg-cut-before-the-end": JPEG[:len(JPEG) // 2],
    "jpeg-no-end-marker": JPEG[:-2],
    "jpeg-no-frame": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9",
    "gif-header-only": b"GIF89a",
    "gif-cut-before-the-trailer": GIF[:-1],
    "gif-zero-size": GIF[:6] + b"\x00\x00\x00\x00" + GIF[10:],
    "webp-header-only": b"RIFF\x1a\x00\x00\x00WEBP",
    "webp-cut-short": WEBP[:-6],
    # The review's reproductions: right header, but no pixels at all.
    "webp-empty-vp8-chunk": bytes.fromhex("524946460c000000574542505650382000000000"),
    "gif-header-and-trailer-only": gif_with(),
    "gif-image-block-without-data": gif_with(b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x00"),
    "gif-zero-size-image-block": gif_with(b"\x2c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x02\x44\x01\x00"),
    "jpeg-no-scan-data": jpeg_without_scan_data(),
    "webp-vp8-without-a-frame-header": b"RIFF\x1c\x00\x00\x00WEBPVP8 \x10\x00\x00\x00" + b"\x00" * 16,
    "png-pixels-do-not-decompress": png_from_raw(4, 4, b"", idat=b"this is not a zlib stream"),
    "png-pixel-stream-too-short": png_from_raw(4, 4, b"\x00" * (4 * 13 - 1)),
    "png-pixel-stream-too-long": png_from_raw(4, 4, b"\x00" * (4 * 13 + 1)),
    "png-invalid-row-filter": png_from_raw(4, 4, (b"\x09" + b"\x00" * 12) * 4),
    "png-palette-without-plte": png_from_raw(4, 4, (b"\x00" + b"\x00" * 4) * 4, ctype=3),
    "webp-no-image-chunk": b"RIFF\x0c\x00\x00\x00WEBPJUNK\x00\x00\x00\x00",
}
