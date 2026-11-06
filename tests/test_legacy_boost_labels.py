"""Only the boost-button labels our old code wrote to the registry get cleared."""

from cala.helpers import legacy_boost_label_overrides


def test_clears_labels_written_by_old_code():
    assert legacy_boost_label_overrides("Start 24h Boost", "mdi:play-circle") == {
        "name": None,
        "icon": None,
    }
    assert legacy_boost_label_overrides("Stop Boost", "mdi:stop-circle") == {
        "name": None,
        "icon": None,
    }


def test_keeps_user_overrides():
    assert legacy_boost_label_overrides("Hot water now", "mdi:fire") == {}
    assert legacy_boost_label_overrides("Hot water now", "mdi:play-circle") == {"icon": None}


def test_nothing_to_clear():
    assert legacy_boost_label_overrides(None, None) == {}
