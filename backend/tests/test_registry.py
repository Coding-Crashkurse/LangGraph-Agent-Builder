import pytest

from graphforge.components.base import BaseComponent, ComponentConfig
from graphforge.components.registry import ComponentRegistry, DuplicateComponentError


def test_builtin_palette_loaded(loaded_registry):
    names = set(loaded_registry.all())
    assert {
        "llm_agent",
        "llm_call",
        "pgvector_retriever",
        "llm_router",
        "human_approval",
        "human_input",
        "mcp_toolset",
        "set_data",
    } <= names
    assert "fake_llm" in names  # include_testing=True


def test_testing_components_excluded_without_flag(loaded_registry):
    loaded_registry.load(include_testing=False)
    assert "fake_llm" not in loaded_registry.all()
    loaded_registry.load(include_testing=True)  # restore for other tests


def test_payload_shape(loaded_registry):
    payload = {item["name"]: item for item in loaded_registry.payload()}
    agent = payload["llm_agent"]
    assert agent["kind"] == "node"
    assert agent["accepts_attachments"] == ["tools"]
    assert "properties" in agent["config_json_schema"]

    router = payload["llm_router"]
    assert router["kind"] == "router"
    assert router["outputs_from_config"] == "labels"

    approval = payload["human_approval"]
    assert approval["outputs_static"] == ["approved", "rejected"]

    toolset = payload["mcp_toolset"]
    assert toolset["kind"] == "tool_provider"
    assert toolset["attachment_kind"] == "tools"


def test_duplicate_names_rejected():
    fresh = ComponentRegistry()

    class ConfigA(ComponentConfig):
        pass

    class CompA(BaseComponent):
        name = "dup"
        display_name = "A"
        description = "a"
        category = "io"
        config_model = ConfigA

        def build(self, config, ctx):  # pragma: no cover
            raise NotImplementedError

    class CompB(BaseComponent):
        name = "dup"
        display_name = "B"
        description = "b"
        category = "io"
        config_model = ConfigA

        def build(self, config, ctx):  # pragma: no cover
            raise NotImplementedError

    fresh.add(CompA)
    with pytest.raises(DuplicateComponentError):
        fresh.add(CompB)
