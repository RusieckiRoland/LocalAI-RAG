from server.app_config.app_config_service import AppConfigService
from server.auth.user_access import UserAccessContext
from server.pipelines.pipeline_access import PipelineAccessService


class FakeTemplatesStore:
    def load(self):
        return {
            "consultants": [
                {"id": "ada", "pipelineName": "ada"},
                {"id": "rejewski", "pipelineName": "rejewski"},
            ],
            "defaultConsultantId": "rejewski",
        }


class FakeAccessProvider:
    def __init__(self, allowed_pipelines):
        self._allowed_pipelines = allowed_pipelines

    def resolve(self, *, user_id, token, session_id):
        return UserAccessContext(
            user_id=None,
            is_anonymous=True,
            group_ids=["anonymous"],
            allowed_pipelines=self._allowed_pipelines,
            allowed_commands=[],
            acl_tags_any=[],
        )


def test_app_config_filters_consultants_by_allowed_pipelines():
    service = AppConfigService(
        templates_store=FakeTemplatesStore(),
        access_provider=FakeAccessProvider(["ada"]),
        pipeline_access=PipelineAccessService(),
        snapshot_registry=None,
        pipeline_snapshot_store=None,
        snapshot_policy="single",
    )

    cfg = service.build_app_config(runtime_cfg={"repo_name": "nopCommerce", "project_root": "."}, session_id="s", auth_header="")

    consultants = cfg.get("consultants") or []
    assert [c.get("id") for c in consultants] == ["ada"]
    assert cfg.get("defaultConsultantId") == "ada"
    assert consultants[0].get("snapshotSetId") is None
    assert consultants[0].get("snapshots") == []
