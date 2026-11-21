# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Each place that says what a shared results document never holds gives its exceptions.

A results document holds no host name, user name, path outside the run folder
or value of the environment, except an image reference the user asks for and
the forms the security policy lists as known limits of the shown command. Every
file that says what results never hold is listed here; each names both
exceptions and links the known limits, and a page of the documentation site
links them by a relative link that the site's build checks and rewrites.

The same is said in other words: that the shown command or a shared file holds
nothing that identifies the machine, no host and no user, or is safe to share.
Wherever the source, the documentation, the skill, the README, ``llms.txt`` or
a schema says it of what the shared files hold, it names the known limits; a
place that says it of something else, which no form of the shown command
reaches, is listed with its subject.
"""

from __future__ import annotations

import inspect
import io
import re
import tokenize
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pairbench.mcp import server
from pairbench.model import Provenance, RunInfo
from pairbench.results import load_schema

SECURITY = "SECURITY.md"
LIMITS_HEADING = "Known limits of the shown command"
HASH_LIMITS_HEADING = "Known limits of the hashes"
# The anchor a heading gets: its words in small letters, joined by hyphens.
LIMITS_ANCHOR = "-".join(LIMITS_HEADING.lower().split())
LIMITS_ANCHORS = (LIMITS_ANCHOR, "-".join(HASH_LIMITS_HEADING.lower().split()))
# What a place says results never hold, in each spelling the files use.
CLAIM = re.compile(r"no host ?names?, (?:an? )?user ?names?|never contain an? host ?name")
# Every file that says it. A loud note's message (``pairbench.api.Notify``) is held to
# "no host, no user", which no form of the shown command is an exception to.
MARKDOWN_PLACES = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/concepts.md",
    "docs/licence.md",
    "docs/method/reporting-checklist.md",
    "docs/reference/results-schema.md",
)
SERVER = "src/pairbench/mcp/server.py"
IMAGE_REFERENCE = re.compile(r"an image reference (?:you ask|the user asks) for")
LINK = re.compile(r"\]\(([^)\s]+)\)")
# A file of the repository named by its address on the forge, in any form: an inline link, a
# reference definition, an autolink, the address alone, with or without its scheme, or a link
# written in HTML; on any page of the forge that shows a file or on its host of raw files; in any
# capitals. A page of the site names such a file by its path, which the build turns into that
# address.
REPOSITORY_ADDRESS = re.compile(
    r"github\.com/eugo-inc/pairbench/(?:blob|tree|blame|raw)/"
    r"|raw\.githubusercontent\.com/eugo-inc/pairbench/",
    re.IGNORECASE,
)
# A file of the repository named by its address in each form a page can write it: an inline link,
# a reference definition, an autolink, the address alone (after a parenthesis too, and with www.
# and no scheme), a link written in HTML, other capitals, the blame and raw pages and the host of
# raw files; and the same file named by its path, and a page of the forge that shows no file.
BY_ADDRESS = (
    "the [policy](https://github.com/eugo-inc/pairbench/blob/main/SECURITY.md)",
    "[policy]: https://github.com/eugo-inc/pairbench/blob/main/SECURITY.md",
    "see <https://github.com/eugo-inc/pairbench/blob/main/SECURITY.md>",
    "see https://github.com/eugo-inc/pairbench/tree/main/showcases for more",
    "the policy (https://github.com/eugo-inc/pairbench/blob/main/SECURITY.md)",
    'the <a href="https://github.com/eugo-inc/pairbench/blob/main/SECURITY.md">policy</a>',
    "see www.github.com/eugo-inc/pairbench/tree/main/showcases for more",
    "see HTTPS://GitHub.com/Eugo-Inc/PairBench/blob/main/SECURITY.md",
    "see https://github.com/eugo-inc/pairbench/blame/main/SECURITY.md",
    "see https://github.com/eugo-inc/pairbench/raw/main/SECURITY.md",
    "see https://raw.githubusercontent.com/eugo-inc/pairbench/main/SECURITY.md",
)
NOT_BY_ADDRESS = (
    "the [policy](../../SECURITY.md) and [showcases](../../showcases/)",
    "report it at https://github.com/eugo-inc/pairbench/issues",
)
# The link the reference page writes, the page it is written in, and the address the build
# turns it into.
WRITTEN = ("reference/results-schema.md", f"../../{SECURITY}#{LIMITS_ANCHOR}")
BUILT = f"https://github.com/eugo-inc/pairbench/blob/main/{SECURITY}#{LIMITS_ANCHOR}"
# A host or a user named as such, in each spelling: "host name", "hostname", "user names",
# "usernames", in code quotes or not.
WHO_NAMED = r"`?(?:host|user)[ -]?names?\b`?"
# A host or a user in each spelling: a named one, "hosts", "users", or "host" or "user" alone
# where no hyphen, no "'s" and no word but "or", "and", "nor" or "identity" follows, so "a host
# header", "the host field" and "the user's code" are a part of something else.
WHO = (
    r"`?(?:(?:host|user)(?:[ -]?names?|s)\b`?"
    r"|(?:host|user)\b`?(?!-)(?!['\u2019]s\b)(?!\s+(?!(?:or|and|nor|identity)\b)[a-z]))"
)
# A verb of holding or showing, as written after "never" and as written after "not"; and as
# written in the passive.
HOLDING = (
    r"(?:contains?|holds?|names?|shows?|includes?|carr(?:y|ies)|keeps?|records?|stores?"
    r"|writes?|prints?|exposes?|reveals?|saves?)"
)
TO_HOLD = (
    r"(?:contain|hold|name|show|include|carry|keep|record|store|write|print|expose|reveal|save)"
)
PASSIVE = r"(?:written|recorded|kept|stored|shown|printed|included|saved|exposed|revealed|held)"
# What may stand between the verb and the host or user: a space, or the colon of a lead-in and
# the marker of the list item after it; then an article or "any".
BETWEEN = r"(?::\s*(?:(?:\d+\.|[-*])\s+)?|\s+)(?:(?:any|an?|the|your)\s+)?"
# A helper verb that says the verb after it does not happen.
NOT_DONE = (
    r"(?:(?:does|do|did|will|must|can|should|may|shall|would|could)"
    r"(?: not|n['\u2019]t|\s+never)|cannot|won['\u2019]t)"
)
# What a place says a shared file or the shown command holds: every wording the tree uses, and
# the families of words a new sentence could use for the same claim, whatever the sentence is
# about. A family is "no" before a host or a user and then another ("no hostname, username",
# "no host name and no user name"), or "no" before one after "and", "or" or a comma; a verb of
# holding or showing with "never" or a helper verb and "not" before it, then a host or a user;
# "has no" and a host name or user name; a host or a user "is never" written, or "no" host or
# user "is" written; "free of", "neither", "omits" or "stripped of" before a host or a user;
# "hides" before a host name or a user name in the same clause, with no "keeps", "shows" or
# "leaves" between; "safe to" share, publish or post; a verb of identifying with the machine,
# the host or the computer, or "not" before it; "machine-specific"; and leaking the host, the
# machine or a user name.
HOLDS_NOTHING = re.compile(
    r"no host name, (?:a )?user name|never contain a host name|no host, no user"
    rf"|\bno {WHO},? (?:(?:and|or) )?(?:no )?{WHO}"
    rf"|(?:,|\band|\bor) no {WHO}"
    r"|safe to (?:share|publish|post)"
    r"|identif(?:y|ies) (?:the|your|this) (?:machine|host|computer)"
    r"|not identify (?:a|the|your) (?:machine|host|computer)"
    rf"|\bnever {HOLDING}{BETWEEN}{WHO}"
    rf"|\b{NOT_DONE} {TO_HOLD}{BETWEEN}{WHO}"
    rf"|\b(?:has|have) no {WHO_NAMED}"
    rf"|\bno {WHO} (?:is|are) (?:ever )?{PASSIVE}"
    rf"|\b{WHO} (?:is|are) (?:never|not) (?:ever )?{PASSIVE}"
    rf"|\bfree of (?:any )?{WHO}"
    rf"|\bneither (?:(?:a|an|the|any|your)\s+)?{WHO}"
    rf"|\bomits?{BETWEEN}{WHO}|\bstripped of{BETWEEN}{WHO}"
    rf"|\bhides?\b(?:(?!\b(?:keeps?|shows?|leaves?)\b)[^.;:]){{0,80}}?\b{WHO_NAMED}"
    rf"|machine-specific|\bleak(?:s|ing|ed)? (?:the |your |a |any )?(?:machine|{WHO})",
    re.IGNORECASE,
)
# A shared file or the shown command, named in a sentence: the subject of the claim.
SHARED = re.compile(
    r"\bresults\b|\breport\.html\b|\bshared (?:files?|results)\b"
    r"|\b(?:shown|recorded) command\b|\b(?:the|this|that) command\b|\breproduce line\b",
    re.IGNORECASE,
)
# A word that says a thing is not there, and a verb that takes a thing away.
NOT_THERE = (
    r"(?:\b(?:no|never|not|nothing|neither|nor|without|free of|clean of|scrubbed of"
    r"|stripped of|no trace of)\b|n['\u2019]t\b)"
)
TAKES_AWAY = r"(?:drops?|masks?|removes?|redacts?|omits?|strips?|scrubs?|leaves?\s+out)"
# The machine itself, as a claim names it.
MACHINE = r"(?:machine|computer)\b"
# What says a host or a user is gone, said right after it, and the verb that may stand between.
GONE = (
    r"(?:never|not|removed|redacted|scrubbed|stripped|dropped|masked|hidden|omitted"
    r"|left out|kept out|out of)"
)
BEING = r"(?:is|are|do|does|did|will|must|can|stays?|remains?|gets?|goes|go)"
# What stands between two words of one clause: a blank, a quote, a bracket, a hyphen, or a dot
# inside a file name; never a comma, a colon or a semicolon.
WITHIN = r"(?:[\s`'\u2019\"()-]|\.(?=\w))+"
# Families that say the claim only in a sentence that names a shared file or the shown command
# (``SHARED``), since the same words say something else of a client, a server or a side: a verb
# of holding or showing with "no" after it, or "without", before a host or a user; a word of
# ``NOT_THERE`` up to six words before one in the same clause; a verb of ``TAKES_AWAY`` right
# before one; a host or a user, or two joined by "and" or "or", that "never" appear, "are
# removed", "stay out of" or "don't" appear; keeping a host or a user out; and a verb of holding
# with "no" before the machine, or a verb of naming or identifying it after a word of
# ``NOT_THERE`` in the same clause.
ABOUT_SHARED = re.compile(
    rf"\b{HOLDING} no {MACHINE}"
    rf"|{NOT_THERE}(?:{WITHIN}\w+){{0,6}}?{WITHIN}(?:names?|identif(?:y|ies))\s+"
    rf"(?:(?:the|your|this|a|any)\s+)?{MACHINE}"
    rf"|\b{HOLDING} no {WHO}"
    rf"|\bwithout (?:(?:a|an|the|any|your)\s+)?{WHO_NAMED}"
    rf"|{NOT_THERE}(?:{WITHIN}\w+){{0,6}}?{WITHIN}{WHO}"
    rf"|\b{TAKES_AWAY}\s+(?:(?:the|any|a|an|all|your)\s+)?{WHO}"
    rf"|{WHO}(?:\s+(?:and|or)\s+{WHO})?\s+(?:{BEING}\s+)?(?:(?:all|also|always|ever)\s+)?{GONE}\b"
    rf"|{WHO}\s+{BEING}n['\u2019]t\b"
    rf"|\bkeeps?\s+(?:(?:the|any|your)\s+)?{WHO}\s+out\b",
    re.IGNORECASE,
)


def says_it(text: str) -> bool:
    """Whether a text says what a shared file or the shown command holds: a family of
    ``HOLDS_NOTHING``, or one of ``ABOUT_SHARED`` in a text that names a shared file or the
    command."""
    if HOLDS_NOTHING.search(text):
        return True
    return SHARED.search(text) is not None and ABOUT_SHARED.search(text) is not None


# Each wording, as a place writes it.
WORDINGS = (
    "It holds no host name, user name, path outside the run folder",
    "they hold no host name, a user name",
    "never contain a host name, a user name",
    "Nothing in it identifies the machine",
    "with nothing that identifies the machine",
    "a reason that names nothing which identifies the machine",
    "and holds no host, no user, no image reference",
    "results.json and results.md stay safe to share",
    # Each family of other words a new sentence could use for the same claim.
    "results.json never names a host",
    "the shown command never contains a host name",
    "results.json holds no host name",
    "the command shows no user name",
    "results.md is safe to publish",
    "nothing in it identifies your machine",
    "the shared files hold nothing that identifies the host",
    "side identity is limited to what does not identify a machine",
    "the reproduce line keeps nothing machine-specific",
    "share results.json without leaking the host",
    # One-word spellings, plurals, "no ... and no ...", other verbs and a lead-in with its list.
    "results.json never contains a hostname",
    "The shown command never names the username of whoever ran it",
    "results.md holds no hostnames",
    "The shared files contain no usernames",
    "results.json has no hostname and no username",
    "They never contain: 1. a hostname 2. a username",
    "There is no host name and no user name in results.md",
    "The results never include: - the hostname - the username",
    "results.json does not contain a hostname",
    "The reproduce line doesn't show the username",
    "results.md will never record a host name",
    "Shared results hold no hostnames, usernames or paths outside the run folder",
    "The shown command keeps no users",
    "Shared results contain no hostnames and no usernames",
    "results.json never shows any hostname",
    "It never holds the user names of the machine",
    "The files it writes include no usernames or hostnames",
    "The results never contain usernames",
    "results.json never leaks hostnames",
    "The shared files must not hold a username",
    "the rules: no runtime dependencies, no host identity in results",
    # Other verbs, other helpers, "has no", the passive, "free of", "neither", "omits",
    # "stripped of", "without" and "hide", each in a sentence of its own.
    "No hostname is written to results.json",
    "results.md is free of host names",
    "The shared files hold neither the host name nor the user name",
    "results.json won't contain your hostname",
    "The shared results cannot contain a user name",
    "results.json has no hostname",
    "pairbench never writes the hostname into results.json",
    "The report never prints your username",
    "results.json does not expose the host name",
    "Shared results are written without the hostname or the username",
    "results.json omits the host name and the user name",
    "neither a host name nor a user name is stored in results.json",
    "The results carry no host names or user names",
    "results.json shall not contain a hostname",
    "The command as typed, with no hostname or username",
    "The shown command is stripped of the hostname",
    "This field never holds `hostname` output",
    "The hostname is never recorded here",
    "they hide the values of credential-like names and headers, host names and paths",
    # Restatements in other verbs and orders: a host or a user after "no" or "nothing", taken
    # away, or said to be gone after it, in a sentence about a shared file or the command.
    "results.json lists no hostnames.",
    "Hostnames never appear in results.json.",
    "No user name ends up in the shared files.",
    "The shared files are scrubbed of host names.",
    "results.md mentions no host or user.",
    "Host names and user names are removed from the shown command.",
    "The shown command drops hostnames and usernames.",
    "Nothing in results.json names the host.",
    "Hostnames are redacted from results.json.",
    "pairbench keeps host names out of results.json.",
    "Host names stay out of the shared files.",
    "The results do not mention the host.",
    "The shared files don't list user names.",
    "results.json gives away no hostname.",
    "The shown command masks the host name.",
    "results.json is clean of user names.",
    "No trace of the hostname is left in results.md.",
    "The shared files contain neither hostnames nor usernames.",
    "results.json reveals nothing about the host.",
    "Usernames are never part of the shared files.",
    "results.json carries no host names.",
    "The recorded command never spells out a username.",
    "No hostname makes it into results.md.",
    "Nothing in report.html points to the host.",
    "The shared files include neither the host nor the user.",
    "Host names don't appear in the results.",
    "results.md keeps hostnames out.",
    "The shown command never exposes a user name.",
    "User names are stripped from results.json.",
    "results.json does not record the hostname of the machine.",
    "The reproduce line omits the username.",
    "Hostnames are hidden in results.json.",
    "Results files contain no usernames at all.",
    "report.html redacts the host name.",
    "There is no hostname anywhere in results.json.",
    # The machine named, rather than identified, and a host or a user left out.
    "Nothing in results.json names the machine.",
    "The results name no machine.",
    "The shared files leave out host names and user names.",
)
# Words that are not the claim.
NOT_THE_CLAIM = (
    "the identify command of a side",
    "a host part no host name has",
    "results that identify a machine",
    "meant to be shared",
    "the link names no page of the site",
    "a host name the rules do not read",
    "the side names the host launcher",
    "a file address with a host and no path",
    "the path that follows the scheme with no host between",
    "a hostname the address names",
    "the username option takes no value",
    "a host or a user that the rules do not read",
    "Set the hostname with --host",
    "Pass the user name with --user when the server needs one",
    "The hostname must resolve before the run starts",
    "A run with no host given uses the loopback address",
    "The image names the user it runs as",
    "The remote side has no user account of its own",
    "The probe never contains a host header",
    "The client does not show the host field",
    "This page shows no host-specific settings",
    "An address with a path and no host is read as a file",
    "the password is hidden whole and each user name is shown",
    "it hides the password and keeps the user name",
    # Sentences of a client, a server or a side, and sentences of a shared file that say what
    # it shows, with the words a claim uses.
    "Without a host name, the client connects to the loopback address.",
    "The client shows no user name prompt when a password file is set.",
    "With no host name given, the client reads the socket path.",
    "The image lists no users of its own.",
    "Run the client without the hostname option to use a socket.",
    "A server with no hostname set listens on every address.",
    "The ssh side never names a host key file unless asked.",
    "Without a user name the database refuses the login.",
    "The probe does not show the host header.",
    "No user is needed for a local socket.",
    "The server takes its host name from the --host option.",
    "Pass --user to set the user name the client logs in as.",
    "A side without a hostname runs on this machine.",
    "results.json lists each side by the name you gave it.",
    "The results hold the median of each case.",
    "No host is contacted unless the workload asks for one.",
    "The client never resolves the hostname twice.",
    "results.md shows the user name you typed after --user, as the security policy lists.",
    "The command runs as the user who started pairbench.",
    "Without the hostname flag, redis-cli uses the loopback address.",
    "Without results.json, the host name is unknown.",
    "results.json shows a host written with no scheme as typed.",
    "The shown command keeps the host of an address with no scheme.",
    "results.json shows the user name but not the password.",
    "results.json names the machine class it ran on.",
    "The client leaves out the host name when it reads a socket.",
)
# A place points to the known limits of the security policy by the heading's words or its anchor.
KNOWN_LIMITS = re.compile(
    r"known limits of the (?:shown command|hashes)|known-limits-of-the-(?:shown-command|hashes)",
    re.IGNORECASE,
)
# Places that say it of something no form of the shown command reaches, each by the words that
# name its subject: a loud note's message, a refusal's message, a check's one-line reason, the
# machine record a capture keeps, a message a cleaning rule cannot read, the writer, and the
# places the launch-cost script measures its own fixed commands from.
OTHER_SUBJECTS = {
    "src/pairbench/api.py": (
        "The message reaches a document that is meant to be shared",
        '``detail["message"]`` is a one-line reason',
        "``machine_record`` holds nothing that identifies the machine beyond what a capture",
    ),
    "src/pairbench/errors.py": ("The message is printed on standard error",),
    "src/pairbench/gates/platform.py": ("``message`` is the one-line reason",),
    "src/pairbench/model.py": (
        "whoever writes a message that reaches a results document",
        '``detail["message"]``, when present, is a one-line reason',
    ),
    "src/pairbench/results/writer.py": ("The writer asks the machine for nothing",),
    "tools/launch_cost.py": ("The script measures from neutral places",),
    "docs/reference/python-names.md": (
        "The message is printed on standard error",
        '`detail["message"]` is a one-line reason',
    ),
}
SOURCE_SUFFIXES = frozenset({".py", ".json"})
# A claim in a comment, wrapped so the phrase breaks across two comment lines, and the block the
# search finds in it: the comment's words, without the code after it.
WRAPPED_COMMENT = (
    "    # The writer never contains a\n    # host name in what it writes.\n    WRITES = 1\n"
)
WRAPPED_CLAIM = "The writer never contains a host name in what it writes."
# Code whose words read like the claim, and the docstring and string after it, which say it.
CODE_AND_TEXT = (
    "halt = stop if stop is not None else host.kill\n"
    "\n"
    "def made_up():\n"
    '    """results.json lists no hostnames."""\n'
    '    return ("The shown command " "never names the host")\n'
)
CODE_AND_TEXT_BLOCKS = [
    '"""results.json lists no hostnames.""" "The shown command " "never names the host"'
]
# The kinds of token of a Python file that hold its words: comments and strings, in each form
# the tokenizer of the running Python gives a formatted string.
WORD_TOKENS = frozenset(
    kind
    for kind in (
        tokenize.COMMENT,
        tokenize.STRING,
        getattr(tokenize, "FSTRING_START", None),
        getattr(tokenize, "FSTRING_MIDDLE", None),
        getattr(tokenize, "FSTRING_END", None),
    )
    if kind is not None
)
# A heading of the security policy's lists of known limits: what stands under one is the
# exception itself.
LIMITS_SECTION = re.compile(r"^## Known limits of .*$", re.MULTILINE)
# The start of a list item.
LIST_ITEM = re.compile(r"\s*(?:[-*]|\d+\.)\s")
# The mark that starts a comment line of a Python file, with its indent and one space after it.
COMMENT_MARK = re.compile(r"(?m)^[ \t]*# ?")
# Where a sentence ends: a full stop, a question mark or an exclamation mark after anything but a
# blank or a digit alone (the "1." of a list item), then a blank. One inside a code span or after
# an abbreviation ends none.
SENTENCE_END = re.compile(r"(?<=[^\s\d][.!?])\s+")
ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.")
# A published page that says it must link the known limits in the same sentence: a Markdown file
# the documentation rules hold, or llms.txt.
LINKED_SUFFIXES = frozenset({".md"})
LINKED_NAMES = frozenset({"llms.txt"})
# A planted security policy and the page a planted claim is written in, below the root.
PLANTED_POLICY = f"# Security policy\n\n## {LIMITS_HEADING}\n\n- A made-up limit.\n"
PLANTED_PAGE = "docs/page.md"
PLANTED_LINK = f"../{SECURITY}#{LIMITS_ANCHOR}"
# Each planted claim, and whether the check refuses it on a published page: no exception, the
# exception in the next sentence, the exception's words with no link, and the exception linked
# in the same sentence.
PLANTED = (
    ("results.json lists no hostnames.", True),
    (f"results.json lists no hostnames. The [known limits]({PLANTED_LINK}) say more.", True),
    ("results.json lists no hostnames, except the known limits of the shown command.", True),
    (
        f"results.json lists no hostnames, except the forms the [policy]({PLANTED_LINK}) lists.",
        False,
    ),
)
# The same claims in a source file, which names the known limits and links nothing.
PLANTED_SOURCE = "src/made_up.py"
PLANTED_IN_SOURCE = (
    ('"""results.json lists no hostnames."""\n', True),
    ('"""results.json lists no hostnames. See Known limits of the shown command."""\n', True),
    (
        '"""results.json lists no hostnames, except the forms SECURITY.md lists under Known'
        ' limits of the shown command."""\n',
        False,
    ),
)
# The classes of the results document whose schema description says it. A schema describes a
# class by the first paragraph of its docstring, with the lines joined.
DESCRIBED = (RunInfo, Provenance)


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def blocks(text: str) -> list[str]:
    """The paragraphs and list items of a Markdown text, each with its lines joined.

    A paragraph that ends in a colon leads in the list after it, so it and the list's items
    are one block: "They never contain:" and "1. a hostname" say the claim together.
    """
    found: list[str] = []
    leads_in = False
    for part in re.split(r"\n\s*\n|\n(?=\s*(?:[-*]|\d+\.) )", text):
        if leads_in and LIST_ITEM.match(part):
            found[-1] = f"{found[-1]} {plain(part)}"
            continue
        found.append(plain(part))
        leads_in = found[-1].endswith(":")
    return found


