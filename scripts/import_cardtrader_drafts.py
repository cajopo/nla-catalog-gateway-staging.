"""Prepare and import a bounded batch of missing DRAFTs; never publish products.

Default is preview. Uses the existing refresh lock, reference builder, complete
identity check and durable importer ledger. Retain the run directory permanently:
an applied run can become the canonical-reference source for future refreshes.
"""

import argparse
import json
import os
import re
import sqlite3
import stat
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from nla_catalog_gateway.canonical_names import (
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    load_canonical_names,
    load_canonical_names_manifest,
)
from nla_catalog_gateway.expansion_collections import reconcile_expansion_collections
from nla_catalog_gateway.shopify_capture_http import CaptureHttpError, ShopifyCaptureHttp
from nla_catalog_gateway.shopify_draft_import import create_draft_once
from scripts import activate_staging_refresh as activation
from scripts import capture_import_identities as identities
from scripts import refresh_staging_catalog as refresh
from scripts.prepare_cardtrader_reference import prepare


def failure_reason(error):
    """Only local, fixed codes may enter receipts; never copy remote error text."""
    reasons = {
        "unexpected_preparation_approval",
        "source_stale_or_reference_not_selected",
        "identity_snapshot_changed",
        "identity_export_stale",
        "identity_guard_wrong_shop",
        "identity_definition_changed",
        "invalid_identity_timestamp",
        "future_identity_timestamp",
        "invalid_identity_page_limit",
        "invalid_identity_metafield",
        "invalid_identity_page",
        "inconsistent_identity_page",
        "invalid_identity_cursor",
        "identity_page_limit_requires_fresh_baseline",
        "import_access_not_granted",
        "invalid_import_identity",
        "invalid_import_product",
        "invalid_import_image",
        "invalid_expansion_collection_identity",
        "invalid_expansion_collection_handle",
        "invalid_expansion_collection_tags",
        "conflicting_expansion_collection_identity",
        "conflicting_expansion_collection_handle",
        "expansion_collection_source_drift",
        "duplicate_expansion_collection_identity",
        "expansion_collection_gid_changed",
        "expansion_collection_missing_inspect",
        "expansion_collection_handle_occupied",
        "expansion_collection_create_rejected",
        "expansion_collection_readback_mismatch",
        "expansion_collection_handle_changed",
    }
    if isinstance(error, CaptureHttpError):
        return "shopify_request_failed"
    if type(error) is ValueError and len(error.args) == 1:
        reason = error.args[0]
        if type(reason) is str and reason in reasons:
            return reason
    if isinstance(error, sqlite3.Error):
        return "ledger_database_error"
    return "unexpected_batch_error"


def config_values(path):
    raw = refresh.document(path)
    if set(raw) != refresh.FIELDS:
        raise ValueError("unexpected_refresh_configuration")
    config = dict(raw)
    for key in refresh.PATHS:
        value = Path(raw[key])
        if not value.is_absolute() or value.resolve() != value:
            raise ValueError("noncanonical_refresh_path")
        config[key] = value
    return raw, config


def durable_tree(root):
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("reference_symlink")
        if path.is_file():
            with path.open("r+b") as stream:
                os.fsync(stream.fileno())
    for path in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        activation.sync_directory(path)
    activation.sync_directory(root)
    activation.sync_directory(root.parent)


