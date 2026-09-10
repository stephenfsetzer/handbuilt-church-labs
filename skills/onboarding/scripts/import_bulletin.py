#!/usr/bin/env python3
"""Snapshot a supplied bulletin PDF, extract its evidence, and record which
source sections map to church settings.

Subcommands: import, list-imports, manifest, map-section, mark-review-complete,
inventory, list-inventories, validate, validate-for-production,
check-rendered-text.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills.onboarding.bulletin_import import (
    BulletinImportError, import_bulletin, list_imports, read_manifest,
)
from skills.bulletin.source_inventory import (
    InventoryError, add_section, check_mapping_integrity, check_rendered_text,
    list_inventories, mark_review_complete, read_inventory, validate_for_production,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="Snapshot a supplied bulletin PDF and extract page evidence")
    imp.add_argument("--church-folder", required=True)
    imp.add_argument("--source-pdf", required=True)
    imp.add_argument("--original-filename")
    imp.add_argument("--dpi", type=int, default=150)

    ls = sub.add_parser("list-imports")
    ls.add_argument("--church-folder", required=True)

    manifest = sub.add_parser("manifest")
    manifest.add_argument("--church-folder", required=True)
    manifest.add_argument("--import-id", required=True)

    add = sub.add_parser("map-section", help="Record what one supplied page range means")
    add.add_argument("--church-folder", required=True)
    add.add_argument("--import-id", required=True)
    add.add_argument("--section-id", required=True)
    add.add_argument("--page-start", type=int, required=True)
    add.add_argument("--page-end", type=int)
    add.add_argument("--disposition", required=True, choices=("mapped", "unresolved", "omitted"))
    add.add_argument("--scope", required=True, choices=("standing", "weekly"))
    add.add_argument("--service-date", help="Required for --scope weekly (YYYY-MM-DD)")
    add.add_argument("--config-path")
    add.add_argument("--text-file")
    add.add_argument("--asset-path")
    add.add_argument("--notes", default="")

    review = sub.add_parser(
        "mark-review-complete",
        help="Attest that every page of this import has been accounted for as a recorded section",
    )
    review.add_argument("--church-folder", required=True)
    review.add_argument("--import-id", required=True)
    review.add_argument("--note", required=True)

    inv = sub.add_parser("inventory")
    inv.add_argument("--church-folder", required=True)
    inv.add_argument("--import-id", required=True)

    inv_ls = sub.add_parser("list-inventories")
    inv_ls.add_argument("--church-folder", required=True)

    val = sub.add_parser("validate", help="Informative pre-render mapping-integrity check for onboarding")
    val.add_argument("--church-folder", required=True)
    val.add_argument("--import-id")
    val.add_argument("--service-date")

    val_prod = sub.add_parser(
        "validate-for-production",
        help="Blocking pre-render check the bulletin workflow should pass before relying on an import",
    )
    val_prod.add_argument("--church-folder", required=True)
    val_prod.add_argument("--bulletin-file", required=True, help="Path to the effective weekly bulletin JSON")

    rendered = sub.add_parser("check-rendered-text", help="Optional post-render text check")
    rendered.add_argument("--church-folder", required=True)
    rendered.add_argument("--import-id", required=True)
    rendered.add_argument("--section-id", required=True)
    rendered.add_argument("--rendered-pdf", required=True)
    rendered.add_argument("--excerpt")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "import":
            result = {"status": "imported", **import_bulletin(
                args.church_folder, args.source_pdf,
                original_filename=args.original_filename, dpi=args.dpi,
            )}
        elif args.command == "list-imports":
            result = {"status": "ok", "imports": list_imports(args.church_folder)}
        elif args.command == "manifest":
            result = {"status": "ok", "manifest": read_manifest(args.church_folder, args.import_id)}
        elif args.command == "map-section":
            target = {}
            if args.config_path:
                target["config_path"] = args.config_path
            if args.text_file:
                target["text_file"] = args.text_file
            if args.asset_path:
                target["asset_path"] = args.asset_path
            entry = add_section(
                args.church_folder, args.import_id,
                section_id=args.section_id, page_start=args.page_start, page_end=args.page_end,
                disposition=args.disposition, scope=args.scope, target=target,
                service_date=args.service_date, notes=args.notes,
            )
            result = {"status": "recorded", "section": entry}
        elif args.command == "mark-review-complete":
            result = {"status": "recorded", "review": mark_review_complete(
                args.church_folder, args.import_id, note=args.note,
            )}
        elif args.command == "inventory":
            result = {"status": "ok", "inventory": read_inventory(args.church_folder, args.import_id)}
        elif args.command == "list-inventories":
            result = {"status": "ok", "inventories": list_inventories(args.church_folder)}
        elif args.command == "validate-for-production":
            bulletin = json.loads(Path(args.bulletin_file).read_text(encoding="utf-8"))
            result = validate_for_production(args.church_folder, bulletin)
        elif args.command == "check-rendered-text":
            result = check_rendered_text(
                args.church_folder, args.import_id, args.section_id, args.rendered_pdf,
                excerpt=args.excerpt,
            )
        else:
            result = check_mapping_integrity(args.church_folder, args.import_id, service_date=args.service_date)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (BulletinImportError, InventoryError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
