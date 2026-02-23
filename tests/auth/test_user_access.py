from server.auth.user_access import DevUserAccessProvider, GroupPolicy


def test_dev_user_access_merges_groups_and_commands():
    policies = {
        "anonymous": GroupPolicy(acl_tags_any=[], allowed_pipelines=["ada"], allowed_commands=[], classification_labels_all=[]),
        "authenticated": GroupPolicy(
            acl_tags_any=["security"],
            classification_labels_all=["public", "tajne"],
            allowed_pipelines=["rejewski"],
            allowed_commands=["showDiagram"],
        ),
        "user:dev-user-1": GroupPolicy(
            acl_tags_any=["finance"],
            classification_labels_all=["wewnetrzne"],
            allowed_pipelines=["shannon"],
            allowed_commands=["ea_export"],
        ),
    }

    provider = DevUserAccessProvider(group_policies=policies)

    ctx = provider.resolve(user_id=None, token="Bearer dev-user:dev-user-1", session_id="s1")

    assert ctx.is_anonymous is False
    assert ctx.user_id == "dev-user-1"
    assert ctx.allowed_pipelines == ["rejewski", "shannon"]
    assert ctx.allowed_commands == ["showDiagram", "ea_export"]
    assert ctx.acl_tags_any == ["security", "finance"]
    assert ctx.classification_labels_all == ["public", "tajne", "wewnetrzne"]


def test_dev_user_access_anonymous_uses_anonymous_group_only():
    policies = {
        "anonymous": GroupPolicy(acl_tags_any=[], allowed_pipelines=["ada"], allowed_commands=[], classification_labels_all=[]),
        "authenticated": GroupPolicy(
            acl_tags_any=["security"],
            allowed_pipelines=["rejewski"],
            allowed_commands=["showDiagram"],
            classification_labels_all=["tajne"],
        ),
    }

    provider = DevUserAccessProvider(group_policies=policies)
    ctx = provider.resolve(user_id=None, token=None, session_id="s2")

    assert ctx.is_anonymous is True
    assert ctx.allowed_pipelines == ["ada"]
    assert ctx.allowed_commands == []
    assert ctx.acl_tags_any == []
    assert ctx.classification_labels_all == []


def test_generic_bearer_is_treated_as_authenticated_group() -> None:
    policies = {
        "anonymous": GroupPolicy(acl_tags_any=[], allowed_pipelines=["ada"], allowed_commands=[], classification_labels_all=[]),
        "authenticated": GroupPolicy(
            acl_tags_any=["security"],
            allowed_pipelines=["rejewski"],
            allowed_commands=["showDiagram"],
            classification_labels_all=["public"],
        ),
    }
    provider = DevUserAccessProvider(group_policies=policies)
    ctx = provider.resolve(user_id=None, token="Bearer some-prod-token", session_id="s3")

    assert ctx.is_anonymous is False
    assert ctx.group_ids == ["authenticated"]
    assert ctx.allowed_pipelines == ["rejewski"]
    assert ctx.acl_tags_any == ["security"]
