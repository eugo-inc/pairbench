# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The share image of the documentation site: what it shows, and that the committed file
holds the pixels its generator draws."""

from __future__ import annotations

import functools
import inspect
import math
import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from .conftest import load_tool

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "site/public/share.png"
# The maker's logo the image draws in its top right corner: the README's copy of it.
LOGO = "docs/readme/eugo-logo.svg"
WIDTH = 1200
HEIGHT = 630
SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The header the script writes: its size, eight bits per sample, colour type 2 (RGB), standard
# compression and filtering, no interlace.
HEADER = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
# What the check of the committed file accepts and what it refuses, word for word.
CHECK_RULE = (
    "Whether a file is the PNG this script writes, up to how its rows are compressed. "
    "It must hold exactly the chunks IHDR, one or more IDAT and IEND, in that order, each "
    "with the CRC of its type and data, and nothing after IEND. The IHDR must be this "
    "script's header: its width and height, eight bits per sample, RGB, no interlace. The "
    "IEND must be empty. The IDAT data, joined, must be one zlib stream with nothing after "
    "its end, and it must decompress to the rows this script draws, each led by the filter "
    "byte 0 (None). So the same rows compressed by another zlib compressor or at another "
    "level, or split across several IDAT chunks, are accepted. The same pixels saved with "
    "another row filter are refused, as are any other chunk (text, Exif data, a time or a "
    "colour profile), another header, an IEND that holds data, a wrong CRC, a chunk cut "
    "short, and bytes after IEND or after the end of the compressed rows."
)
NAME = "pairbench"
LINE = "Tells real benchmark differences from noise"
ALT = (
    "The name pairbench in white beside its mark of four rounded tiles in violet and blue, above "
    "the line “Tells real benchmark differences from noise”, on a dark background under a "
    "violet-to-blue band, with the maker's logo in the top right corner."
)
# A PNG file that holds its header, its pixels and its end, and no text, date or colour
# profile beside them.
CHUNKS = [b"IHDR", b"IDAT", b"IEND"]
RGB_8_BIT = (8, 2)
# Pixels of the mark, by column and row, and their colours. The top-left tile is violet,
# shaded from #b26bff at its top to #a24bff at its bottom; the one below it is azure. Near its
# top edge the white highlight shows, at 22 percent; under its bottom edge, in the gap
# between the rows of tiles, its shadow darkens the ground (#160f3d); far below the mark the
# ground is untouched.
MARK_PIXELS = {
    "the highlight at the top of the violet tile": ((197, 161), (195, 140, 255)),
    "the violet tile near its top": ((197, 170), (176, 102, 255)),
    "the violet tile near its bottom": ((197, 225), (163, 77, 255)),
    "the shadow just under the violet tile": ((197, 230), (14, 10, 39)),
    "the shadow further down": ((197, 234), (19, 13, 54)),
    "the azure tile below it": ((197, 240), (115, 198, 255)),
    "the ground far below the mark": ((197, 330), (22, 15, 61)),
}
# Pixels of the maker's logo in the top right corner, by column and row, and their colours:
# the outlines of docs/readme/eugo-logo.svg, each in its own gradient, the mark from violet at
# its left to blue at its right, and the name from violet at its first letter to blue at its
# last.
LOGO_PIXELS = {
    "the mark at its left": ((998, 71), (148, 91, 232)),
    "the mark at its right": ((1056, 68), (49, 133, 241)),
    "the name at its first letter": ((1077, 59), (148, 88, 234)),
    "the name at its last letter": ((1153, 63), (6, 149, 232)),
}
# The mark's shadow has a standard deviation of 1.2 of its 64 units; the card draws the mark
# 168 pixels wide, so 3.15 pixels. Three box passes of these widths have a variance of
# (24 + 48 + 48) / 12 = 10 square pixels, the nearest odd widths come to 3.15 squared.
SHADOW_DEVIATION_PIXELS = 1.2 * 168 / 64
BOX_WIDTHS = [5, 7, 7]
# What a figure is written with: none of it can be drawn.
FIGURE_SIGNS = "0123456789%.,"
# What the check prints after the file's name and its cause: how to write the file it wants.
REMEDY = "run python3 tools/share_image.py"
MISSING = "is missing"
OUT_OF_DATE = "is out of date (its pixels are not the ones this script draws)"
ANOTHER_FILTER = "has another row filter (this script writes filter 0, None, on every row)"
EXIT_OK = 0
EXIT_STALE = 1
# The bytes of one row of pixels: three samples of eight bits each, red, green and blue.
ROW_BYTES = WIDTH * 3
# PNG's five row filters, by the number a row's first byte holds: None, Sub, Up, Average and
# Paeth.
FILTER_TYPES = range(5)


@pytest.fixture(scope="module")
def share() -> ModuleType:
    return load_tool(ROOT, "share_image")


@pytest.fixture(scope="module")
def rows(share: ModuleType) -> bytes:
    """The rows the script draws, each led by its filter byte."""
    drawn: bytes = share.render()
    return drawn


def chunk(kind: bytes, data: bytes) -> bytes:
    """One PNG chunk: its length, its type, its data and the CRC of the type and data."""
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png_of(*chunks: tuple[bytes, bytes]) -> bytes:
    return SIGNATURE + b"".join(chunk(kind, data) for kind, data in chunks)


def plain(stream: bytes, header: bytes = HEADER) -> bytes:
    """A PNG file of a header, one IDAT chunk of a compressed stream and an end."""
    return png_of((b"IHDR", header), (b"IDAT", stream), (b"IEND", b""))


def split(stream: bytes) -> bytes:
    half = len(stream) // 2
    return png_of(
        (b"IHDR", HEADER), (b"IDAT", stream[:half]), (b"IDAT", stream[half:]), (b"IEND", b"")
    )


def by_strategy(rows: bytes) -> bytes:
    """The rows compressed with zlib's filtered strategy and its largest memory level."""
    packer = zlib.compressobj(6, zlib.DEFLATED, 15, 9, zlib.Z_FILTERED)
    return packer.compress(rows) + packer.flush()


