"""Domain Pack SDK manifest schema and local validation commands."""

import argparse
import json
import sys
from pathlib import Path

from operations.modules.domain_packs.application.artifacts import artifact_json_schema
from operations.modules.domain_packs.application.manifest import PackManifest
from operations.modules.domain_packs.application.validation import validate_pack_directory


def main() -> int:
    parser = argparse.ArgumentParser(prog="domain-pack")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a local declarative package")
    validate.add_argument("directory", type=Path)
    validate.add_argument("--core-version", required=True)
    schema = commands.add_parser("schema", help="print the JSON Schema for pack.yaml")
    schema.add_argument("--artifacts", action="store_true", help="emit artifact JSON Schema")
    schema.add_argument("--output", type=Path)
    schema.add_argument("--check", type=Path)
    arguments = parser.parse_args()

    if arguments.command == "schema":
        schema_document = (
            artifact_json_schema() if arguments.artifacts else PackManifest.model_json_schema()
        )
        content = json.dumps(schema_document, indent=2, sort_keys=True) + "\n"
        if arguments.check is not None:
            checked_in = (
                arguments.check.read_text(encoding="utf-8") if arguments.check.exists() else None
            )
            if checked_in != content:
                sys.stderr.write("Domain Pack schema drift; regenerate with --output\n")
                return 1
            return 0
        if arguments.output is None:
            sys.stdout.write(content)
        else:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(content, encoding="utf-8")
        return 0

    result = validate_pack_directory(arguments.directory, core_version=arguments.core_version)
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
