"""
Output schema validation tool for LLM responses.

Validates LLM response data against a user-provided Pydantic model
to ensure responses conform to expected structure.
"""

from typing import Any
import logging

from pydantic import BaseModel, ValidationError

from ..base import LLMResponse, OutputTool

logger = logging.getLogger(__name__)


class SchemaValidationError(ValueError):
    """Raised when LLM response data fails schema validation."""

    def __init__(self, message: str, validation_errors: list[Any]):
        self.validation_errors = validation_errors
        super().__init__(message)


class OutputSchemaValidator(OutputTool):
    """
    Validates LLM response data against a Pydantic model schema.

    Args:
        schema: A Pydantic BaseModel class defining the expected response structure.
        on_failure: Behavior when validation fails:
            - "raise": Raise SchemaValidationError (default).
            - "warn": Log a warning and add errors to response metadata.
            - "coerce": Attempt to fill defaults for missing fields, raise if still invalid.
    """

    def __init__(self, schema: type[BaseModel], on_failure: str = "raise"):
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError(
                f"schema must be a Pydantic BaseModel subclass, got {type(schema)}"
            )
        if on_failure not in ("raise", "warn", "coerce"):
            raise ValueError(
                f"Invalid on_failure: {on_failure!r}. Must be 'raise', 'warn', or 'coerce'."
            )

        self.schema = schema
        self.on_failure = on_failure

    def run(self, response: LLMResponse, **kwargs: Any) -> LLMResponse:
        """
        Validate response.data against the configured schema.

        Returns:
            LLMResponse with validated (and possibly coerced) data.

        Raises:
            SchemaValidationError: If on_failure="raise" and validation fails.
        """
        try:
            validated = self.schema.model_validate(response.data)

            # Replace data with the validated (and possibly coerced) version
            validated_data = validated.model_dump()

            # Detect if Pydantic filled in defaults (coercion happened)
            was_coerced = set(validated_data.keys()) != set(response.data.keys())

            updated_metadata = {
                **response.metadata,
                "schema_validated": True,
                "schema_name": self.schema.__name__,
            }
            if was_coerced and self.on_failure == "coerce":
                updated_metadata["schema_coerced"] = True

            return response.model_copy(
                update={"data": validated_data, "metadata": updated_metadata}
            )

        except ValidationError as e:
            error_list = e.errors()
            error_summary = "; ".join(
                f"{err['loc']}: {err['msg']}" for err in error_list[:5]
            )

            if self.on_failure == "raise":
                raise SchemaValidationError(
                    f"Response data failed schema validation ({self.schema.__name__}): {error_summary}",
                    validation_errors=error_list,
                )

            elif self.on_failure == "warn":
                logger.warning(
                    f"Schema validation warning ({self.schema.__name__}): {error_summary}"
                )
                updated_metadata = {
                    **response.metadata,
                    "schema_validated": False,
                    "schema_name": self.schema.__name__,
                    "schema_warnings": error_list,
                }
                return response.model_copy(update={"metadata": updated_metadata})

            else:  # coerce
                # Try to build a partial model with defaults where possible
                try:
                    coerced_data = {**response.data}
                    # Fill in defaults from the schema for missing fields
                    for field_name, field_info in self.schema.model_fields.items():
                        if (
                            field_name not in coerced_data
                            and field_info.default is not None
                        ):
                            coerced_data[field_name] = field_info.default

                    validated = self.schema.model_validate(coerced_data)
                    validated_data = validated.model_dump()
                    updated_metadata = {
                        **response.metadata,
                        "schema_validated": True,
                        "schema_coerced": True,
                        "schema_name": self.schema.__name__,
                    }
                    return response.model_copy(
                        update={"data": validated_data, "metadata": updated_metadata}
                    )
                except ValidationError as coerce_error:
                    raise SchemaValidationError(
                        f"Response data failed schema validation even after coercion "
                        f"({self.schema.__name__}): {error_summary}",
                        validation_errors=coerce_error.errors(),
                    )