def wrong_crc(data: bytes) -> bytes:
    """A file whose IDAT chunk, the one before the 12 bytes of IEND, has a wrong CRC."""
    return data[:-13] + bytes([data[-13] ^ 0xFF]) + data[-12:]


def first_row_up(rows: bytes) -> bytes:
    """The same pixels with the first row under filter 2 (Up): Up adds the byte above, and
    above the first row every byte is zero, so the row's bytes stay as they are."""
    return b"\x02" + rows[1:]


def _paeth(left: int, above: int, corner: int) -> int:
    """The Paeth predictor: of the bytes to the left, above and above to the left, the one
    nearest to left + above - corner, ties going to the left, then to the one above."""
    guess = left + above - corner
    to_left, to_above, to_corner = abs(guess - left), abs(guess - above), abs(guess - corner)
    if to_left <= to_above and to_left <= to_corner:
        return left
    return above if to_above <= to_corner else corner


def filtered(kind: int, row: bytes, prior: bytes) -> bytes:
    """A row of pixels under one of PNG's five filters, given the row above it unfiltered."""
    left = bytes(3) + row[:-3]
    if kind == 0:
        return row
    if kind == 1:
        return bytes((x - a) & 0xFF for x, a in zip(row, left, strict=True))
    if kind == 2:
        return bytes((x - b) & 0xFF for x, b in zip(row, prior, strict=True))
    if kind == 3:
        return bytes((x - (a + b) // 2) & 0xFF for x, a, b in zip(row, left, prior, strict=True))
    corner = bytes(3) + prior[:-3]
    return bytes(
        (x - _paeth(a, b, c)) & 0xFF for x, a, b, c in zip(row, left, prior, corner, strict=True)
    )


def _signed_sum(row: bytes) -> int:
    return sum(value if value < 128 else 256 - value for value in row)


@functools.cache
def adaptive(rows: bytes) -> bytes:
    """The rows as an image editor saves them with adaptive filtering: each row under the
    filter whose bytes, read as signed numbers, have the smallest sum of absolute values."""
    out = bytearray()
    prior = bytes(ROW_BYTES)
    for start in range(0, len(rows), ROW_BYTES + 1):
        row = rows[start + 1 : start + 1 + ROW_BYTES]
        kind, best = min(
            ((kind, filtered(kind, row, prior)) for kind in FILTER_TYPES),
            key=lambda pair: _signed_sum(pair[1]),
        )
        out.append(kind)
        out += best
        prior = row
    return bytes(out)


def other_pixels(rows: bytes) -> bytes:
    """The rows with the first sample of the first pixel changed."""
    changed = bytearray(rows)
    changed[1] ^= 0xFF
    return bytes(changed)


TEXT = (b"tEXt", b"Comment\x00made-up text")
# A chunk whose type holds an escape sequence of a terminal, not four letters.
ESCAPE = (b"\x1b[0m", b"")
# A zlib stream ends with the four bytes of its Adler-32 checksum.
CHECKSUM_LENGTH = 4
# An IDAT chunk ends with its CRC: cutting this many bytes from the end of a file of a header,
# one IDAT chunk and an IEND chunk cuts into the IDAT chunk's data.
INTO_THE_ROWS = 20
# The rows the check accepts: the same rows, compressed another way.
ACCEPTED: dict[str, Callable[[bytes], bytes]] = {
    "at compression level 1": lambda rows: plain(zlib.compress(rows, 1)),
    "stored without compression": lambda rows: plain(zlib.compress(rows, 0)),
    "by another strategy": lambda rows: plain(by_strategy(rows)),
    "split across two IDAT chunks": lambda rows: split(zlib.compress(rows, 9)),
}
# The files the check refuses, most of them holding the same rows or the same pixels, each
# with what the check says of it after the file's name.
REFUSED: dict[str, tuple[Callable[[bytes], bytes], str]] = {
    "the same pixels with another row filter": (
        lambda rows: plain(zlib.compress(first_row_up(rows), 9)),
        ANOTHER_FILTER,
    ),
    "an editor's re-save with adaptive row filters": (
        lambda rows: plain(zlib.compress(adaptive(rows), 6)),
        ANOTHER_FILTER,
    ),
    "other pixels": (lambda rows: plain(zlib.compress(other_pixels(rows), 9)), OUT_OF_DATE),
    "an interlaced header": (
        lambda rows: plain(zlib.compress(rows, 9), HEADER[:12] + b"\x01"),
        "has another header (interlace method 1, not 0)",
    ),
    "a header of sixteen-bit samples": (
        lambda rows: plain(zlib.compress(rows, 9), HEADER[:8] + b"\x10" + HEADER[9:]),
        "has another header (bit depth 16, not 8)",
    ),
    "a header of another size": (
        lambda rows: plain(zlib.compress(rows, 9), struct.pack(">II", 600, 315) + HEADER[8:]),
        "has another header (width 600, not 1200; height 315, not 630)",
    ),
    "a header of twelve bytes": (
        lambda rows: plain(zlib.compress(rows, 9), HEADER[:12]),
        "has another header (of 12 bytes, not 13)",
    ),
    "a wrong CRC": (
        lambda rows: wrong_crc(plain(zlib.compress(rows, 9))),
        "has a bad checksum (in its IDAT chunk)",
    ),
    "not a PNG file": (lambda rows: b"GIF89a made-up bytes", "is not a PNG file"),
    "a chunk cut short": (
        lambda rows: plain(zlib.compress(rows, 9))[:-4],
        "is cut short (it ends before its IEND chunk)",
    ),
    "the rows' chunk cut short": (
        lambda rows: plain(zlib.compress(rows, 9))[:-INTO_THE_ROWS],
        "is cut short (it ends before its IEND chunk)",
    ),
    "no IEND after an empty IDAT": (
        lambda rows: png_of((b"IHDR", HEADER), (b"IDAT", zlib.compress(rows, 9)), (b"IDAT", b"")),
        "is cut short (it ends before its IEND chunk)",
    ),
    "bytes after IEND": (
        lambda rows: plain(zlib.compress(rows, 9)) + b"made-up bytes",
        "has data after the end (after its IEND chunk)",
    ),
    "a chunk after IEND": (
        lambda rows: plain(zlib.compress(rows, 9)) + chunk(*TEXT),
        "has data after the end (after its IEND chunk)",
    ),
    "IEND before the rows": (
        lambda rows: png_of((b"IHDR", HEADER), (b"IEND", b""), (b"IDAT", zlib.compress(rows, 9))),
        "has data after the end (after its IEND chunk)",
    ),
    "an IEND that holds data": (
        lambda rows: png_of(
            (b"IHDR", HEADER), (b"IDAT", zlib.compress(rows, 9)), (b"IEND", b"made-up bytes")
        ),
        "has data in its IEND chunk",
    ),
    "a text chunk before the rows": (
        lambda rows: png_of(
            (b"IHDR", HEADER), TEXT, (b"IDAT", zlib.compress(rows, 9)), (b"IEND", b"")
        ),
        "has an extra chunk (tEXt)",
    ),
    "a chunk whose type is not four letters": (
        lambda rows: png_of(
            (b"IHDR", HEADER), ESCAPE, (b"IDAT", zlib.compress(rows, 9)), (b"IEND", b"")
        ),
        "has an extra chunk (0x1b5b306d)",
    ),
    "the header in a chunk of another type": (
        lambda rows: png_of((b"tEXt", HEADER), (b"IDAT", zlib.compress(rows, 9)), (b"IEND", b"")),
        "has an extra chunk (tEXt)",
    ),
    "two headers": (
        lambda rows: png_of(
            (b"IHDR", HEADER), (b"IHDR", HEADER), (b"IDAT", zlib.compress(rows, 9)), (b"IEND", b"")
        ),
        "has an extra chunk (a second IHDR)",
    ),
    "the rows before the header": (
        lambda rows: png_of((b"IDAT", zlib.compress(rows, 9)), (b"IHDR", HEADER), (b"IEND", b"")),
        "has another header (its first chunk is IDAT, not IHDR)",
    ),
    "no IDAT": (
        lambda rows: png_of((b"IHDR", HEADER), (b"IEND", b"")),
        "has no rows (no IDAT chunk)",
    ),
    "rows that are not a zlib stream": (
        lambda rows: plain(b"made-up bytes"),
        "has compressed rows that do not decompress",
    ),
    "the compressed rows cut short": (
        lambda rows: plain(zlib.compress(rows, 9)[:-8]),
        "has compressed rows cut short (their zlib stream does not end)",
    ),
    "the compressed rows without their checksum": (
        lambda rows: plain(zlib.compress(rows, 9)[:-CHECKSUM_LENGTH]),
        "has compressed rows cut short (their zlib stream does not end)",
    ),
    "bytes after the compressed rows": (
        lambda rows: plain(zlib.compress(rows, 9) + b"made-up bytes"),
        "has trailing compressed data (bytes after the end of the zlib stream of its rows)",
    ),
    "a row too many": (
        lambda rows: plain(zlib.compress(rows + rows[-(ROW_BYTES + 1) :], 9)),
        "has rows of another length than its header gives",
    ),
}
# What ``chunks`` says of a file it cannot read whole, and the file.
CUT_SHORT = "a chunk is cut short"
WRONG_IDAT_CRC = "the CRC of a b'IDAT' chunk does not match"
UNREADABLE: dict[str, tuple[Callable[[bytes], bytes], str]] = {
    "two bytes after IEND": (lambda rows: plain(zlib.compress(rows, 9)) + b"\x00\x00", CUT_SHORT),
    "an IEND without its CRC": (lambda rows: plain(zlib.compress(rows, 9))[:-4], CUT_SHORT),
    "a length past the end of the file": (
        lambda rows: plain(zlib.compress(rows, 9)) + b"made-up bytes",
        CUT_SHORT,
    ),
    "a wrong CRC": (lambda rows: wrong_crc(plain(zlib.compress(rows, 9))), WRONG_IDAT_CRC),
}


def stage(share: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    """Put a file where the script's check looks, in a repository of its own."""
    monkeypatch.setattr(share, "REPO", tmp_path)
    target = tmp_path / IMAGE
    target.parent.mkdir(parents=True)
    target.write_bytes(data)


def test_the_committed_image_holds_the_pixels_the_generator_draws(share: ModuleType) -> None:
    data = (ROOT / IMAGE).read_bytes()

    assert share.size(data) == (WIDTH, HEIGHT)
    assert share.pixels(data) == share.render()
    assert share.is_current(ROOT / IMAGE)


def test_the_image_is_an_rgb_png_with_nothing_beside_its_pixels(share: ModuleType) -> None:
    chunks = share.chunks((ROOT / IMAGE).read_bytes())
    header = dict(chunks)[b"IHDR"]

    assert [kind for kind, _ in chunks] == CHUNKS
    assert (header[8], header[9]) == RGB_8_BIT


def test_the_image_shows_the_name_and_one_plain_line(share: ModuleType) -> None:
    assert (share.NAME, share.LINE) == (NAME, LINE)
    assert [sign for sign in share.GLYPHS if sign in FIGURE_SIGNS] == []
    assert set(NAME + LINE) <= set(share.GLYPHS)


def test_the_alt_text_says_what_the_image_shows(share: ModuleType) -> None:
    assert share.ALT == ALT


@pytest.mark.parametrize("where", sorted(MARK_PIXELS))
def test_the_mark_is_shaded_with_a_highlight_and_a_shadow(rows: bytes, where: str) -> None:
    (x, y), colour = MARK_PIXELS[where]
    at = y * (ROW_BYTES + 1) + 1 + 3 * x

    assert tuple(rows[at : at + 3]) == colour


@pytest.mark.parametrize("where", sorted(LOGO_PIXELS))
def test_the_maker_s_logo_is_drawn_in_its_own_gradients(rows: bytes, where: str) -> None:
    (x, y), colour = LOGO_PIXELS[where]
    at = y * (ROW_BYTES + 1) + 1 + 3 * x

    assert tuple(rows[at : at + 3]) == colour


def test_the_logo_is_the_file_the_readme_s_banner_nests(share: ModuleType) -> None:
    assert share.LOGO == ROOT / LOGO


def test_the_shadow_is_blurred_by_box_passes_of_a_gaussian_s_variance(share: ModuleType) -> None:
    assert share.box_widths(SHADOW_DEVIATION_PIXELS) == BOX_WIDTHS
    assert "exp(" not in inspect.getsource(share)


def test_the_drawing_uses_square_roots_and_no_trigonometry(share: ModuleType) -> None:
    source = inspect.getsource(share)

    assert share.direction(0) == (1.0, 0.0)
    assert share.direction(30) == (math.sqrt(3.0) / 2.0, 0.5)
    assert share.direction(135) == (-math.sqrt(2.0) / 2.0, math.sqrt(2.0) / 2.0)
    with pytest.raises(ValueError, match="multiple of 15 degrees"):
        share.direction(10)
    assert [name for name in ("sin(", "cos(", "tan(", "atan", "radians") if name in source] == []


def test_the_check_finds_an_image_that_is_missing_or_differs(
    share: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(share, "REPO", tmp_path)
    target = tmp_path / IMAGE
    target.parent.mkdir(parents=True)

    assert share.main(["--check"]) == EXIT_STALE
    target.write_bytes(share.png(other_pixels(share.render())))
    assert share.main(["--check"]) == EXIT_STALE
    assert share.main([]) == EXIT_OK
    assert share.main(["--check"]) == EXIT_OK
    assert capsys.readouterr() == (
        "",
        f"{IMAGE} {MISSING}: {REMEDY}\n{IMAGE} {OUT_OF_DATE}: {REMEDY}\n",
    )


def test_the_check_says_what_it_accepts_and_what_it_refuses(share: ModuleType) -> None:
    assert " ".join((inspect.getdoc(share.is_current) or "").split()) == CHECK_RULE
    assert "whatever compressor" not in inspect.getsource(share)


@pytest.mark.parametrize("way", sorted(ACCEPTED))
def test_the_check_accepts_the_same_rows_compressed_another_way(
    share: ModuleType,
    rows: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    way: str,
) -> None:
    stage(share, tmp_path, monkeypatch, ACCEPTED[way](rows))

    assert (share.main(["--check"]), capsys.readouterr()) == (EXIT_OK, ("", ""))


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_the_check_refuses_another_filter_header_chunk_or_stray_bytes_and_names_the_cause(
    share: ModuleType,
    rows: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    make, cause = REFUSED[case]
    stage(share, tmp_path, monkeypatch, make(rows))

    assert (share.main(["--check"]), capsys.readouterr()) == (
        EXIT_STALE,
        ("", f"{IMAGE} {cause}: {REMEDY}\n"),
    )
    assert share.is_current(tmp_path / IMAGE) is False


def unfiltered(rows: bytes) -> bytes:
    """The rows of a file with every filter undone, each led by the filter byte 0 (None)."""
    out = bytearray()
    prior = bytes(ROW_BYTES)
    for start in range(0, len(rows), ROW_BYTES + 1):
        kind, row = rows[start], rows[start + 1 : start + 1 + ROW_BYTES]
        pixels = bytearray(ROW_BYTES)
        for index, value in enumerate(row):
            left = pixels[index - 3] if index >= 3 else 0
            corner = prior[index - 3] if index >= 3 else 0
            above = prior[index]
            guess = (0, left, above, (left + above) // 2, _paeth(left, above, corner))[kind]
            pixels[index] = (value + guess) & 0xFF
        out.append(0)
        out += pixels
        prior = bytes(pixels)
    return bytes(out)


def test_an_editor_s_re_save_holds_the_same_pixels_under_other_row_filters(rows: bytes) -> None:
    resaved = adaptive(rows)

    assert sorted(set(resaved[:: ROW_BYTES + 1])) == list(FILTER_TYPES)[1:]
    assert unfiltered(resaved) == rows


@pytest.mark.parametrize("case", sorted(UNREADABLE))
def test_the_chunks_of_a_file_cut_short_or_with_a_wrong_crc_are_a_value_error(
    share: ModuleType, rows: bytes, case: str
) -> None:
    make, message = UNREADABLE[case]

    with pytest.raises(ValueError) as raised:
        share.chunks(make(rows))
    assert str(raised.value) == message
