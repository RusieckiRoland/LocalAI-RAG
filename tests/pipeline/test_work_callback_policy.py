from code_query_engine.work_callback.policy import (
    CONTENT_ALL,
    CONTENT_DOCUMENTS_FORBIDDEN,
    GLOBAL_CALLBACK_ALLOWED,
    GLOBAL_CALLBACK_FORBIDDEN,
    GLOBAL_CALLBACK_PIPELINE_DECISION,
    PIPELINE_CALLBACK_ALLOWED,
    PIPELINE_CALLBACK_FORBIDDEN,
    resolve_callback_policy,
)


def test_global_forbidden_has_highest_priority() -> None:
    policy = resolve_callback_policy(
        runtime_cfg={"callback": GLOBAL_CALLBACK_FORBIDDEN},
        pipeline_settings={"callback": PIPELINE_CALLBACK_ALLOWED},
    )
    assert policy.enabled is False


def test_global_allowed_ignores_pipeline_callback_block() -> None:
    policy = resolve_callback_policy(
        runtime_cfg={"callback": GLOBAL_CALLBACK_ALLOWED},
        pipeline_settings={"callback": PIPELINE_CALLBACK_FORBIDDEN},
    )
    assert policy.enabled is True


def test_pipeline_decision_uses_pipeline_callback_value() -> None:
    allowed_policy = resolve_callback_policy(
        runtime_cfg={"callback": GLOBAL_CALLBACK_PIPELINE_DECISION},
        pipeline_settings={"callback": PIPELINE_CALLBACK_ALLOWED},
    )
    forbidden_policy = resolve_callback_policy(
        runtime_cfg={"callback": GLOBAL_CALLBACK_PIPELINE_DECISION},
        pipeline_settings={"callback": PIPELINE_CALLBACK_FORBIDDEN},
    )
    assert allowed_policy.enabled is True
    assert forbidden_policy.enabled is False


def test_content_flags_pipeline_can_only_restrict() -> None:
    policy = resolve_callback_policy(
        runtime_cfg={"callback_content": [CONTENT_ALL]},
        pipeline_settings={"callback_content": [CONTENT_DOCUMENTS_FORBIDDEN]},
    )
    assert policy.include_documents is False


def test_content_flags_global_restrictions_stay_enforced() -> None:
    policy = resolve_callback_policy(
        runtime_cfg={"callback_content": ["captioned", CONTENT_DOCUMENTS_FORBIDDEN]},
        pipeline_settings={"callback_content": [CONTENT_ALL]},
    )
    # captioned is ignored (removed); documents_forbidden still applies
    assert policy.include_documents is False