def run_locked(
    config_path,
    capture,
    identity_run,
    run,
    ledger,
    generator_sha,
    client,
    *,
    apply=False,
    max_attempts=1,
    expansion_collections=False,
):
    """Caller holds refresh.pipeline_lock. No automatic retry or publication."""
    if (
        type(apply) is not bool
        or type(expansion_collections) is not bool
        or type(max_attempts) is not int
        or not 1 <= max_attempts <= 100
    ):
        raise ValueError("invalid_batch_controls")
    if re.fullmatch(r"[0-9a-f]{40}", generator_sha) is None:
        raise ValueError("invalid_generator_sha")
    for path in (config_path, capture, identity_run, run, ledger):
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError("canonical_absolute_paths_required")
    if not run.is_relative_to(ledger.parent) or run == ledger.parent:
        raise ValueError("run_must_live_under_persistent_importer_state")
    raw, config = config_values(config_path)
    if (config["run_root"] / "pending-run.json").exists() or refresh.freshness(config)[
        "status"
    ] != "fresh":
        raise ValueError("refresh_not_fresh_or_pending")
    facts = ledger.lstat()
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise ValueError("existing_regular_ledger_required")
    if os.name == "posix" and (facts.st_uid != 0 or stat.S_IMODE(facts.st_mode) != 0o600):
        raise ValueError("private_existing_ledger_required")
    with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute(
            "SELECT 1 FROM draft_attempts WHERE state != 'draft_verified' LIMIT 1"
        ).fetchone():
            raise ValueError("previous_import_needs_reconciliation")
        recorded = db.execute(
            "SELECT cardmarket_id,blueprint_id FROM draft_attempts WHERE shop=?",
            (config["shop"],),
        ).fetchall()
    recorded_ids = {str(row[0]) for row in recorded}
    recorded_blueprints = {row[1] for row in recorded}
    _, existing_ids = identities.read_fresh_identities(identity_run, config["shop"])
    current = refresh.document(config["run_root"] / "last-success.json")["manifestSha256"]
    if re.fullmatch(r"[0-9a-f]{64}", current) is None:
        raise ValueError("invalid_current_generation")
    generation = config["store"] / "generations" / current
    manifest_path = generation / "staging-generation-manifest.v1.json"
    if activation.digest(manifest_path) != current:
        raise ValueError("current_generation_changed")
    manifest = json.loads(manifest_path.read_bytes())
    artifact = next(
        a for a in manifest["artifacts"] if a["filename"] == "catalog-projection.v1.sqlite3"
    )
    run.mkdir(mode=0o700)
    activation.sync_directory(run.parent)
    prepared = prepare(
        capture,
        generation / "catalog-projection.v1.sqlite3",
        artifact["sha256"],
        config["reference"],
        config["reference_manifest_sha256"],
        run / "reference",
        generator_sha,
    )
    # New DRAFTs may postdate the projection. Exclude them before the batch
    # limit, so later cycles advance instead of repeatedly selecting the same ID.
    excluded_ids = existing_ids | recorded_ids
    missing = [
        c
        for c in prepared["candidates"]
        if str(c["cardmarketId"]) not in excluded_ids
        and c["blueprintId"] not in recorded_blueprints
    ]
    selected = missing[:max_attempts]
    result = dict(
        status="preview",
        candidates=len(prepared["candidates"]),
        skippedExisting=len(prepared["candidates"]) - len(missing),
        selected=len(selected),
        exceptions=len(prepared["exceptions"]),
        attempts=[],
        deferred=[],
        published=False,
        automaticImportEnabled=False,
        referenceSelected=False,
    )
    if not apply or not selected:
        refresh.publish(run / "result.json", result)
        return result

    verify_identity = identities.missing_guard(identity_run, config["shop"], client.graphql)
    reference = Path(prepared["reference"])
    reference_sha = prepared["referenceEvidence"]["manifestSha256"]
    reference_manifest = load_canonical_names_manifest(
        (reference / MANIFEST_FILENAME).read_bytes(), expected_sha256=reference_sha
    )
    with (reference / SIDECAR_FILENAME).open("rb") as source:
        load_canonical_names(source, manifest=reference_manifest)
    # Preserve all configuration fields except the three canonical-reference pins.
    updated = dict(
        raw,
        reference=str(reference),
        reference_manifest_sha256=reference_sha,
        reference_data_sha256=reference_manifest.sidecar.sha256,
    )
    if refresh.document(config_path) != raw:
        raise ValueError("refresh_configuration_changed")
    durable_tree(run)
    refresh.publish(run / "refresh-config.before.json", raw)
    if updated != raw:
        refresh.publish(config_path, updated, replace=True)
    result["referenceSelected"] = True
    result["status"] = "stopped_inspect_before_retry"

    def guard(cardmarket_id, blueprint_id):
        age = (
            datetime.now(UTC) - identities.timestamp(prepared["sourceStartedAt"])
        ).total_seconds()
        if not 0 <= age <= 86400 or refresh.document(config_path) != updated:
            raise ValueError("source_stale_or_reference_not_selected")
        try:
            return verify_identity(cardmarket_id)
        except ValueError as error:
            if type(error) is not ValueError or error.args != ("inconsistent_identity_page",):
                raise
            # This callback runs before create_draft_once reserves or writes anything.
            result["deferred"].append(
                dict(
                    cardmarketId=cardmarket_id,
                    blueprintId=blueprint_id,
                    reason="inconsistent_identity_page",
                )
            )
            return False

    identifier = None
    try:
        # Reconcile before product creation: a crash after productCreate cannot
        # strand a new release whose existing identity is skipped next cycle.
        specs = [candidate for candidate in selected if "collectionTags" in candidate]
        if expansion_collections and specs:
            if any(candidate["creationApproved"] is not False for candidate in specs):
                raise ValueError("unexpected_preparation_approval")
            result["expansionCollections"] = dict(
                status="started_inspect_journal", candidates=len(specs)
            )
            result["expansionCollections"] = reconcile_expansion_collections(
                graphql=client.graphql,
                specs=specs,
                state_dir=ledger.parent / "expansion-collections",
                enabled=True,
            )
        for candidate in selected:
            identifier = None
            identifier = int(candidate["cardmarketId"])
            if candidate["creationApproved"] is not False:
                raise ValueError("unexpected_preparation_approval")
            attempt = create_draft_once(
                ledger,
                shop=config["shop"],
                blueprint_id=candidate["blueprintId"],
                cardmarket_id=identifier,
                game=candidate["game"],
                product_family=candidate.get("productFamily", "single"),
                source_expansion_id=candidate.get("sourceExpansionId"),
                source_expansion_name=candidate.get("sourceExpansionName"),
                collection_tags=candidate.get("collectionTags"),
                title=candidate["title"],
                image_url=candidate["imageUrl"],
                graphql=client.graphql,
                verify_missing=lambda identifier=identifier, blueprint=candidate["blueprintId"]: (
                    guard(identifier, blueprint)
                ),
                enabled=True,
            )
            result["attempts"].append(dict(cardmarketId=identifier, **attempt))
            if attempt["status"] == "needs_reconciliation" or (
                attempt["status"] == "already_reserved" and attempt.get("state") != "draft_verified"
            ):
                result["status"] = "needs_reconciliation"
                break
            if result["deferred"]:
                if attempt["status"] != "not_verified_missing":
                    raise ValueError("unexpected_deferred_attempt_outcome")
                result["status"] = "batch_deferred"
                break
        else:
            result["status"] = "batch_complete"
    except Exception as error:
        result["status"] = "stopped_inspect_before_retry"
        result["failure"] = dict(reason=failure_reason(error), cardmarketId=identifier)
    finally:
        # A crash before this backup still leaves the original durable ledger.
        with (
            closing(sqlite3.connect(ledger)) as source,
            closing(sqlite3.connect(run / "ledger-after.sqlite3")) as backup,
        ):
            source.backup(backup)
        durable_tree(run)
        refresh.publish(run / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("refresh-config", "capture", "identities", "run", "ledger"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--generator-sha", required=True)
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expansion-collections", action="store_true")
    args = parser.parse_args()
    try:
        if not __debug__ or sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("non_optimized_root_linux_required")
        os.umask(0o077)
        _, config = config_values(args.refresh_config)
        with refresh.pipeline_lock(config["run_root"]):
            credentials = refresh.document(config["config"] / "shopify-app-credentials.json")
            client = ShopifyCaptureHttp(
                config["shop"],
                "2026-07",
                credentials["client_id"],
                credentials["client_secret"],
            )
            result = run_locked(
                args.refresh_config,
                args.capture,
                args.identities,
                args.run,
                args.ledger,
                args.generator_sha,
                client,
                apply=args.apply,
                max_attempts=args.max_attempts,
                expansion_collections=args.expansion_collections,
            )
        print(json.dumps(result))
        return 0 if result["status"] in ("preview", "batch_complete") else 1
    except Exception:
        print(json.dumps(dict(status="import_unconfirmed_inspect_run_and_ledger", published=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
