from __future__ import annotations

from tests.integration.retrival.helpers import is_visible


def test_is_visible_acl_only() -> None:
    permissions = {"acl_enabled": True, "security_enabled": False}
    meta = {"acl_allow": ["hr"]}
    assert (
        is_visible(
            meta,
            acl_any=["finance", "security"],
            labels_all=[],
            user_level=None,
            permissions=permissions,
        )
        is False
    )

    meta_public = {"acl_allow": []}
    assert (
        is_visible(
            meta_public,
            acl_any=["finance"],
            labels_all=[],
            user_level=None,
            permissions=permissions,
        )
        is True
    )


def test_is_visible_labels_only() -> None:
    permissions = {
        "acl_enabled": False,
        "security_enabled": True,
        "security_model": {"kind": "labels_universe_subset", "labels_universe_subset": {"allow_unlabeled": False}},
    }
    meta_ok = {"classification_labels": ["public"]}
    meta_bad = {"classification_labels": ["secret"]}

    assert (
        is_visible(
            meta_ok,
            acl_any=[],
            labels_all=["public", "internal"],
            user_level=None,
            permissions=permissions,
        )
        is True
    )
    assert (
        is_visible(
            meta_bad,
            acl_any=[],
            labels_all=["public", "internal"],
            user_level=None,
            permissions=permissions,
        )
        is False
    )


def test_is_visible_clearance_only() -> None:
    permissions = {
        "acl_enabled": False,
        "security_enabled": True,
        "security_model": {"kind": "clearance_level", "clearance_level": {"allow_missing_doc_level": False}},
    }
    meta_low = {"doc_level": 5}
    meta_high = {"doc_level": 20}

    assert (
        is_visible(
            meta_low,
            acl_any=[],
            labels_all=[],
            user_level=10,
            permissions=permissions,
        )
        is True
    )
    assert (
        is_visible(
            meta_high,
            acl_any=[],
            labels_all=[],
            user_level=10,
            permissions=permissions,
        )
        is False
    )
