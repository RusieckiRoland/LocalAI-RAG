from server.auth.user_access import DevUserAccessProvider, GroupPolicy


def test_dev_user_access_merges_groups_and_commands():
    policies = {
        "anonymous": GroupPolicy(acl_tags_all=[], allowed_pipelines=["ada"], allowed_commands=[]),
        "authenticated": GroupPolicy(
            acl_tags_all=["security"],
            allowed_pipelines=["rejewski"],
            allowed_commands=["showDiagram"],
        ),
        "user:dev-user-1": GroupPolicy(
            acl_tags_all=["finance"],
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
    assert ctx.acl_tags_all == ["security", "finance"]


def test_dev_user_access_anonymous_uses_anonymous_group_only():
    policies = {
        "anonymous": GroupPolicy(acl_tags_all=[], allowed_pipelines=["ada"], allowed_commands=[]),
        "authenticated": GroupPolicy(acl_tags_all=["security"], allowed_pipelines=["rejewski"], allowed_commands=["showDiagram"]),
    }

    provider = DevUserAccessProvider(group_policies=policies)
    ctx = provider.resolve(user_id=None, token=None, session_id="s2")

    assert ctx.is_anonymous is True
    assert ctx.allowed_pipelines == ["ada"]
    assert ctx.allowed_commands == []
    assert ctx.acl_tags_all == []
