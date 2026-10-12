"""The CI selector must not depend on the HA plugin's autouse fixture graph."""
from types import SimpleNamespace
from tests.conftest import _requires_home_assistant


def item(args=(), definitions=None, markers=(), explicit=False):
    return SimpleNamespace(
        _fixtureinfo=SimpleNamespace(argnames=args, name2fixturedefs={
            key: [SimpleNamespace(argnames=deps)]
            for key, deps in (definitions or {}).items()
        }),
        fixturenames=("hass", "ha_plugin_autouse"),
        iter_markers=lambda name: [SimpleNamespace(args=m) for m in markers],
        get_closest_marker=lambda name: explicit or None,
    )


def test_plugin_autouse_does_not_select_unit_tests():
    assert not _requires_home_assistant(item())


def test_direct_and_nested_hass_requests_are_selected():
    assert _requires_home_assistant(item(("hass",)))
    assert _requires_home_assistant(item(("wrapped",), {"wrapped": ("hass",)}))


def test_usefixtures_and_explicit_dynamic_marker_are_selected():
    assert _requires_home_assistant(item(markers=(("hass",),)))
    assert _requires_home_assistant(item(explicit=True))


def test_fixture_cycles_terminate_without_marking():
    assert not _requires_home_assistant(item(("a",), {"a": ("b",), "b": ("a",)}))
