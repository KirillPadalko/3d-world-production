"""``envgen`` command line interface."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from environment_generator import GENERATOR_NAME, __version__
from environment_generator.adapters import available_adapters
from environment_generator.assets.registry import load_builtin_registry
from environment_generator.blueprint import (
    dumps_blueprint,
    migrate_file,
    raise_for,
    validate_source,
)
from environment_generator.core.errors import EnvironmentGeneratorError, ExportError
from environment_generator.core.hashing import pretty_json
from environment_generator.core.issues import has_errors
from environment_generator.exporters.json_manifest import load_manifest, verify_manifest
from environment_generator.models.assets import AssetCategory, AssetRegistryDocument
from environment_generator.models.pipeline import GenerationPlan
from environment_generator.models.schemas import export_schemas, stale_schemas
from environment_generator.pipeline import (
    InputBundle,
    LoadInputsStage,
    Pipeline,
    PipelineOptions,
    ResolveInputsStage,
)
from environment_generator.reporting.summary import render_issues, render_report
from environment_generator.reporting.svg_preview import render_svg
from environment_generator.validation.contract import load_document

logger = logging.getLogger("environment_generator.cli")

ENV_LOG_LEVEL = "ENVGEN_LOG_LEVEL"
ENV_REGISTRY = "ENVGEN_ASSET_REGISTRY"

EXIT_OK = 0
EXIT_UNEXPECTED = 1


def _add_input_arguments(
    parser: argparse.ArgumentParser, *, blueprint_required: bool = True
) -> None:
    parser.add_argument(
        "--blueprint",
        "-b",
        type=Path,
        required=blueprint_required,
        help="LocationBlueprint JSON file",
    )
    parser.add_argument(
        "--recipe", "-r", type=Path, help="LocationRecipe JSON file (default recipe if omitted)"
    )
    parser.add_argument("--overrides", "-o", type=Path, help="LocationOverrides JSON file")
    parser.add_argument(
        "--package-root",
        type=Path,
        help="folder that blueprint file references are relative to (default: its folder)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=os.environ.get(ENV_REGISTRY) or None,
        help=f"asset registry JSON file (default: built-in; env {ENV_REGISTRY})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="envgen",
        description="Deterministic procedural environment generator.",
    )
    parser.add_argument("--version", action="version", version=f"{GENERATOR_NAME} {__version__}")
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="more logging (-vv for debug)"
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    validate = commands.add_parser("validate", help="validate inputs without generating")
    _add_input_arguments(validate)
    validate.add_argument("--json", action="store_true", help="print issues as JSON")

    plan = commands.add_parser("plan", help="produce a generation plan (dry run)")
    _add_input_arguments(plan)
    plan.add_argument("--seed", type=int, help="override the seed")
    plan.add_argument("--output", type=Path, help="write the plan JSON here")

    generate = commands.add_parser("generate", help="run the full pipeline")
    _add_input_arguments(generate, blueprint_required=False)
    generate.add_argument("--plan", type=Path, help="generate from a saved plan instead of inputs")
    generate.add_argument(
        "--output-dir", "-d", type=Path, required=True, help="directory for outputs"
    )
    generate.add_argument("--seed", type=int, help="override the seed")
    generate.add_argument("--dry-run", action="store_true", help="stop after planning")
    generate.add_argument(
        "--write-plan", action="store_true", help="also write generation-plan.json"
    )
    generate.add_argument("--preview", action="store_true", help="also write preview.svg")
    generate.add_argument(
        "--no-timings", action="store_true", help="omit stage durations (byte-stable reports)"
    )

    blueprint = commands.add_parser("blueprint", help="validate, format or migrate blueprints")
    blueprint_commands = blueprint.add_subparsers(
        dest="blueprint_command", required=True, metavar="ACTION"
    )
    check = blueprint_commands.add_parser(
        "validate", help="validate one blueprint (version, schema, semantics, references, files)"
    )
    check.add_argument("file", type=Path)
    check.add_argument("--json", action="store_true", help="print the validation report as JSON")
    check.add_argument("--package-root", type=Path, help="default: the blueprint's folder")
    check.add_argument(
        "--no-external", action="store_true", help="do not open referenced external files"
    )
    fmt = blueprint_commands.add_parser(
        "format", help="print a valid blueprint in canonical, deterministic form"
    )
    fmt.add_argument("file", type=Path)
    fmt_target = fmt.add_mutually_exclusive_group()
    fmt_target.add_argument("--output", type=Path, help="write here instead of stdout")
    fmt_target.add_argument(
        "--check", action="store_true", help="exit 3 if the file is not canonically formatted"
    )
    fmt.add_argument("--force", action="store_true", help="allow replacing an existing --output")
    migrate = blueprint_commands.add_parser(
        "migrate", help="upgrade a blueprint to the current schema version"
    )
    migrate.add_argument("file", type=Path)
    migrate_target = migrate.add_mutually_exclusive_group(required=True)
    migrate_target.add_argument("--output", type=Path, help="write the migrated copy here")
    migrate_target.add_argument(
        "--in-place",
        action="store_true",
        help="replace the file (a .v<old>.bak backup is written first)",
    )
    migrate.add_argument(
        "--force", action="store_true", help="allow replacing an existing --output"
    )

    preview = commands.add_parser("preview", help="render a manifest as a top-down SVG")
    preview.add_argument("manifest", type=Path)
    preview.add_argument("--output", type=Path, help="SVG path (default: next to the manifest)")

    verify = commands.add_parser("verify", help="check a manifest against its content hash")
    verify.add_argument("manifest", type=Path)

    schema = commands.add_parser("schema", help="export or check the public JSON Schemas")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True, metavar="ACTION")
    for name, text in (
        ("export", "write schemas"),
        ("check", "fail if committed schemas are stale"),
    ):
        sub = schema_commands.add_parser(name, help=text)
        sub.add_argument("--output-dir", type=Path, default=Path("schemas"))

    assets = commands.add_parser("assets", help="inspect asset registries")
    assets_commands = assets.add_subparsers(dest="assets_command", required=True, metavar="ACTION")
    listing = assets_commands.add_parser("list", help="list archetypes")
    listing.add_argument("--registry", type=Path, default=os.environ.get(ENV_REGISTRY) or None)
    listing.add_argument("--category", choices=[c.value for c in AssetCategory])

    adapters = commands.add_parser("adapters", help="show integration adapters and their status")
    adapters_commands = adapters.add_subparsers(
        dest="adapters_command", required=True, metavar="ACTION"
    )
    adapters_commands.add_parser("list", help="list adapters")
    return parser


def _configure_logging(verbosity: int) -> None:
    env_level = os.environ.get(ENV_LOG_LEVEL, "").upper()
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    elif env_level in logging.getLevelNamesMapping():
        level = logging.getLevelNamesMapping()[env_level]
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )


def _bundle(args: argparse.Namespace) -> InputBundle:
    return InputBundle(
        blueprint=args.blueprint,
        recipe=args.recipe,
        overrides=args.overrides,
        registry=args.registry,
        seed_override=getattr(args, "seed", None),
        package_root=args.package_root,
    )


def _cmd_validate(args: argparse.Namespace) -> int:
    loaded = LoadInputsStage().run(_bundle(args))
    resolved = ResolveInputsStage().run(loaded.output)
    issues = [*loaded.issues, *resolved.issues]
    if args.json:
        print(json.dumps([i.model_dump(mode="json") for i in issues], indent=2))
    else:
        print(f"Inputs are valid ({len(issues)} note(s)).")
        print("\n".join(render_issues(issues)))
    return 0 if not has_errors(issues) else 3


def _cmd_plan(args: argparse.Namespace) -> int:
    result = Pipeline().run(_bundle(args), PipelineOptions(dry_run=True))
    print(render_report(result.report))
    if result.error is not None:
        return result.error.exit_code
    assert result.plan is not None
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            pretty_json(result.plan.model_dump(mode="json"), decimals=None), encoding="utf-8"
        )
        print(f"Plan written to {args.output}")
    return EXIT_OK


def _cmd_generate(args: argparse.Namespace) -> int:
    options = PipelineOptions(
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        write_plan=args.write_plan,
        write_preview=args.preview,
        include_timings=not args.no_timings,
    )
    pipeline = Pipeline()
    if args.plan is not None:
        if args.blueprint or args.recipe or args.overrides:
            raise SystemExit("envgen generate: --plan cannot be combined with input documents")
        plan = load_document(GenerationPlan, args.plan, "plan")
        result = pipeline.run_plan(plan, options)
    else:
        if args.blueprint is None:
            raise SystemExit("envgen generate: --blueprint or --plan is required")
        result = pipeline.run(_bundle(args), options)
    print(render_report(result.report))
    return result.error.exit_code if result.error is not None else EXIT_OK


def _cmd_blueprint(args: argparse.Namespace) -> int:
    if args.blueprint_command == "validate":
        result = validate_source(
            args.file, package_root=args.package_root, check_external=not args.no_external
        )
        report = result.report(document=str(args.file))
        if args.json:
            print(pretty_json(report.model_dump(mode="json"), decimals=None), end="")
        else:
            counts = report.counts
            state = "valid" if report.valid else "INVALID"
            print(
                f"{args.file}: {state} (schema {report.schema_version or '?'}; "
                f"{counts.get('error', 0)} error(s), {counts.get('warning', 0)} warning(s), "
                f"{counts.get('info', 0)} info)"
            )
            for line in render_issues(report.diagnostics, limit=200):
                print(line)
        return EXIT_OK if report.valid else 3
    if args.blueprint_command == "format":
        blueprint = raise_for(validate_source(args.file))
        text = dumps_blueprint(blueprint)
        if args.check:
            if args.file.read_text(encoding="utf-8") != text:
                print(f"{args.file}: not canonically formatted (run `envgen blueprint format`)")
                return 3
            print(f"{args.file}: canonical")
            return EXIT_OK
        if args.output is None:
            print(text, end="")
            return EXIT_OK
        if args.output.resolve() == args.file.resolve() and not args.force:
            raise ExportError("Refusing to replace the input file; pass --force to rewrite it")
        if args.output.exists() and not args.force:
            raise ExportError(f"'{args.output}' exists; pass --force to replace it")
        args.output.write_text(text, encoding="utf-8")
        print(f"Formatted blueprint written to {args.output}")
        return EXIT_OK
    migration, written = migrate_file(
        args.file, output=args.output, in_place=args.in_place, overwrite=args.force
    )
    steps = " > ".join(migration.steps) or "none"
    print(f"{args.file}: {migration.source_version} -> {migration.target_version} (steps: {steps})")
    if written is None:
        print("Already current; nothing written.")
    else:
        print(f"Migrated blueprint written to {written}")
    return EXIT_OK


def _cmd_preview(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    output = args.output or args.manifest.with_name("preview.svg")
    output.write_text(render_svg(manifest), encoding="utf-8")
    print(f"Preview written to {output}")
    return EXIT_OK


def _cmd_verify(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    if verify_manifest(manifest):
        print(f"OK {manifest.content_hash} ({manifest.statistics.entity_count} entities)")
        return EXIT_OK
    print(f"MISMATCH: content does not match {manifest.content_hash}")
    return 3


def _cmd_schema(args: argparse.Namespace) -> int:
    if args.schema_command == "export":
        for path in export_schemas(args.output_dir):
            print(f"wrote {path}")
        return EXIT_OK
    stale = stale_schemas(args.output_dir)
    if stale:
        print("Stale schemas (run `envgen schema export`): " + ", ".join(stale))
        return 3
    print("Schemas are up to date.")
    return EXIT_OK


def _cmd_assets(args: argparse.Namespace) -> int:
    registry = (
        load_document(AssetRegistryDocument, args.registry, "registry")
        if args.registry
        else load_builtin_registry()
    )
    print(f"{registry.id}: {registry.name}")
    for archetype in sorted(registry.archetypes, key=lambda a: a.id):
        if args.category and archetype.category.value != args.category:
            continue
        dims = archetype.dimensions
        size = f"{dims.width_m:g}x{dims.depth_m:g}x{dims.height_m:g}"
        print(
            f"  {archetype.id:<42} {archetype.category.value:<15} "
            f"kinds={','.join(archetype.kinds)} size={size} variants={archetype.variants}"
        )
    return EXIT_OK


def _cmd_adapters(_: argparse.Namespace) -> int:
    for info in available_adapters():
        print(f"  {info.name:<22} [{info.status.value:<5}] {info.workflow_step}")
        print(f"  {'':<22}         {info.description}")
    return EXIT_OK


COMMANDS = {
    "validate": _cmd_validate,
    "plan": _cmd_plan,
    "generate": _cmd_generate,
    "blueprint": _cmd_blueprint,
    "preview": _cmd_preview,
    "verify": _cmd_verify,
    "schema": _cmd_schema,
    "assets": _cmd_assets,
    "adapters": _cmd_adapters,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    try:
        return COMMANDS[args.command](args)
    except EnvironmentGeneratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception:  # pragma: no cover - last-resort guard
        logger.exception("unexpected failure")
        return EXIT_UNEXPECTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
