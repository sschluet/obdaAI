"""Same path language as the old lookahead, with no unsupported regex constructs."""

import itertools
import re
import string

import pytest
from hub.agent_path_grammar import ha_read_path_pattern


@pytest.mark.parametrize(
    "prefixes",
    [
        ["/"],
        ["/api/"],
        ["/API/"],
        ["/api/states/"],
        ["/api/webhook/"],
        ["/api/webhook/", "/api/states/"],
        ["/api/", "/outside/"],
    ],
)
def test_positive_language_preserves_scope_and_blocks_all_case_variants(prefixes):
    pattern = ha_read_path_pattern(prefixes)
    assert pattern is None or ("(?!" not in pattern and "(?<" not in pattern)
    paths = {
        "",
        "/",
        "/api",
        "/api/",
        "/api/states/",
        "/outside/test",
        "/api/webhooks",
        "/api/webhookx/a",
        "/api/webhook/secret",
        "/api/webhook%2Fsecret",
        "/API/states/",
    }
    for variant in itertools.product(
        *[(c.lower(), c.upper()) if c.isalpha() else (c,) for c in "/api/webhook"]
    ):
        path = "".join(variant)
        paths.update({path, path + "/", path + "/trigger", path + "x"})
    for length in range(len("/api/webhook") + 1):
        prefix = "/api/webhook"[:length]
        paths.add(prefix)
        paths.update(prefix + c for c in string.ascii_letters + string.digits + "_.~/-")
    for path in paths:
        expected = (
            any(path.startswith(p) for p in prefixes)
            and bool(re.fullmatch(r"[A-Za-z0-9_.~/-]+", path))
            and path.casefold().rstrip("/") != "/api/webhook"
            and not path.casefold().startswith("/api/webhook/")
        )
        assert bool(pattern and re.fullmatch(pattern, path)) == expected, path


def test_no_safe_prefix_or_invalid_scope_does_not_create_a_broader_pattern():
    assert ha_read_path_pattern(["/api/webhook/", "/API/WEBHOOK/nested/"]) is None
    assert ha_read_path_pattern([]) is None
    with pytest.raises(ValueError):
        ha_read_path_pattern(["api/"])
