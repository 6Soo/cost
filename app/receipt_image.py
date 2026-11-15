"""Shared structural checks for receipt image bytes."""

def sniff_image(body: bytes) -> str:
    """Return the media type only for an image that passes the receipt upload checks."""
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        pos, first, ended = 8, True, False
        while pos + 8 <= len(body) and not ended:
            length = int.from_bytes(body[pos:pos + 4], "big")
            kind = body[pos + 4:pos + 8]
            if first and (kind != b"IHDR" or length != 13):
                raise ValueError("IMAGE_CORRUPT")
            first = False
            pos += 12 + length
            ended = kind == b"IEND"
        if not ended or pos != len(body):
            raise ValueError("IMAGE_CORRUPT")
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        # Phone cameras append data after the EOI marker, so the end of the file is not the end of the picture.
        if _jpeg_has_eoi(body) or body.rstrip().endswith(b"\xff\xd9"):
            return "image/jpeg"
        raise ValueError("IMAGE_CORRUPT")
    if body[4:8] == b"ftyp" and body[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1", b"avif"):
        raise ValueError("IMAGE_HEIC")
    raise ValueError("IMAGE_TYPE_UNSUPPORTED")


def _jpeg_has_eoi(body: bytes) -> bool:
    """Follow JPEG segments through the scan; ignore bytes after the EOI marker."""
    pos, size, framed = 2, len(body), False
    while pos + 1 < size:
        if body[pos] != 0xFF:
            return False
        marker = body[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            pos += 2
            continue
        if marker == 0xD9 or pos + 4 > size:
            return False
        framed = framed or (0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC))
        pos += 2 + int.from_bytes(body[pos + 2:pos + 4], "big")
        if marker != 0xDA:
            continue
        if not framed:
            return False
        while pos + 1 < size:
            if body[pos] == 0xFF and body[pos + 1] not in (0x00, 0xFF) and not 0xD0 <= body[pos + 1] <= 0xD7:
                break
            pos += 1
        if pos + 1 < size and body[pos + 1] == 0xD9:
            return True
    return False