def claims(text: str) -> list[str]:
    """Each paragraph or list item of a Markdown text that says what results never hold."""
    return [block for block in blocks(text) if CLAIM.search(block)]


def links_to_the_limits(
    repo_root: Path,
    place: str,
    block: str,
    anchors: tuple[str, ...] = (LIMITS_ANCHOR,),
    kit: Any = None,
) -> list[str]:
    """The links of a block that name one of ``anchors`` of the security policy: a path from
    the place, or, with ``kit``, an address of the repository's files on the forge."""
    found = []
    for target in LINK.findall(block):
        path, _, fragment = target.partition("#")
        if path.startswith("https://"):
            linked = kit.linked_file(repo_root, path) if kit is not None else None
            if linked is None:
                continue
        else:
            linked = (repo_root / place).parent / path if path else repo_root / place
        if linked.resolve() == (repo_root / SECURITY).resolve() and fragment in anchors:
            found.append(target)
    return found


def places(repo_root: Path, kit: Any) -> list[Path]:
    """Every file of the source, the documentation, the skill, the README and llms.txt."""
    found = set(kit.documents(repo_root))
    found.update((repo_root / "docs").rglob("*.md"))
    found.update(p for p in (repo_root / "src").rglob("*") if p.suffix in SOURCE_SUFFIXES)
    return sorted(found)


