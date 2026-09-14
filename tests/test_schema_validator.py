import pytest
from pydantic import BaseModel

from smart_llm.base import LLMResponse
from smart_llm.security.schema_validator import (
    OutputSchemaValidator,
    SchemaValidationError,
)


# Test schemas
class SimpleSchema(BaseModel):
    name: str
    score: int


class SchemaWithDefaults(BaseModel):
    name: str
    score: int = 0
    tags: list[str] = []


class NestedSchema(BaseModel):
    class Inner(BaseModel):
        value: int

    name: str
    details: Inner


class OptionalSchema(BaseModel):
    name: str
    description: str | None = None


@pytest.fixture
def make_response():
    def _make(data, provider="openai", metadata=None):
        return LLMResponse(data=data, provider=provider, metadata=metadata or {})

    return _make


class TestSchemaValidatorRaise:
    """Tests for on_failure='raise' (default)."""

    def test_valid_data_passes(self, make_response):
        tool = OutputSchemaValidator(schema=SimpleSchema)
        resp = make_response({"name": "test", "score": 95})
        result = tool.run(resp)
        assert result.data["name"] == "test"
        assert result.data["score"] == 95
        assert result.metadata["schema_validated"] is True
        assert result.metadata["schema_name"] == "SimpleSchema"

    def test_missing_field_raises(self, make_response):
        tool = OutputSchemaValidator(schema=SimpleSchema)
        resp = make_response({"name": "test"})  # missing "score"
        with pytest.raises(SchemaValidationError) as exc_info:
            tool.run(resp)
        assert len(exc_info.value.validation_errors) > 0

    def test_wrong_type_raises(self, make_response):
        tool = OutputSchemaValidator(schema=SimpleSchema)
        resp = make_response({"name": "test", "score": "not_a_number"})
        with pytest.raises(SchemaValidationError):
            tool.run(resp)

    def test_extra_fields_preserved(self, make_response):
        """Extra fields not in schema should be dropped by Pydantic validation."""
        tool = OutputSchemaValidator(schema=SimpleSchema)
        resp = make_response({"name": "test", "score": 95, "extra": "field"})
        result = tool.run(resp)
        assert result.data["name"] == "test"

    def test_nested_schema_valid(self, make_response):
        tool = OutputSchemaValidator(schema=NestedSchema)
        resp = make_response({"name": "test", "details": {"value": 42}})
        result = tool.run(resp)
        assert result.data["details"]["value"] == 42

    def test_nested_schema_invalid(self, make_response):
        tool = OutputSchemaValidator(schema=NestedSchema)
        resp = make_response({"name": "test", "details": {"value": "not_int"}})
        with pytest.raises(SchemaValidationError):
            tool.run(resp)


class TestSchemaValidatorWarn:
    """Tests for on_failure='warn'."""

    def test_invalid_data_warns(self, make_response):
        tool = OutputSchemaValidator(schema=SimpleSchema, on_failure="warn")
        resp = make_response({"name": "test"})  # missing "score"
        result = tool.run(resp)
        assert result.metadata["schema_validated"] is False
        assert "schema_warnings" in result.metadata
        assert len(result.metadata["schema_warnings"]) > 0

    def test_valid_data_passes(self, make_response):
        tool = OutputSchemaValidator(schema=SimpleSchema, on_failure="warn")
        resp = make_response({"name": "test", "score": 95})
        result = tool.run(resp)
        assert result.metadata["schema_validated"] is True


class TestSchemaValidatorCoerce:
    """Tests for on_failure='coerce'."""

    def test_fills_defaults(self, make_response):
        tool = OutputSchemaValidator(schema=SchemaWithDefaults, on_failure="coerce")
        resp = make_response({"name": "test"})  # missing score and tags
        result = tool.run(resp)
        assert result.data["name"] == "test"
        assert result.data["score"] == 0
        assert result.data["tags"] == []
        assert result.metadata["schema_coerced"] is True

    def test_coerce_fails_when_required_missing(self, make_response):
        tool = OutputSchemaValidator(schema=SimpleSchema, on_failure="coerce")
        resp = make_response({"score": 95})  # missing required "name", no default
        with pytest.raises(SchemaValidationError):
            tool.run(resp)

    def test_optional_fields_default_to_none(self, make_response):
        tool = OutputSchemaValidator(schema=OptionalSchema, on_failure="coerce")
        resp = make_response({"name": "test"})
        result = tool.run(resp)
        assert result.data["name"] == "test"
        assert result.data["description"] is None


class TestSchemaValidatorInit:
    """Tests for constructor validation."""

    def test_invalid_schema_type_raises(self):
        with pytest.raises(TypeError):
            OutputSchemaValidator(schema=dict)

    def test_invalid_on_failure_raises(self):
        with pytest.raises(ValueError, match="Invalid on_failure"):
            OutputSchemaValidator(schema=SimpleSchema, on_failure="explode")

    def test_preserves_existing_metadata(self, make_response):
        tool = OutputSchemaValidator(schema=SimpleSchema)
        resp = make_response(
            {"name": "test", "score": 1},
            metadata={"agent_name": "myagent"},
        )
        result = tool.run(resp)
        assert result.metadata["agent_name"] == "myagent"
        assert result.metadata["schema_validated"] is True
