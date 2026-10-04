#!/usr/bin/env python3
"""Load, promote, or roll back staging activation with value-free output."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from nla_catalog_gateway.staging_activation import (
    StagingActivationOutcomeAmbiguous,
    load_active_staging_generation,
    promote_staging_generation,
    rollback_staging_generation,
)

_ROOT_ENV = "NLA_STAGING_STORE_ROOT"
_ACTION_ENV = "NLA_STAGING_ACTIVATION_ACTION"
_PIN_ENV = "NLA_STAGING_ACTIVATION_SHA256"
_CANDIDATE_ENV = "NLA_STAGING_CANDIDATE_MANIFEST_SHA256"


def run_action(
    root_directory: Path,
    action: str,
    expected_activation_sha256: str,
    candidate_manifest_sha256: str | None = None,
) -> object:
    """Execute one explicitly selected operator action."""

    if action == "load" and candidate_manifest_sha256 is None:
        return load_active_staging_generation(root_directory, expected_activation_sha256)
    if action == "promote" and candidate_manifest_sha256 is not None:
        return promote_staging_generation(
            root_directory,
            candidate_manifest_sha256,
            expected_activation_sha256,
        )
    if action == "rollback" and candidate_manifest_sha256 is None:
        return rollback_staging_generation(root_directory, expected_activation_sha256)
    raise ValueError


def main() -> int:
    try:
        if sys.argv[1:]:
            raise ValueError
        candidate = os.environ.get(_CANDIDATE_ENV)
        run_action(
            Path(os.environ[_ROOT_ENV]),
            os.environ[_ACTION_ENV],
            os.environ[_PIN_ENV],
            candidate,
        )
    except StagingActivationOutcomeAmbiguous:
        print("VALUE_FREE_RESULT: AMBIGUOUS")
        return 2
    except Exception:
        print("VALUE_FREE_RESULT: REJECTED")
        return 1
    print("VALUE_FREE_RESULT: ACCEPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_action"]
