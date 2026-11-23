# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What a line on standard error shows of a text read from an input: ``errors.printable``.

Every character that could break the line, reorder the text around it on a terminal or fail
to encode is written as an escape; every other character is printed as it is.
"""

from __future__ import annotations

import random

import pytest

from pairbench import api
from pairbench.cli import common
from pairbench.cli import run as run_command
from pairbench.errors import Refusal, printable, unprintable
from pairbench.model import GateRecord

# The characters that end a line besides the control characters, and the Bidi_Control
# characters, as the Unicode Character Database lists them.
LINE_SEPARATORS = frozenset({0x2028, 0x2029})
BIDI_CONTROLS = frozenset(
    {0x061C, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E}
    | {0x2066, 0x2067, 0x2068, 0x2069}
)
CONTROLS = frozenset({*range(0x20), 0x7F, *range(0x80, 0xA0)})
SURROGATES = frozenset(range(0xD800, 0xE000))
# A flag written as an emoji and tag characters.
TAG_SEQUENCE = "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f"
ESCAPED = CONTROLS | LINE_SEPARATORS | BIDI_CONTROLS | SURROGATES
# The characters printable writes otherwise: the class and the backslash.
WRITTEN = ESCAPED | {0x5C}


def _escape(code: int) -> str:
    short = {0x09: "\\t", 0x0A: "\\n", 0x0D: "\\r", 0x5C: "\\\\"}
    if code in short:
        return short[code]
    if code < 0x100:
        return f"\\x{code:02x}"
    if code < 0x10000:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"


def _breaks_a_line(code: int) -> bool:
    return len(f"a{chr(code)}b".splitlines()) > 1


def test_every_character_that_breaks_a_line_is_in_the_escaped_class() -> None:
    breakers = {c for c in range(0x110000) if c not in SURROGATES and _breaks_a_line(c)}
    assert breakers == {0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029}
    assert breakers <= ESCAPED


def test_each_character_is_escaped_exactly_when_it_is_in_the_class() -> None:
    wrong = [
        f"U+{code:04X}"
        for code in range(0x110000)
        if printable(chr(code)) != (_escape(code) if code in WRITTEN else chr(code))
    ]
    assert wrong == []


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        pytest.param("a\u2028b", "a\\u2028b", id="line-separator"),
        pytest.param("a\u2029b", "a\\u2029b", id="paragraph-separator"),
        pytest.param("r\u202eabc", "r\\u202eabc", id="right-to-left-override"),
        pytest.param("x\u061cy", "x\\u061cy", id="arabic-letter-mark"),
        pytest.param("\u200e\u200f", "\\u200e\\u200f", id="direction-marks"),
        pytest.param("\u202a\u202b\u202c\u202d", "\\u202a\\u202b\\u202c\\u202d", id="embeddings"),
        pytest.param("\u2066\u2067\u2068\u2069", "\\u2066\\u2067\\u2068\\u2069", id="isolates"),
        pytest.param("a\ud800b\udfff", "a\\ud800b\\udfff", id="lone-surrogates"),
        pytest.param("a\x1b[2Jb\x9bc\x7f", "a\\x1b[2Jb\\x9bc\\x7f", id="controls"),
        pytest.param("a\tb\nc\rd\x0be\x85", "a\\tb\\nc\\rd\\x0be\\x85", id="control-breaks"),
    ],
)
def test_a_character_of_the_class_is_written_as_an_escape(text: str, shown: str) -> None:
    assert printable(text) == shown


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("caf\u00e9 \u00f1 \u00dcn\u00efc\u00f6d\u00e9", id="accents"),
        pytest.param("e\u0301", id="combining-mark"),
        pytest.param("\u884c\u5217\u4e57\u7b97", id="cjk"),
        pytest.param("\U0001f680conv", id="emoji"),
        pytest.param("\U0001f468\u200d\U0001f469\u200d\U0001f467", id="emoji-zwj"),
        pytest.param("\u2764\ufe0f 0\ufe0f\u20e3", id="variation-selectors"),
        pytest.param(TAG_SEQUENCE, id="tag-sequence"),
        pytest.param("a\u00a0b\u200bc", id="no-break-and-zero-width-spaces"),
        pytest.param("\u061b\u061d\u200d\u2010\u2027\u202f\u2065\u206a", id="next-to-the-class"),
        pytest.param("\ud7ff\ue000\ufffd\U0010ffff", id="next-to-surrogates"),
        pytest.param("\u00a0\u00ff\u0100", id="next-to-c1"),
    ],
)  # fmt: skip
def test_every_other_character_prints_as_it_is(text: str) -> None:
    assert printable(text) == text


def test_a_printed_line_always_encodes() -> None:
    text = "a\ud800b\udbff\udc00c\u2028d\x1be"
    assert printable(text).encode("utf-8") == b"a\\ud800b\\udbff\\udc00c\\u2028d\\x1be"


FORGED = "x\u2028pairbench: E_USAGE: made-up\u202e\u2066end\ud800"
SHOWN = "x\\u2028pairbench: E_USAGE: made-up\\u202e\\u2066end\\ud800"


def test_every_printed_line_escapes_the_class(capsys: pytest.CaptureFixture[str]) -> None:
    assert api.note_line("floor_provisional", FORGED) == (
        f"pairbench: note: floor_provisional: {SHOWN}"
    )
    failed = GateRecord(name="quiet", mode="warn", status="fail", detail={"message": FORGED})
    assert api.gate_line(failed) == f"pairbench: check quiet: fail: {SHOWN}"
    refusal = Refusal("E_USAGE", "a\u202eb\u2066c\ud800d")
    assert refusal.message == "a\u202eb\u2066c\ud800d"
    assert refusal.line == "E_USAGE: a\\u202eb\\u2066c\\ud800d"
    common.say(FORGED)
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", f"pairbench: {SHOWN}\n")


def test_a_refusal_in_a_kept_note_escapes_only_its_control_characters() -> None:
    refusal = Refusal("E_USAGE", "case a\x1bb\u202ec\\x1b")
    assert run_command._failure(refusal) == "E_USAGE: case a\\x1bb\u202ec\\x1b"
    assert run_command._failure(ValueError("x\u202e")) == "ValueError"


# Each printed text stands for one text only: a decoder reads every printed text back.
_SHORT = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}
_WIDTH = {"x": 2, "u": 4, "U": 8}
_HEX = frozenset("0123456789abcdef")


def decode(shown: str) -> str:
    """The text that ``printable`` printed as ``shown``; a ValueError for an escape it does not
    write."""
    out: list[str] = []
    at = 0
    while at < len(shown):
        char = shown[at]
        if char != "\\":
            out.append(char)
            at += 1
            continue
        kind = shown[at + 1 : at + 2]
        if kind in _SHORT:
            out.append(_SHORT[kind])
            at += 2
            continue
        width = _WIDTH.get(kind)
        digits = shown[at + 2 : at + 2 + width] if width else ""
        if width is None or len(digits) != width or not set(digits) <= _HEX:
            raise ValueError(f"no escape printable writes at {at}: {shown[at : at + 10]!r}")
        out.append(chr(int(digits, 16)))
        at += 2 + width
    return "".join(out)


@pytest.mark.parametrize(
    "shown",
    [
        pytest.param("\\", id="lone-backslash"),
        pytest.param("\\q", id="unknown-escape"),
        pytest.param("\\x1", id="short-x"),
        pytest.param("\\u202", id="short-u"),
        pytest.param("\\U0001f60", id="short-big-u"),
        pytest.param("\\x1B", id="upper-case-digits"),
    ],
)
def test_the_decoder_refuses_an_escape_printable_does_not_write(shown: str) -> None:
    with pytest.raises(ValueError, match=r"^no escape printable writes at 0: "):
        decode(shown)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        pytest.param("a\\b", "a\\\\b", id="backslash"),
        pytest.param("\\x1b", "\\\\x1b", id="typed-escape"),
        pytest.param("\\\x1b", "\\\\\\x1b", id="backslash-then-escape"),
        pytest.param("C:\\temp\\new", "C:\\\\temp\\\\new", id="windows-path"),
        pytest.param("\\n\n", "\\\\n\\n", id="typed-and-real-newline"),
    ],
)
def test_a_backslash_is_written_as_two(text: str, shown: str) -> None:
    assert printable(text) == shown
    assert decode(shown) == text


def test_a_typed_escape_and_the_character_it_names_print_apart() -> None:
    pairs = [("\\x1b", "\x1b"), ("\\n", "\n"), ("\\t", "\t"), ("\\x85", "\x85")]
    pairs += [("\\" + _escape(code)[1:], chr(code)) for code in (0x2028, 0x202E, 0xD800)]
    for typed, char in pairs:
        assert printable(typed) != printable(char)
        assert printable(typed) == "\\" + printable(char)


def _random_text(rng: random.Random) -> str:
    pieces = ["\\", "\\\\", "x", "u", "U", "n", "t", "r", "1b", "2028", "a", "f", " ", "\u00e9"]
    pieces += ["\u884c", "\U0001f680", "\u200d", "\ufe0f", "\U000e0067"]
    escaped = sorted(ESCAPED)
    parts: list[str] = []
    for _ in range(rng.randrange(25)):
        roll = rng.random()
        if roll < 0.35:
            parts.append(rng.choice(pieces))
        elif roll < 0.6:
            parts.append(chr(rng.choice(escaped)))
        elif roll < 0.8:
            parts.append(printable(chr(rng.choice(escaped))))
        else:
            parts.append(chr(rng.randrange(0x110000)))
    return "".join(parts)


def test_printable_is_read_back_and_holds_no_character_of_the_class() -> None:
    rng = random.Random(7919)
    texts = {_random_text(rng) for _ in range(12000)}
    assert len(texts) >= 10000
    for text in texts:
        shown = printable(text)
        assert decode(shown) == text, ascii(text)
        assert not any(ord(char) in ESCAPED for char in shown), ascii(text)


BACKSLASHED = "a\\x1bb\x1bc\\"
BACKSLASHED_SHOWN = "a\\\\x1bb\\x1bc\\\\"


def test_every_printed_line_writes_a_backslash_as_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert api.note_line("floor_provisional", BACKSLASHED) == (
        f"pairbench: note: floor_provisional: {BACKSLASHED_SHOWN}"
    )
    failed = GateRecord(name="quiet", mode="warn", status="fail", detail={"message": BACKSLASHED})
    assert api.gate_line(failed) == f"pairbench: check quiet: fail: {BACKSLASHED_SHOWN}"
    refusal = Refusal("E_USAGE", BACKSLASHED)
    assert refusal.message == BACKSLASHED
    assert refusal.to_json()["message"] == BACKSLASHED
    assert refusal.line == f"E_USAGE: {BACKSLASHED_SHOWN}"
    common.say(BACKSLASHED)
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", f"pairbench: {BACKSLASHED_SHOWN}\n")


def test_errors_reads_a_printed_text_back() -> None:
    rng = random.Random(104729)
    for _ in range(10000):
        text = _random_text(rng)
        shown = printable(text)
        assert unprintable(shown) == decode(shown) == text, ascii(text)


@pytest.mark.parametrize(
    "shown",
    [
        pytest.param("\\", id="lone-backslash"),
        pytest.param("a\\q", id="unknown-escape"),
        pytest.param("\\x1", id="short-x"),
        pytest.param("\\U0001f60", id="short-big-u"),
        pytest.param("\\x1B", id="upper-case-digits"),
    ],
)
def test_errors_refuses_a_text_printable_does_not_write(shown: str) -> None:
    with pytest.raises(ValueError, match=r"^no escape that printable writes at "):
        unprintable(shown)


def test_errors_reads_an_escape_printable_does_not_write_leniently() -> None:
    assert unprintable("\\x41\\u00e9\\U0001f680") == "A\u00e9\U0001f680"
    assert "never writes" in " ".join((unprintable.__doc__ or "").split())
