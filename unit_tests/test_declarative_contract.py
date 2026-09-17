# ABOUTME: Unit tests for the declarative test contract (TEST_META) and stable test keys.
# ABOUTME: Lives outside tests/ so the comparator does not load it as a sandbox workload.
import ast
import os
import re

import comparator

resolve_test_meta = comparator.resolve_test_meta


def make_func(name="test_thing", meta=None, payload_raises=False):
    def func():
        if payload_raises:
            raise RuntimeError("payload builder must not be called for metadata")

    func.__name__ = name
    if meta is not None:
        func.meta = meta
    return func


def test_meta_resolves_slug_from_function_name_by_default():
    meta = resolve_test_meta(make_func())
    assert meta["slug"] == "thing"
    assert meta["single_run"] is False
    assert meta["info_test"] is False


def test_meta_from_attribute_wins_over_function_name():
    func = make_func(meta={"slug": "custom", "single_run": True, "info_test": True})
    meta = resolve_test_meta(func)
    assert meta["slug"] == "custom"
    assert meta["single_run"] is True
    assert meta["info_test"] is True


def test_single_run_detection_never_calls_payload():
    func = make_func(meta={"slug": "x", "single_run": True}, payload_raises=True)
    assert comparator.is_single_run_test(func) is True


def test_test_key_uses_slug():
    func = make_func(meta={"slug": "fft_performance"})
    assert comparator.test_key(func) == "test_fft_performance"


def test_registered_tests_have_valid_unique_slugs():
    slugs = [resolve_test_meta(func)["slug"] for func in comparator.defined_tests.values()]
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", slug) for slug in slugs)
    assert len(slugs) == len(set(slugs)), "slugs must be unique across tests"


def module_defines_test_function(path: str) -> bool:
    tree = ast.parse(open(path).read())
    return any(
        isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        for node in tree.body
    )


def test_ids_follow_sorted_filename_order():
    expected_slugs = []
    for filename in sorted(os.listdir("tests")):
        if (
            filename.endswith(".py")
            and not filename.startswith("__")
            and filename != "test_template.py"
            and module_defines_test_function(os.path.join("tests", filename))
        ):
            expected_slugs.append(filename[len("test_"):-len(".py")])

    actual_slugs = [
        resolve_test_meta(comparator.defined_tests[test_id])["slug"]
        for test_id in sorted(comparator.defined_tests)
    ]
    assert actual_slugs == expected_slugs


def test_declared_meta_flags_present():
    by_slug = {resolve_test_meta(func)["slug"]: resolve_test_meta(func) for func in comparator.defined_tests.values()}
    assert by_slug["system_info"]["info_test"] is True
    assert by_slug["system_info"]["single_run"] is True
    assert by_slug["startup_time"]["info_test"] is True
    assert by_slug["calculate_primes"]["single_run"] is False
    assert by_slug["container_stability"]["single_run"] is True
