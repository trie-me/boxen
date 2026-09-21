import json
from functools import lru_cache
from pathlib import Path

import yaml
from boxen.shared.errors import DomainError
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ASSETS = Path(__file__).resolve().parents[1] / "assets"


@lru_cache
def api_contract() -> dict:
    return yaml.safe_load((ASSETS / "openapi.yaml").read_text())


def resolve(node: dict) -> dict:
    if "$ref" not in node:
        return node
    result = api_contract()
    for key in node["$ref"].removeprefix("#/").split("/"):
        result = result[key.replace("~1", "/").replace("~0", "~")]
    return result


@lru_cache
def validator(name: str) -> Draft202012Validator:
    document = api_contract()
    resource = Resource.from_contents({"$schema": "https://json-schema.org/draft/2020-12/schema", **document})
    registry = Registry().with_resource("urn:boxen:api", resource)
    return Draft202012Validator(
        {"$ref": f"urn:boxen:api#/components/schemas/{name}"},
        registry=registry,
        format_checker=FormatChecker(),
    )


def _validation_message(error) -> str:
    # jsonschema's own messages include the supplied value (possibly a secret).
    # Only use fixed copy and constraints from our trusted schema here.
    messages = {
        "required": "This field is required.",
        "minLength": f"Use at least {error.validator_value} character{'s' if error.validator_value != 1 else ''}.",
        "maxLength": f"Use no more than {error.validator_value} character{'s' if error.validator_value != 1 else ''}.",
        "minimum": f"Use a value of at least {error.validator_value}.",
        "maximum": f"Use a value no greater than {error.validator_value}.",
        "exclusiveMinimum": f"Use a value greater than {error.validator_value}.",
        "exclusiveMaximum": f"Use a value less than {error.validator_value}.",
        "minItems": f"Include at least {error.validator_value} items.",
        "maxItems": f"Include no more than {error.validator_value} items.",
        "minProperties": f"Include at least {error.validator_value} fields.",
        "maxProperties": f"Include no more than {error.validator_value} fields.",
        "uniqueItems": "Remove duplicate items.",
        "additionalProperties": "Remove unsupported fields.",
        "enum": "Choose one of the supported options.",
        "pattern": "Use the expected format for this field.",
    }
    if error.validator == "type":
        types = error.validator_value
        labels = {
            "string": "text",
            "integer": "a whole number",
            "number": "a number",
            "boolean": "true or false",
            "object": "an object",
            "array": "a list",
            "null": "null",
        }
        return (
            "Use "
            + " or ".join(labels[kind] for kind in ([types] if isinstance(types, str) else types))
            + "."
        )
    if error.validator == "format":
        return {
            "uuid": "Use a valid UUID.",
            "date-time": "Use a valid date and time with a time zone.",
            "uri-reference": "Use a valid URL or relative reference.",
        }.get(error.validator_value, "Use the expected format for this field.")
    return messages.get(error.validator, "This field does not match the expected type or limits.")


def validate_payload(value: object, schema: dict, prefix: str = "") -> None:
    """Validate a body or a parameter with an optional, escaped JSON Pointer prefix."""
    document = {"$schema": "https://json-schema.org/draft/2020-12/schema", **api_contract()}
    registry = Registry().with_resource("urn:boxen:api", Resource.from_contents(document))
    full = {"$id": "urn:boxen:api:request", **schema, "components": document["components"]}
    errors = sorted(
        Draft202012Validator(full, registry=registry, format_checker=FormatChecker()).iter_errors(value),
        key=lambda e: str(e.path),
    )
    if errors:
        fields = []
        for error in errors:
            paths = [list(error.absolute_path)]
            if error.validator == "required":
                paths = [
                    [*error.absolute_path, name]
                    for name in error.validator_value
                    if name not in error.instance
                ]
            for path in paths:
                pointer = prefix.rstrip("/") + "".join(
                    "/" + str(part).replace("~", "~0").replace("/", "~1") for part in path
                )
                field = {
                    "path": pointer or "/",
                    "code": "value.invalid",
                    "message": _validation_message(error),
                }
                if field not in fields:
                    fields.append(field)
                if len(fields) == 20:
                    break
            if len(fields) == 20:
                break
        raise DomainError("request.validation", "Check the highlighted fields and try again.", errors=fields)


def strict_json(raw: bytes) -> object:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("nonfinite number")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant)

        def depth(node, level=0):
            if level > 32:
                raise ValueError("depth limit")
            if isinstance(node, dict):
                for v in node.values():
                    depth(v, level + 1)
            elif isinstance(node, list):
                for v in node:
                    depth(v, level + 1)

        depth(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise DomainError(
            "request.malformed_json",
            "The request must contain one valid, bounded JSON value without duplicate keys.",
            400,
        ) from None
