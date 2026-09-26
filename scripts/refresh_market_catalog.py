"""Coordinate one market-source -> draft -> Shopify-index cycle. No publication.

No timer is installed by this command. A pending cycle is never restarted blindly.
Retain cycle directories: an applied batch can own the active canonical reference.
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

from nla_catalog_gateway.cardtrader_capture import capture_catalog
from nla_catalog_gateway.cardtrader_catalog import CardTraderCatalogClient
from nla_catalog_gateway.shopify_capture_http import ShopifyCaptureHttp
from scripts import activate_staging_refresh as activation
from scripts import capture_import_identities as identities
from scripts import import_cardtrader_drafts as drafts
from scripts import refresh_staging_catalog as refresh


def batch_paths(run, number):
    suffix = "" if number == 1 else f"-{number:04d}"
    return run / ("batch" + suffix), run / ("identities" + suffix)


def batch_directories(run, prefix):
    return [
        path
        for path in run.iterdir()
        if path.name == prefix or re.fullmatch(prefix + r"-\d{4}", path.name)
    ]


def input_facts(path, root):
    facts = path.lstat()
    if (
        path.resolve() != path
        or not path.is_relative_to(root)
        or not stat.S_ISREG(facts.st_mode)
        or facts.st_nlink != 1
        or facts.st_dev != root.stat().st_dev
        or (os.name == "posix" and facts.st_uid != os.geteuid())
    ):
        raise ValueError("unsafe_expired_market_input")
    return facts


def prune_batch_identities(run, completed_batches):
    """After successful batches, keep the latest two payloads and every receipt.

    Caller holds the importer lock. Exact local payload hashes and terminal batch
    receipts are verified before durable expiry intent and unlink; no directories.
    """
    if run.resolve() != run or not run.is_dir():
        raise ValueError("noncanonical_retention_run")
    for number in range(1, completed_batches - 1):
        batch, identity = batch_paths(run, number)
        payload = identity / "identities.jsonl"
        if not os.path.lexists(payload):
            continue
        receipt = refresh.document(identity / "completed.json")
        if (
            refresh.document(batch / "result.json")["status"] != "batch_complete"
            or receipt["status"] != "complete"
            or receipt["shopifyChanged"] is not False
        ):
            raise ValueError("identity_retention_requires_completed_batch")
        facts = input_facts(payload, run)
        if activation.digest(payload) != receipt["sha256"]:
            raise ValueError("expired_identity_hash_changed")
        refresh.publish(
            identity / "payload-expiry.json",
            dict(authorizedAt=refresh.timestamp(), sha256=receipt["sha256"], bytes=facts.st_size),
            replace=True,
        )
        after = input_facts(payload, run)
        unchanged = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(after, key) != getattr(facts, key) for key in unchanged):
            raise ValueError("expired_market_input_changed")
        payload.unlink()
        activation.sync_directory(identity)


def prune_completed_inputs(state, config_path):
    """Caller holds both locks. Keep receipts, ledger, latest two and reference rollback.

    Delete only named large input files, never directories or incomplete cycles.
    Old retained manifests describe intentionally expired raw inputs, not reusable captures.
    """
    raw, config = drafts.config_values(config_path)
    if (state / "pending-market-run.json").exists() or (
        config["run_root"] / "pending-run.json"
    ).exists():
        raise ValueError("retention_requires_idle_pipelines")
    if state.resolve() != state or not state.is_dir():
        raise ValueError("noncanonical_retention_state")
    runs = []
    for run in sorted(state.iterdir()):
        if re.fullmatch(r"market-\d{8}t\d{6}z-[0-9a-f]{8}", run.name) is None:
            continue
        if run.resolve() != run or not (run / "completed.json").is_file():
            raise ValueError("market_run_requires_inspection_before_retention")
        receipt = refresh.document(run / "completed.json")
        if receipt["run"] != run.name or receipt["status"] not in (
            "draft_cycle_complete",
            "draft_cycle_partial",
            "preview_cycle_complete",
        ):
            raise ValueError("invalid_completed_market_run")
        runs.append(run)
    if len(runs) <= 2:
        return 0
    keep = set(runs[-2:])
    current_reference = config["reference"]
    keep.update(run for run in runs if current_reference.is_relative_to(run))
    # Protect the before-reference of retained runs, once (not their entire history).
    for run in tuple(keep):
        for batch in batch_directories(run, "batch"):
            before = batch / "refresh-config.before.json"
            if before.exists():
                reference = Path(refresh.document(before)["reference"])
                keep.update(old for old in runs if reference.is_relative_to(old))
    removed = 0
    for run in runs:
        if run in keep:
            continue
        targets = [
            p
            for p in (run / "source").glob("blueprints-*.json")
            if re.fullmatch(r"blueprints-[1-9][0-9]*\.json", p.name)
        ]
        for identity in batch_directories(run, "identities"):
            if os.path.lexists(identity / "identities.jsonl"):
                targets.append(identity / "identities.jsonl")
        for batch in batch_directories(run, "batch"):
            for name in ("ledger-after.sqlite3", "reference/bundle/canonical-names.v1.jsonl"):
                if os.path.lexists(batch / name):
                    targets.append(batch / name)
        checked = {}
        for path in targets:
            checked[path] = input_facts(path, state)
        if not checked:
            continue
        if refresh.document(config_path) != raw:
            raise ValueError("configuration_changed_during_retention")
        for path, facts in checked.items():
            if path.resolve() != path or path.lstat() != facts:
                raise ValueError("expired_market_input_changed")
            path.unlink()
        for parent in {p.parent for p in checked}:
            activation.sync_directory(parent)
        refresh.publish(
            run / "pruned-inputs.json",
            dict(
                prunedAt=refresh.timestamp(),
                files=len(checked),
                bytes=sum(f.st_size for f in checked.values()),
                receiptsRetained=True,
            ),
            replace=True,
        )
        removed += len(checked)
    return removed


def refresh_index(package, config_path):
    """Use the configured existing operator, including its own archive validation."""
    if not package.is_absolute() or package.resolve() != package:
        raise ValueError("canonical_refresh_package_required")
    environment = dict(os.environ, PYTHONPATH=str(package / "src"))
    subprocess.run(  # noqa: S603 -- fixed Python module, explicit argv; operator-owned paths.
        [
            sys.executable,
            "-m",
            "scripts.refresh_staging_catalog",
            "--config",
            str(config_path),
            "--apply",
        ],
        cwd=package,
        env=environment,
        check=True,
        timeout=14400,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cycle(
    state,
    refresh_config,
    refresh_package,
    ledger,
    generator_sha,
    cardtrader,
    shopify,
    *,
    apply_drafts=False,
    max_attempts=1,
    max_batches=1,
    pause=time.sleep,
):
    """Caller holds state's pipeline lock; individual stages use refresh's lock.

    Bounded source capture and identity polling reuse their durable receipts.
    Any error/interruption retains pending-market-run.json for operator inspection.
    """
    if (
        type(apply_drafts) is not bool
        or type(max_attempts) is not int
        or not 1 <= max_attempts <= 100
        or type(max_batches) is not int
        or not 1 <= max_batches <= 100
    ):
        raise ValueError("invalid_cycle_controls")
    if re.fullmatch(r"[0-9a-f]{40}", generator_sha) is None:
        raise ValueError("invalid_generator_sha")
    for path in (state, refresh_config, refresh_package, ledger):
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError("canonical_cycle_paths_required")
    if state != ledger.parent or not ledger.is_file():
        raise ValueError("existing_persistent_importer_state_required")
    marker = state / "pending-market-run.json"
    if marker.exists():
        raise ValueError("previous_market_cycle_requires_inspection")
    _, config = drafts.config_values(refresh_config)
    with refresh.pipeline_lock(config["run_root"]):
        prune_completed_inputs(state, refresh_config)
    if shutil.disk_usage(state).free < 6 * 1024**3:
        raise ValueError("insufficient_market_cycle_space")
    name = (
        "market-"
        + refresh.timestamp().replace("-", "").replace(":", "").lower()
        + "-"
        + uuid.uuid4().hex[:8]
    )
    run = state / name
    run.mkdir(mode=0o700)
    activation.sync_directory(state)
    refresh.publish(marker, dict(run=name, startedAt=refresh.timestamp(), applyDrafts=apply_drafts))
    result = dict(
        run=name,
        status="incomplete",
        startedAt=refresh.timestamp(),
        published=False,
        applyDrafts=apply_drafts,
        indexRefreshed=False,
        batches=[],
        attempts=[],
        selected=0,
        maxBatches=max_batches,
        remaining=None,
        eligibleExhausted=False,
    )
    try:
        source = capture_catalog(cardtrader, run / "source")
        result["sourceExpansions"] = source["completedExpansions"]
        result["sourceBlueprints"] = source["blueprints"]
        refresh.publish(
            run / "source-summary.json", {k: v for k, v in source.items() if k != "files"}
        )
        for number in range(1, max_batches + 1):
            batch_path, identity_path = batch_paths(run, number)
            _, config = drafts.config_values(refresh_config)
            # Poll only this batch's operation; uncertainty never starts another.
            deadline = time.monotonic() + 1200
            while True:
                with refresh.pipeline_lock(config["run_root"]):
                    if (config["run_root"] / "pending-run.json").exists():
                        raise ValueError("catalog_refresh_pending")
                    identity = identities.capture_once(shopify, config["shop"], identity_path)
                if identity["status"] == "complete":
                    break
                if identity["status"] != "running" or time.monotonic() >= deadline:
                    raise ValueError("identity_poll_limit_inspect_same_operation")
                pause(30)
            result["identityOperation"] = identity["operationId"]
            with refresh.pipeline_lock(config["run_root"]):
                batch = drafts.run_locked(
                    refresh_config,
                    run / "source",
                    identity_path,
                    batch_path,
                    ledger,
                    generator_sha,
                    shopify,
                    apply=apply_drafts,
                    max_attempts=max_attempts,
                )
            result["batchStatus"] = batch["status"]
            result["attempts"].extend(batch["attempts"])
            result["candidates"] = batch["candidates"]
            result["selected"] += batch["selected"]
            result["exceptions"] = batch["exceptions"]
            if batch["status"] not in ("preview", "batch_complete"):
                raise ValueError("draft_batch_requires_inspection")
            verified = sum(
                a["status"] == "draft_verified"
                or (a["status"] == "already_reserved" and a.get("state") == "draft_verified")
                for a in batch["attempts"]
            )
            # Conservative backlog: live-guard rejections are NOT counted as imported.
            result["remaining"] = batch["candidates"] - batch["skippedExisting"] - verified
            result["eligibleExhausted"] = result["remaining"] == 0
            result["batches"].append(
                dict(
                    number=number,
                    directory=batch_path.name,
                    identityOperation=identity["operationId"],
                    status=batch["status"],
                    selected=batch["selected"],
                    remaining=result["remaining"],
                )
            )
            if apply_drafts:
                prune_batch_identities(run, number)
            if not apply_drafts:
                result["completionReason"] = "preview"
                break
            if result["eligibleExhausted"]:
                result["completionReason"] = "eligible_exhausted"
                break
            if verified == 0:
                result["completionReason"] = "no_verified_progress"
                break
        else:
            result["completionReason"] = "batch_budget_exhausted"
        # Refresh even an empty apply cycle: PowerTools stock/price changes remain
        # authoritative and must reach the index independently of new printings.
        if apply_drafts:
            refresh_index(refresh_package, refresh_config)
            _, config = drafts.config_values(refresh_config)
            if refresh.freshness(config)["status"] != "fresh":
                raise ValueError("post_import_index_not_fresh")
            result["indexRefreshed"] = True
        result["status"] = "draft_cycle_complete" if apply_drafts else "preview_cycle_complete"
        if apply_drafts and not result["eligibleExhausted"]:
            result["status"] = "draft_cycle_partial"
        result["finishedAt"] = refresh.timestamp()
        refresh.publish(run / "completed.json", result)
        refresh.publish(state / "last-market-success.json", result, replace=True)
        marker.unlink()
        activation.sync_directory(state)
        return result
    except BaseException:
        result["status"] = "stopped_inspect_pending_cycle"
        refresh.publish(run / "stopped.json", result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("state", "refresh-config", "refresh-package", "ledger", "cardtrader-credentials"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--generator-sha", required=True)
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--apply-drafts", action="store_true")
    args = parser.parse_args()
    try:
        if not __debug__ or sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("non_optimized_root_linux_required")
        os.umask(0o077)
        _, config = drafts.config_values(args.refresh_config)
        if args.state == config["run_root"]:
            raise ValueError("importer_and_refresh_locks_must_be_separate")
        with refresh.pipeline_lock(args.state):
            card_credentials = refresh.document(args.cardtrader_credentials)
            shop_credentials = refresh.document(config["config"] / "shopify-app-credentials.json")
            result = cycle(
                args.state,
                args.refresh_config,
                args.refresh_package,
                args.ledger,
                args.generator_sha,
                CardTraderCatalogClient(card_credentials["api_token"]),
                ShopifyCaptureHttp(
                    shop_domain=config["shop"],
                    api_version="2026-07",
                    client_id=shop_credentials["client_id"],
                    client_secret=shop_credentials["client_secret"],
                ),
                apply_drafts=args.apply_drafts,
                max_attempts=args.max_attempts,
                max_batches=args.max_batches,
            )
        print(json.dumps(result))
        return 0
    except (Exception, KeyboardInterrupt):
        print(json.dumps(dict(status="market_cycle_stopped_inspect_pending", published=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