def python_words(text: str) -> str:
    """The comments and strings of a Python text, each on the lines it stands on, with the
    code taken out and the comment marks off, so a claim wrapped over comment lines reads as
    one sentence and code reads as nothing."""
    lines = [""] * (text.count("\n") + 2)
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type not in WORD_TOKENS:
            continue
        words = (
            COMMENT_MARK.sub("", token.string) if token.type == tokenize.COMMENT else token.string
        )
        for row, part in enumerate(words.split("\n"), start=token.start[0] - 1):
            lines[row] = f"{lines[row]} {part}" if lines[row] else part
    return "\n".join(lines)


def without_limits(text: str) -> str:
    """A Markdown text without its sections on the known limits, which are the exception."""
    parts = LIMITS_SECTION.split(text)
    return parts[0] + "".join(
        part[part.find("\n## ") :] if "\n## " in part else "" for part in parts[1:]
    )


def file_blocks(path: Path) -> list[str]:
    """The blocks of a file: its paragraphs and list items, or the lines of a JSON file, such
    as one description of a schema.

    Of a Python file only the comments and strings are read (``python_words``); of a Markdown
    file, all but the sections on the known limits (``without_limits``).
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        text = python_words(text)
    if path.suffix == ".md":
        text = without_limits(text)
    return [plain(line) for line in text.splitlines()] if path.suffix == ".json" else blocks(text)


def holds_nothing(path: Path) -> Iterator[str]:
    """Each block of a file that says what a shared file holds."""
    for block in file_blocks(path):
        if says_it(block):
            yield block


def sentences(block: str) -> list[str]:
    """The sentences of a block, split where ``SENTENCE_END`` says one ends."""
    found: list[str] = []
    start = 0
    for end in SENTENCE_END.finditer(block):
        before = block[start : end.start()]
        if block.count("`", 0, end.start()) % 2 or before.endswith(ABBREVIATIONS):
            continue
        found.append(before)
        start = end.end()
    found.append(block[start:])
    return [sentence for sentence in found if sentence]


def is_linked(path: Path, published: frozenset[Path]) -> bool:
    """Whether a file is a published page, whose claim links the known limits."""
    linked_kind = path.suffix in LINKED_SUFFIXES or path.name in LINKED_NAMES
    return linked_kind and path in published


def unexcepted(repo_root: Path, path: Path, *, linked: bool, kit: Any = None) -> list[str]:
    """Each sentence of a file that says what a shared file or the shown command holds and does
    not give the exception in the same sentence.

    On a published page the sentence links the known limits of the security policy; in source,
    a schema or a page the site does not publish, it names them. A block that names another
    subject (``OTHER_SUBJECTS``) is left out.
    """
    relative = path.relative_to(repo_root).as_posix()
    subjects = OTHER_SUBJECTS.get(relative, ())
    missing: list[str] = []
    for block in file_blocks(path):
        if any(subject in block for subject in subjects):
            continue
        for sentence in sentences(block):
            if not says_it(sentence):
                continue
            if linked:
                given = links_to_the_limits(repo_root, relative, sentence, LIMITS_ANCHORS, kit)
            else:
                given = KNOWN_LIMITS.findall(sentence)
            if not given:
                missing.append(f"{relative}: {sentence[:200]}")
    return missing


@pytest.mark.parametrize("wording", WORDINGS)
def test_each_wording_of_the_claim_is_found(wording: str) -> None:
    assert says_it(wording) is True


@pytest.mark.parametrize("words", NOT_THE_CLAIM)
def test_words_that_are_not_the_claim_are_not_found(words: str) -> None:
    assert says_it(words) is False


def test_a_block_is_split_into_sentences_outside_code_spans() -> None:
    block = (
        "`results.json` holds no host name. It names a side, e.g. `new`, by its name: "
        "1. a list item `a. B` stays. Is it shared? Yes!"
    )

    assert sentences(block) == [
        "`results.json` holds no host name.",
        "It names a side, e.g. `new`, by its name: 1. a list item `a. B` stays.",
        "Is it shared?",
        "Yes!",
    ]


@pytest.mark.parametrize(("claim", "refused"), PLANTED)
def test_a_planted_claim_on_a_page_needs_the_linked_exception_in_its_sentence(
    tmp_path: Path, claim: str, refused: bool
) -> None:
    (tmp_path / SECURITY).write_text(PLANTED_POLICY, encoding="utf-8")
    page = tmp_path / PLANTED_PAGE
    page.parent.mkdir(parents=True)
    page.write_text(f"---\ndescription: made up\n---\n\n{claim}\n", encoding="utf-8")

    found = unexcepted(tmp_path, page, linked=True)

    assert found == ([f"{PLANTED_PAGE}: {sentences(claim)[0]}"] if refused else [])


@pytest.mark.parametrize(("text", "refused"), PLANTED_IN_SOURCE)
def test_a_planted_claim_in_source_needs_the_named_exception_in_its_sentence(
    tmp_path: Path, text: str, refused: bool
) -> None:
    source = tmp_path / PLANTED_SOURCE
    source.parent.mkdir(parents=True)
    source.write_text(text, encoding="utf-8")

    found = unexcepted(tmp_path, source, linked=False)

    assert len(found) == (1 if refused else 0)


def test_a_claim_wrapped_over_comment_lines_is_found(tmp_path: Path) -> None:
    source = tmp_path / "writer.py"
    source.write_text(WRAPPED_COMMENT, encoding="utf-8")

    assert list(holds_nothing(source)) == [WRAPPED_CLAIM]


def test_of_a_python_file_only_the_comments_and_strings_are_read(tmp_path: Path) -> None:
    source = tmp_path / "made_up.py"
    source.write_text(CODE_AND_TEXT, encoding="utf-8")

    assert list(holds_nothing(source)) == CODE_AND_TEXT_BLOCKS


def test_the_sections_on_the_known_limits_are_left_out_of_a_page(tmp_path: Path) -> None:
    page = tmp_path / SECURITY
    page.write_text(
        "# Policy\n\nresults.json lists no hostnames.\n\n"
        f"## {LIMITS_HEADING}\n\nThe shown command keeps no host name typed as made up.\n\n"
        f"## {HASH_LIMITS_HEADING}\n\nThe shared files hold no user name of made-up form.\n\n"
        "## Other\n\nThe results never name the host.\n",
        encoding="utf-8",
    )

    assert list(holds_nothing(page)) == [
        "results.json lists no hostnames.",
        "The results never name the host.",
    ]


def test_every_claim_of_what_the_shared_files_hold_gives_the_exception_in_its_sentence(
    repo_root: Path, kit: Any
) -> None:
    searched = places(repo_root, kit)
    published = frozenset(kit.documents(repo_root))
    missing: list[str] = []
    for path in searched:
        missing += unexcepted(repo_root, path, linked=is_linked(path, published), kit=kit)

    assert {"README.md", "llms.txt", "skills/pairbench/SKILL.md"} <= {
        path.relative_to(repo_root).as_posix() for path in searched
    }
    assert missing == []


def test_each_place_of_another_subject_still_says_it(repo_root: Path) -> None:
    gone = [
        f"{relative}: {subject}"
        for relative, subjects in OTHER_SUBJECTS.items()
        for subject in subjects
        if not any(subject in block for block in holds_nothing(repo_root / relative))
    ]

    assert gone == []


@pytest.mark.parametrize("cls", DESCRIBED, ids=lambda cls: cls.__name__)
def test_the_schema_describes_the_class_in_the_words_of_its_docstring(cls: type) -> None:
    description = load_schema("results")["$defs"][cls.__name__]["description"]

    assert description == plain(inspect.cleandoc(cls.__doc__ or "").split("\n\n")[0])
    assert says_it(description) is True
    assert KNOWN_LIMITS.search(description) is not None


def test_the_security_policy_has_the_heading_the_places_link(repo_root: Path) -> None:
    text = (repo_root / SECURITY).read_text(encoding="utf-8")

    assert f"\n## {LIMITS_HEADING}\n" in text


@pytest.mark.parametrize("place", MARKDOWN_PLACES)
def test_each_place_names_both_exceptions_and_links_the_known_limits(
    repo_root: Path, place: str
) -> None:
    blocks = claims((repo_root / place).read_text(encoding="utf-8"))

    assert blocks != []
    assert [block for block in blocks if IMAGE_REFERENCE.search(block) is None] == []
    assert [block for block in blocks if not links_to_the_limits(repo_root, place, block)] == []
    assert [block for block in blocks if "The one exception" in block] == []


def test_the_tool_server_names_both_exceptions_and_the_known_limits(repo_root: Path) -> None:
    text = server.GLOSSARY["results"]

    assert CLAIM.search(text) is not None
    assert IMAGE_REFERENCE.search(text) is not None
    assert f"{SECURITY} of the source lists under {LIMITS_HEADING}" in text
    assert (repo_root / SECURITY).is_file()


def test_every_file_that_says_what_results_never_hold_is_a_listed_place(
    repo_root: Path, kit: Any
) -> None:
    files = [*kit.documents(repo_root), *sorted((repo_root / "src").rglob("*.py"))]
    saying = {
        path.relative_to(repo_root).as_posix()
        for path in files
        if CLAIM.search(plain(path.read_text(encoding="utf-8")))
    }

    assert saying == {*MARKDOWN_PLACES, SERVER}


@pytest.mark.parametrize("written", BY_ADDRESS)
def test_a_file_of_the_repository_named_by_its_address_is_found_in_each_form(
    written: str,
) -> None:
    assert REPOSITORY_ADDRESS.search(written) is not None


@pytest.mark.parametrize("written", NOT_BY_ADDRESS)
def test_a_file_of_the_repository_named_by_its_path_or_no_file_is_not_found(written: str) -> None:
    assert REPOSITORY_ADDRESS.search(written) is None


def test_no_page_of_the_site_links_a_file_of_the_repository_by_its_address(
    repo_root: Path, docs_site: ModuleType
) -> None:
    pages = docs_site.site_pages(repo_root)
    found = [
        page
        for page in pages
        if REPOSITORY_ADDRESS.search((repo_root / "docs" / page).read_text(encoding="utf-8"))
    ]

    assert found == []


def test_the_build_checks_the_link_to_the_known_limits_and_writes_its_address(
    repo_root: Path, docs_site: ModuleType
) -> None:
    linker = docs_site.Linker(
        repo_root, docs_site.read_address(repo_root), frozenset(docs_site.site_pages(repo_root))
    )
    page, written = WRITTEN

    assert linker.target(page, written) == BUILT
    with pytest.raises(docs_site.SiteError, match="names nothing in the repository"):
        linker.target(page, f"../../NO_{SECURITY}#{LIMITS_ANCHOR}")
