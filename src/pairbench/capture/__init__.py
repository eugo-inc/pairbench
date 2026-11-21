# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Captures on disk: the writer and reader of ``capture.jsonl``, the text input format, pooling.

* ``writer``: appends the records of a run, flushed and synced after each one,
  and ends the file with a record that carries the hash of everything before it;
* ``reader``: the built-in reader ``jsonl`` of that file. A torn last line and a
  missing or broken end record are detected;
* ``text``: the built-in reader ``text`` of the simple text input format, and
  ``project``, a two-sided view of a run of several sides;
* ``pool``: what reading several capture files needs at the level of files.

Importing this package imports none of its modules.
"""
