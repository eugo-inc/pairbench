# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Last-level cache domains from a synthetic CPU tree."""

from __future__ import annotations

from typing import Any

from pairbench.gates.cache import cache_domains, domain_lists, last_level_domain, sharing_cache


def test_last_level_is_the_highest_data_or_unified_cache(tree: Any) -> None:
    tree.cache(0, 0, 1, "Data", "0")
    tree.cache(0, 1, 1, "Instruction", "0")
    tree.cache(0, 2, 2, "Unified", "0-1")
    tree.cache(0, 3, 3, "Unified", "0-7")
    assert last_level_domain(tree.root, 0) == frozenset(range(8))


def test_an_instruction_cache_is_never_the_last_level(tree: Any) -> None:
    tree.cache(0, 0, 1, "Data", "0")
    tree.cache(0, 1, 4, "Instruction", "0-15")
    assert last_level_domain(tree.root, 0) == frozenset({0})


def test_domains_of_the_machine_in_the_order_of_their_lowest_cpu(tree: Any) -> None:
    tree.online("0-7")
    tree.llc([[4, 5, 6, 7], [0, 1, 2, 3]])
    domains = cache_domains(tree.root)
    assert domain_lists(domains or ()) == ("0-3", "4-7")


def test_domains_touching_a_pinned_set(tree: Any) -> None:
    tree.online("0-11")
    tree.llc([[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]])
    assert domain_lists(cache_domains(tree.root, {5, 6}) or ()) == ("4-7",)
    assert domain_lists(cache_domains(tree.root, {3, 4}) or ()) == ("0-3", "4-7")


def test_sharing_cache_holds_the_pinned_set_and_its_domains(tree: Any) -> None:
    tree.online("0-7")
    tree.llc([[0, 1, 2, 3], [4, 5, 6, 7]])
    assert sharing_cache(tree.root, frozenset({1})) == frozenset({0, 1, 2, 3})


def test_unreadable_topology_is_none(tree: Any) -> None:
    tree.online("0-3")
    assert cache_domains(tree.root) is None
    assert sharing_cache(tree.root, frozenset({1})) is None
    assert last_level_domain(tree.root, 9) is None
