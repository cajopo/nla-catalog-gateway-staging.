from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from urllib.parse import quote_plus

import pytest

import nla_catalog_gateway.app_proxy_security as security
from nla_catalog_gateway.app_proxy_security import (
    AppProxyConfigurationError,
    AppProxyErrorCode,
    AppProxyVerificationError,
    AppProxyVerifier,
    AppProxyVerifierConfig,
    DeploymentEnvironment,
    GatewayExposurePolicy,
    IngressDecision,
)

_OFFICIAL_VECTOR_KEY = b"hush"
_ATTACKER_VECTOR_KEY = b"attacker"
_TEST_SHOP = "nla-synthetic.myshopify.com"
_OTHER_SHOP = "other-synthetic.myshopify.com"
_STOREFRONT_PREFIX = "/apps/nla-catalog"
_BACKEND_PREFIX = "/proxy"
_NOW = 2_000_000_000


def _config(**changes: object) -> AppProxyVerifierConfig:
    values: dict[str, object] = {
        "shared_secret": _OFFICIAL_VECTOR_KEY,
        "allowed_shops": frozenset({_TEST_SHOP}),
        "allowed_path_prefixes": frozenset({_STOREFRONT_PREFIX}),
        "backend_path_prefix": _BACKEND_PREFIX,
    }
    values.update(changes)
    return AppProxyVerifierConfig(**values)  # type: ignore[arg-type]


def _attacker_config_snapshot() -> security._VerifierConfigSnapshot:
    return security._VerifierConfigSnapshot(
        _ATTACKER_VECTOR_KEY,
        frozenset({_OTHER_SHOP}),
        frozenset({"/apps/attacker"}),
        "/owned",
        security.DEFAULT_REPLAY_WINDOW_SECONDS,
        security.DEFAULT_FUTURE_SKEW_SECONDS,
        security.DEFAULT_MAX_QUERY_BYTES,
        security.DEFAULT_MAX_PARAMETER_COUNT,
        security.DEFAULT_MAX_COMPONENT_BYTES,
        security.DEFAULT_MAX_REQUEST_PATH_BYTES,
    )


def _base_pairs(
    *, timestamp: str = str(_NOW), customer_id: str | None = "7"
) -> list[tuple[str, str]]:
    pairs = [
        ("extra", "1"),
        ("extra", "2"),
        ("shop", _TEST_SHOP),
        ("path_prefix", _STOREFRONT_PREFIX),
        ("timestamp", timestamp),
    ]
    if customer_id is not None:
        pairs.append(("logged_in_customer_id", customer_id))
    return pairs


def _canonical_message(pairs: list[tuple[str, str]]) -> bytes:
    grouped: dict[str, list[str]] = {}
    for key, value in pairs:
        grouped.setdefault(key, []).append(value)
    entries = sorted(f"{key}={','.join(values)}" for key, values in grouped.items())
    return "".join(entries).encode()


def _signed_query(
    pairs: list[tuple[str, str]] | None = None,
    *,
    key: bytes = _OFFICIAL_VECTOR_KEY,
) -> bytes:
    effective = _base_pairs() if pairs is None else pairs
    digest = hmac.new(key, _canonical_message(effective), hashlib.sha256).hexdigest()
    encoded = [
        f"{quote_plus(name, safe='')}={quote_plus(value, safe='')}" for name, value in effective
    ]
    encoded.append(f"signature={digest}")
    return "&".join(encoded).encode()


def _verifier(
    *,
    config: AppProxyVerifierConfig | None = None,
    clock: Callable[[], int] = lambda: _NOW,
) -> AppProxyVerifier:
    return AppProxyVerifier(config or _config(), clock=clock)


def _assert_error(
    code: AppProxyErrorCode,
    *,
    raw_query: bytes,
    request_path: object = "/proxy/catalog",
    verifier: AppProxyVerifier | None = None,
) -> AppProxyVerificationError:
    with pytest.raises(AppProxyVerificationError) as raised:
        (verifier or _verifier()).verify(
            raw_query=raw_query,
            request_path=request_path,  # type: ignore[arg-type]
        )
    assert raised.value.code is code
    assert str(raised.value) == security.PUBLIC_APP_PROXY_ERRORS[code]
    return raised.value


@pytest.mark.parametrize(
    ("raw_query", "expected_message", "expected_signature"),
    [
        (
            b"extra=1&extra=2&shop={shop}.myshopify.com&logged_in_customer_id=1&"
            b"path_prefix=%2Fapps%2Fawesome_reviews&timestamp=1317327555&"
            b"signature=4c68c8624d737112c91818c11017d24d334b524cb5c2b8ba08daa056f7395ddb",
            b"extra=1,2logged_in_customer_id=1path_prefix=/apps/awesome_reviewsshop="
            b"{shop}.myshopify.comtimestamp=1317327555",
            "4c68c8624d737112c91818c11017d24d334b524cb5c2b8ba08daa056f7395ddb",
        ),
        (
            b"extra=1&extra=2&shop={shop}.myshopify.com&logged_in_customer_id=&"
            b"path_prefix=%2Fapps%2Fawesome_reviews&timestamp=1317327555&"
            b"signature=e072b6d7e6622d85912a5214b860d3100dc1e73d9bc29f43796ac8c9ff8093cb",
            b"extra=1,2logged_in_customer_id=path_prefix=/apps/awesome_reviewsshop="
            b"{shop}.myshopify.comtimestamp=1317327555",
            "e072b6d7e6622d85912a5214b860d3100dc1e73d9bc29f43796ac8c9ff8093cb",
        ),
    ],
)
def test_current_shopify_official_vectors_are_exact(
    raw_query: bytes,
    expected_message: bytes,
    expected_signature: str,
) -> None:
    canonical = security._canonicalize_query(raw_query, _config())
    assert canonical.message == expected_message
    assert canonical.signature == expected_signature
    # Shopify publishes a redacted ``{shop}`` placeholder, so the displayed digest
    # cannot be recomputed from the displayed query.  The assertions above anchor
    # both published values; the valid adapted vector is exercised end-to-end below.


def test_valid_request_exposes_only_validated_protocol_gate_metadata() -> None:
    query = _signed_query()
    verified = _verifier().verify(raw_query=query, request_path="/proxy/catalog/search")

    assert verified.shop == _TEST_SHOP
    assert verified.path_prefix == _STOREFRONT_PREFIX
    assert verified.request_path == "/proxy/catalog/search"
    assert verified.timestamp == _NOW
    assert verified._fields == ("shop", "path_prefix", "request_path", "timestamp")
    assert not hasattr(verified, "claimed_logged_in_customer_id")
    assert not hasattr(verified, "parameters")
    assert repr(verified) == "VerifiedAppProxyRequest()"
    with pytest.raises(AttributeError):
        object.__setattr__(verified, "shop", _OTHER_SHOP)


@pytest.mark.parametrize("customer_id", [None, "", "7"])
def test_customer_claim_is_validated_then_discarded(
    customer_id: str | None,
) -> None:
    verified = _verifier().verify(
        raw_query=_signed_query(_base_pairs(customer_id=customer_id)),
        request_path="/proxy",
    )
    assert not hasattr(verified, "claimed_logged_in_customer_id")
    assert not hasattr(verified, "parameters")


def test_percent_decoding_plus_unicode_and_full_entry_sort_follow_protocol() -> None:
    pairs = [*_base_pairs(), ("phrase", "Café snow ☃"), ("a", "last"), ("a1", "first")]
    verified = _verifier().verify(raw_query=_signed_query(pairs), request_path="/proxy/catalog")
    canonical = security._canonicalize_query(_signed_query(pairs), _config())
    assert "phrase=Café snow ☃".encode() in canonical.message
    assert not hasattr(verified, "parameters")
    assert _canonical_message(pairs).index(b"a1=first") < _canonical_message(pairs).index(b"a=last")


def test_separator_free_application_parameter_collision_is_never_exposed() -> None:
    protocol_pairs = [pair for pair in _base_pairs(customer_id=None) if pair[0] != "extra"]
    first_pairs = [("a", "1b"), ("c", "2"), *protocol_pairs]
    second_pairs = [("a", "1"), ("bc", "2"), *protocol_pairs]

    assert _canonical_message(first_pairs) == _canonical_message(second_pairs)
    first_query = _signed_query(first_pairs)
    second_query = _signed_query(second_pairs)
    assert first_query != second_query
    assert first_query.rsplit(b"signature=", 1)[1] == second_query.rsplit(b"signature=", 1)[1]
    first_canonical = security._canonicalize_query(first_query, _config())
    second_canonical = security._canonicalize_query(second_query, _config())
    assert first_canonical.gate_parameters == second_canonical.gate_parameters
    assert not hasattr(first_canonical, "parameters")
    assert all(
        key in security._SECURITY_PARAMETER_NAMES for key, _value in first_canonical.gate_parameters
    )

    first = _verifier().verify(raw_query=first_query, request_path="/proxy/catalog")
    second = _verifier().verify(raw_query=second_query, request_path="/proxy/catalog")
    assert first == second
    assert not hasattr(first, "parameters")
    assert not hasattr(second, "parameters")


def test_separator_free_customer_claim_collision_cannot_create_authority() -> None:
    protocol_pairs = [pair for pair in _base_pairs(customer_id=None) if pair[0] != "extra"]
    without_claim = [("a", "1logged_in_customer_i"), ("d", "7"), *protocol_pairs]
    with_claim = [("a", "1"), ("logged_in_customer_id", "7"), *protocol_pairs]

    assert _canonical_message(without_claim) == _canonical_message(with_claim)
    unsigned_claim_result = _verifier().verify(
        raw_query=_signed_query(without_claim), request_path="/proxy/catalog"
    )
    claimed_result = _verifier().verify(
        raw_query=_signed_query(with_claim), request_path="/proxy/catalog"
    )
    assert unsigned_claim_result == claimed_result
    assert not hasattr(unsigned_claim_result, "claimed_logged_in_customer_id")
    assert not hasattr(claimed_result, "claimed_logged_in_customer_id")
    assert not hasattr(claimed_result, "parameters")


def test_lowercase_percent_hex_is_equivalent_after_one_decode() -> None:
    query = _signed_query().replace(b"%2Fapps%2Fnla-catalog", b"%2fapps%2fnla-catalog")
    assert _verifier().verify(raw_query=query, request_path="/proxy").path_prefix == (
        _STOREFRONT_PREFIX
    )


def test_signature_uses_constant_time_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    original = security.hmac.compare_digest
    calls: list[tuple[str, str]] = []

    def recording_compare(left: str, right: str) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(security.hmac, "compare_digest", recording_compare)
    _verifier().verify(raw_query=_signed_query(), request_path="/proxy")
    assert len(calls) == 1
    assert len(calls[0][0]) == len(calls[0][1]) == 64


def test_tampering_is_rejected_without_echoing_sensitive_material() -> None:
    query = _signed_query()
    tampered = query.replace(b"extra=1", b"extra=9")
    error = _assert_error(AppProxyErrorCode.INVALID_SIGNATURE, raw_query=tampered)
    assert _TEST_SHOP not in repr(error)
    assert query.decode() not in repr(error)
    assert _OFFICIAL_VECTOR_KEY.decode() not in repr(_config())


@pytest.mark.parametrize(
    "replacement",
    [
        b"A" * 64,
        b"a" * 63,
        b"g" * 64,
        b"%61" + b"a" * 63,
    ],
)
def test_signature_encoding_length_case_and_alphabet_are_strict(replacement: bytes) -> None:
    query = _signed_query()
    start = query.index(b"signature=") + len(b"signature=")
    malformed = query[:start] + replacement
    _assert_error(AppProxyErrorCode.INVALID_SIGNATURE, raw_query=malformed)


def test_percent_encoded_non_ascii_signature_is_a_bounded_signature_error() -> None:
    query = _signed_query()
    start = query.index(b"signature=") + len(b"signature=")
    malformed = query[:start] + b"%C3%A9"
    error = _assert_error(AppProxyErrorCode.INVALID_SIGNATURE, raw_query=malformed)
    assert error.__cause__ is None


@pytest.mark.parametrize(
    "name",
    ["shop", "timestamp", "path_prefix", "logged_in_customer_id", "signature"],
)
def test_duplicate_security_parameters_fail_closed(name: str) -> None:
    if name == "signature":
        query = _signed_query() + b"&signature=" + b"a" * 64
    else:
        pairs = [*_base_pairs(), (name, dict(_base_pairs())[name])]
        query = _signed_query(pairs)
    _assert_error(AppProxyErrorCode.INVALID_QUERY, raw_query=query)


@pytest.mark.parametrize("name", ["shop", "timestamp", "path_prefix", "signature"])
def test_percent_encoded_security_parameter_names_are_rejected(name: str) -> None:
    query = _signed_query()
    encoded_name = f"%{ord(name[0]):02X}{name[1:]}".encode()
    query = query.replace(f"{name}=".encode(), encoded_name + b"=", 1)
    _assert_error(AppProxyErrorCode.INVALID_QUERY, raw_query=query)


@pytest.mark.parametrize("missing", ["shop", "timestamp", "path_prefix", "signature"])
def test_required_security_parameters_cannot_be_removed(missing: str) -> None:
    query = _signed_query()
    segments = [
        segment for segment in query.split(b"&") if not segment.startswith(f"{missing}=".encode())
    ]
    _assert_error(AppProxyErrorCode.INVALID_QUERY, raw_query=b"&".join(segments))


def test_oauth_hmac_parameter_is_not_confused_with_app_proxy_signature() -> None:
    _assert_error(
        AppProxyErrorCode.INVALID_QUERY,
        raw_query=_signed_query([*_base_pairs(), ("hmac", "a" * 64)]),
    )


@pytest.mark.parametrize("raw_query", [b"", bytearray(b"a=b"), "a=b"])
def test_query_must_be_nonempty_exact_bytes(raw_query: object) -> None:
    _assert_error(
        AppProxyErrorCode.INVALID_QUERY,
        raw_query=raw_query,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda query: query + b"&",
        lambda query: query.replace(b"extra=1", b"extra", 1),
        lambda query: query.replace(b"extra=1", b"=1", 1),
        lambda query: query.replace(b"extra=1", b"bad+key=1", 1),
        lambda query: query.replace(b"extra=1", b"extra=%", 1),
        lambda query: query.replace(b"extra=1", b"extra=%GG", 1),
        lambda query: query.replace(b"extra=1", b"extra=%FF", 1),
        lambda query: query.replace(b"extra=1", b"extra=%0A", 1),
        lambda query: query.replace(b"extra=1", b"extra=%252F", 1),
        lambda query: query.replace(b"extra=1", b"extra=x%3Dy", 1),
        lambda query: query + b"#fragment",
        lambda query: query.replace(b"extra=1", b"extra=\xff", 1),
    ],
)
def test_malformed_and_ambiguous_query_encodings_are_rejected(
    mutation: Callable[[bytes], bytes],
) -> None:
    _assert_error(AppProxyErrorCode.INVALID_QUERY, raw_query=mutation(_signed_query()))


def test_non_nfc_unicode_is_rejected_as_ambiguous() -> None:
    _assert_error(
        AppProxyErrorCode.INVALID_QUERY,
        raw_query=_signed_query([*_base_pairs(), ("phrase", "é")]),
    )


def test_raw_query_byte_limit_is_enforced_and_inclusive() -> None:
    pairs = [*_base_pairs(), ("padding", "x" * 100)]
    query = _signed_query(pairs)
    assert len(query) > 256
    exact = _verifier(config=_config(max_query_bytes=len(query), max_component_bytes=len(query)))
    exact.verify(raw_query=query, request_path="/proxy")
    too_small = _verifier(
        config=_config(max_query_bytes=len(query) - 1, max_component_bytes=len(query) - 1)
    )
    _assert_error(AppProxyErrorCode.QUERY_LIMIT_EXCEEDED, raw_query=query, verifier=too_small)


def test_parameter_count_limit_is_enforced_and_inclusive() -> None:
    minimal = [
        ("shop", _TEST_SHOP),
        ("path_prefix", _STOREFRONT_PREFIX),
        ("timestamp", str(_NOW)),
    ]
    query = _signed_query(minimal)
    _verifier(config=_config(max_parameter_count=4)).verify(
        raw_query=query,
        request_path="/proxy",
    )
    _assert_error(
        AppProxyErrorCode.QUERY_LIMIT_EXCEEDED,
        raw_query=_signed_query([*minimal, ("extra", "1")]),
        verifier=_verifier(config=_config(max_parameter_count=4)),
    )


@pytest.mark.parametrize("value", ["x" * 65, "%" + "41" * 96])
def test_decoded_and_raw_component_limits_are_enforced(value: str) -> None:
    pairs = [*_base_pairs(), ("extra_limit", value)]
    if value.startswith("%"):
        query = _signed_query().replace(b"extra=1", f"extra_limit={value}".encode(), 1)
    else:
        query = _signed_query(pairs)
    _assert_error(
        AppProxyErrorCode.QUERY_LIMIT_EXCEEDED,
        raw_query=query,
        verifier=_verifier(config=_config(max_component_bytes=64)),
    )


@pytest.mark.parametrize(
    "shop",
    ["NLA-SYNTHETIC.myshopify.com", "nla-synthetic.example.com", _OTHER_SHOP],
)
def test_shop_must_be_canonical_myshopify_domain_and_allowlisted(shop: str) -> None:
    pairs = [(key, shop if key == "shop" else value) for key, value in _base_pairs()]
    _assert_error(AppProxyErrorCode.INVALID_SHOP, raw_query=_signed_query(pairs))


@pytest.mark.parametrize(
    "path_prefix",
    ["/apps/other", "/apps/nla-catalog/child", "//apps/nla-catalog"],
)
def test_signed_storefront_path_prefix_must_match_allowlist(path_prefix: str) -> None:
    pairs = [(key, path_prefix if key == "path_prefix" else value) for key, value in _base_pairs()]
    _assert_error(AppProxyErrorCode.INVALID_PATH, raw_query=_signed_query(pairs))


@pytest.mark.parametrize(
    "request_path",
    [
        "/api/catalog",
        "/proxyevil/catalog",
        "/proxy/../api",
        "/proxy//catalog",
        "/proxy/%2e%2e/api",
        "/pröxy",
        7,
    ],
)
def test_backend_request_path_cannot_bypass_proxy_namespace(request_path: object) -> None:
    _assert_error(
        AppProxyErrorCode.INVALID_PATH,
        raw_query=_signed_query(),
        request_path=request_path,
    )


def test_configured_request_path_byte_limit_is_enforced() -> None:
    request_path = "/proxy/" + "a" * 70
    _assert_error(
        AppProxyErrorCode.INVALID_PATH,
        raw_query=_signed_query(),
        request_path=request_path,
        verifier=_verifier(config=_config(max_request_path_bytes=64)),
    )


@pytest.mark.parametrize("timestamp", ["-1", "01", "1.0", "9223372036854775808"])
def test_timestamp_must_be_canonical_signed_64_bit_epoch_seconds(timestamp: str) -> None:
    _assert_error(
        AppProxyErrorCode.INVALID_TIMESTAMP,
        raw_query=_signed_query(_base_pairs(timestamp=timestamp)),
    )


@pytest.mark.parametrize("offset", [-300, 30])
def test_replay_and_future_boundaries_are_inclusive(offset: int) -> None:
    verified = _verifier().verify(
        raw_query=_signed_query(_base_pairs(timestamp=str(_NOW + offset))),
        request_path="/proxy",
    )
    assert verified.timestamp == _NOW + offset


@pytest.mark.parametrize(
    ("offset", "code"),
    [
        (-301, AppProxyErrorCode.EXPIRED_REQUEST),
        (31, AppProxyErrorCode.FUTURE_REQUEST),
    ],
)
def test_requests_outside_replay_window_are_rejected(
    offset: int,
    code: AppProxyErrorCode,
) -> None:
    _assert_error(
        code,
        raw_query=_signed_query(_base_pairs(timestamp=str(_NOW + offset))),
    )


@pytest.mark.parametrize("customer_id", ["0", "01", "abc", "9223372036854775808"])
def test_customer_id_claim_must_be_empty_or_canonical_positive_integer(
    customer_id: str,
) -> None:
    _assert_error(
        AppProxyErrorCode.INVALID_QUERY,
        raw_query=_signed_query(_base_pairs(customer_id=customer_id)),
    )


@pytest.mark.parametrize("clock_value", [True, 1.5, -1, 2**63])
def test_clock_result_must_be_canonical_epoch_seconds(clock_value: object) -> None:
    verifier = _verifier(clock=lambda: clock_value)  # type: ignore[return-value]
    with pytest.raises(AppProxyConfigurationError, match="clock returned"):
        verifier.verify(raw_query=_signed_query(), request_path="/proxy")


def test_ordinary_clock_exception_is_normalized_without_cause() -> None:
    def broken_clock() -> int:
        raise RuntimeError("sensitive callback detail")

    with pytest.raises(AppProxyConfigurationError, match="clock failed") as raised:
        _verifier(clock=broken_clock).verify(raw_query=_signed_query(), request_path="/proxy")
    assert raised.value.__cause__ is None
    assert "sensitive" not in str(raised.value)


def test_base_exception_from_clock_is_not_swallowed() -> None:
    def interrupted_clock() -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _verifier(clock=interrupted_clock).verify(raw_query=_signed_query(), request_path="/proxy")


@pytest.mark.parametrize(
    "changes",
    [
        {"shared_secret": b""},
        {"shared_secret": "hush"},
        {"shared_secret": b"x" * 4097},
        {"allowed_shops": set()},
        {"allowed_shops": frozenset()},
        {"allowed_shops": frozenset({"bad.example.com"})},
        {"allowed_shops": frozenset({_TEST_SHOP, 7})},
        {"allowed_shops": frozenset(f"s{index}.myshopify.com" for index in range(33))},
        {"allowed_path_prefixes": set()},
        {"allowed_path_prefixes": frozenset()},
        {"allowed_path_prefixes": frozenset({"relative"})},
        {"allowed_path_prefixes": frozenset({_STOREFRONT_PREFIX, 7})},
        {"allowed_path_prefixes": frozenset(f"/apps/p{index}" for index in range(33))},
        {"backend_path_prefix": "relative"},
        {"replay_window_seconds": 0},
        {"replay_window_seconds": 3601},
        {"replay_window_seconds": True},
        {"future_skew_seconds": -1},
        {"future_skew_seconds": 301},
        {"max_query_bytes": 255},
        {"max_query_bytes": 65537},
        {"max_parameter_count": 3},
        {"max_parameter_count": 257},
        {"max_component_bytes": 63},
        {"max_component_bytes": 8193},
        {"max_request_path_bytes": 63},
        {"max_request_path_bytes": 8193},
    ],
)
def test_invalid_verifier_configuration_fails_at_startup(changes: dict[str, object]) -> None:
    with pytest.raises(AppProxyConfigurationError):
        _config(**changes)


def test_valid_configuration_boundary_values_are_supported() -> None:
    config = _config(
        replay_window_seconds=3600,
        future_skew_seconds=0,
        max_query_bytes=65536,
        max_parameter_count=256,
        max_component_bytes=65536,
        max_request_path_bytes=8192,
    )
    assert config.future_skew_seconds == 0


def test_verifier_snapshots_every_config_field_against_alias_mutation() -> None:
    config = _config()
    verifier = _verifier(config=config)
    old_pairs = [
        *_base_pairs(timestamp=str(_NOW - security.DEFAULT_REPLAY_WINDOW_SECONDS)),
        ("padding", "x" * 100),
    ]
    future_pairs = _base_pairs(timestamp=str(_NOW + security.DEFAULT_FUTURE_SKEW_SECONDS))
    long_path = "/proxy/" + "a" * 70

    object.__setattr__(config, "shared_secret", _ATTACKER_VECTOR_KEY)
    object.__setattr__(config, "allowed_shops", frozenset({_OTHER_SHOP}))
    object.__setattr__(config, "allowed_path_prefixes", frozenset({"/apps/attacker"}))
    object.__setattr__(config, "backend_path_prefix", "/owned")
    object.__setattr__(config, "replay_window_seconds", 1)
    object.__setattr__(config, "future_skew_seconds", 0)
    object.__setattr__(config, "max_query_bytes", 256)
    object.__setattr__(config, "max_parameter_count", 4)
    object.__setattr__(config, "max_component_bytes", 64)
    object.__setattr__(config, "max_request_path_bytes", 64)

    assert verifier.verify(raw_query=_signed_query(old_pairs), request_path=long_path).shop == (
        _TEST_SHOP
    )
    assert (
        verifier.verify(
            raw_query=_signed_query(future_pairs),
            request_path="/proxy",
        ).timestamp
        == _NOW + security.DEFAULT_FUTURE_SKEW_SECONDS
    )

    attacker_pairs = [
        (key, _OTHER_SHOP if key == "shop" else value)
        for key, value in _base_pairs()
        if key != "path_prefix"
    ]
    attacker_pairs.append(("path_prefix", "/apps/attacker"))
    _assert_error(
        AppProxyErrorCode.INVALID_SIGNATURE,
        raw_query=_signed_query(attacker_pairs, key=_ATTACKER_VECTOR_KEY),
        request_path="/owned",
        verifier=verifier,
    )

    assert "hush" not in repr(verifier)
    for attribute in ("_config", "_clock", "_snapshot", "_state"):
        with pytest.raises(AttributeError):
            object.__getattribute__(verifier, attribute)


def test_verifier_revalidates_corrupted_and_incomplete_config_instances() -> None:
    corrupted = _config()
    object.__setattr__(corrupted, "max_query_bytes", 0)
    with pytest.raises(AppProxyConfigurationError, match="dependencies"):
        AppProxyVerifier(corrupted)

    incomplete = object.__new__(AppProxyVerifierConfig)
    object.__setattr__(incomplete, "shared_secret", _OFFICIAL_VECTOR_KEY)
    with pytest.raises(AppProxyConfigurationError, match="dependencies"):
        AppProxyVerifier(incomplete)


def test_forged_verifier_instance_fails_closed() -> None:
    forged = object.__new__(AppProxyVerifier)
    attacker_snapshot = _attacker_config_snapshot()
    attacker_state = security._VerifierRuntimeState(attacker_snapshot, lambda: _NOW)
    assert "attacker" not in repr(attacker_snapshot)
    assert "attacker" not in repr(attacker_state)

    for attribute, value in (
        ("_config", attacker_snapshot),
        ("_clock", lambda: _NOW),
        ("_state", attacker_state),
    ):
        with pytest.raises(AttributeError):
            object.__setattr__(forged, attribute, value)

    with pytest.raises(AppProxyConfigurationError, match="dependencies"):
        forged.verify(
            raw_query=_signed_query(key=_ATTACKER_VECTOR_KEY),
            request_path="/owned",
        )


def test_verifier_runtime_state_cannot_be_replaced_or_transplanted() -> None:
    verifier = _verifier()
    attacker_snapshot = _attacker_config_snapshot()
    attacker_state = security._VerifierRuntimeState(attacker_snapshot, lambda: _NOW)
    attacker_config = _config(
        **{
            "shared_secret": _ATTACKER_VECTOR_KEY,
            "allowed_shops": frozenset({_OTHER_SHOP}),
            "allowed_path_prefixes": frozenset({"/apps/attacker"}),
            "backend_path_prefix": "/owned",
        }
    )
    other = _verifier(config=attacker_config)

    for attribute, value in (
        ("_config", attacker_snapshot),
        ("_clock", lambda: _NOW),
        ("_state", attacker_state),
    ):
        with pytest.raises(AttributeError):
            object.__setattr__(verifier, attribute, value)
        with pytest.raises(AttributeError):
            object.__getattribute__(other, attribute)

    with pytest.raises(AppProxyConfigurationError, match="already initialized"):
        AppProxyVerifier.__init__(verifier, attacker_config, clock=lambda: _NOW)

    assert verifier.verify(raw_query=_signed_query(), request_path="/proxy").shop == _TEST_SHOP
    attacker_pairs = [
        (key, _OTHER_SHOP if key == "shop" else value)
        for key, value in _base_pairs()
        if key != "path_prefix"
    ]
    attacker_pairs.append(("path_prefix", "/apps/attacker"))
    _assert_error(
        AppProxyErrorCode.INVALID_SIGNATURE,
        raw_query=_signed_query(attacker_pairs, key=_ATTACKER_VECTOR_KEY),
        request_path="/owned",
        verifier=verifier,
    )


def test_verifier_subclasses_are_not_a_runtime_state_boundary() -> None:
    class ForgedVerifier(AppProxyVerifier):
        pass

    with pytest.raises(AppProxyConfigurationError, match="dependencies"):
        ForgedVerifier(_config(), clock=lambda: _NOW)

    forged = object.__new__(ForgedVerifier)
    with pytest.raises(AppProxyConfigurationError, match="dependencies"):
        forged.verify(raw_query=_signed_query(), request_path="/proxy")


@pytest.mark.parametrize("config", [object(), None])
def test_verifier_rejects_non_config_dependencies(config: object) -> None:
    with pytest.raises(AppProxyConfigurationError, match="dependencies"):
        AppProxyVerifier(config)  # type: ignore[arg-type]


def test_verifier_rejects_non_callable_clock() -> None:
    with pytest.raises(AppProxyConfigurationError, match="dependencies"):
        AppProxyVerifier(_config(), clock=7)  # type: ignore[arg-type]


def test_default_clock_returns_current_integer_seconds() -> None:
    before = security.time.time_ns() // 1_000_000_000
    observed = security._default_clock()
    after = security.time.time_ns() // 1_000_000_000
    assert type(observed) is int
    assert before <= observed <= after


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/proxy", IngressDecision.REQUIRE_APP_PROXY),
        ("/proxy/catalog", IngressDecision.REQUIRE_APP_PROXY),
        ("/proxyevil", IngressDecision.DENY),
        ("/api", IngressDecision.DENY),
        ("/api/catalog", IngressDecision.DENY),
        ("/unknown", IngressDecision.DENY),
        ("/api/../proxy", IngressDecision.DENY),
    ],
)
def test_staging_route_policy_has_no_direct_origin_bypass(
    path: str,
    expected: IngressDecision,
) -> None:
    policy = GatewayExposurePolicy(DeploymentEnvironment.STAGING, "/proxy")
    assert policy.decision(path) is expected


def test_development_bypass_requires_an_explicit_development_only_flag() -> None:
    default = GatewayExposurePolicy(DeploymentEnvironment.DEVELOPMENT, "/proxy")
    explicit = GatewayExposurePolicy(
        DeploymentEnvironment.DEVELOPMENT,
        "/proxy",
        allow_development_direct_origin=True,
    )
    assert default.decision("/api/catalog") is IngressDecision.DENY
    assert explicit.decision("/api") is IngressDecision.DEVELOPMENT_BYPASS
    assert explicit.decision("/api/catalog") is IngressDecision.DEVELOPMENT_BYPASS


def test_exposure_decision_uses_validated_snapshot_not_mutable_public_fields() -> None:
    policy = GatewayExposurePolicy(DeploymentEnvironment.PRODUCTION, "/proxy")
    for attribute, value in (
        ("environment", DeploymentEnvironment.DEVELOPMENT),
        ("allow_development_direct_origin", True),
        ("proxy_route_prefix", "/api"),
        ("direct_api_route_prefix", "/owned"),
    ):
        with pytest.raises(AttributeError):
            object.__setattr__(policy, attribute, value)

    assert policy.environment is DeploymentEnvironment.PRODUCTION
    assert policy.proxy_route_prefix == "/proxy"
    assert policy.direct_api_route_prefix == "/api"
    assert policy.allow_development_direct_origin is False
    assert policy.decision("/proxy/catalog") is IngressDecision.REQUIRE_APP_PROXY
    assert policy.decision("/api/catalog") is IngressDecision.DENY
    assert policy.decision("/owned/catalog") is IngressDecision.DENY


def test_forged_exposure_policy_without_validated_snapshot_denies() -> None:
    forged = object.__new__(GatewayExposurePolicy)
    exact_snapshot = security._ExposurePolicySnapshot(
        DeploymentEnvironment.DEVELOPMENT,
        "/proxy",
        "/api",
        True,
    )
    for attribute, value in (
        ("environment", DeploymentEnvironment.DEVELOPMENT),
        ("proxy_route_prefix", "/proxy"),
        ("direct_api_route_prefix", "/api"),
        ("allow_development_direct_origin", True),
        ("_snapshot", exact_snapshot),
        ("_state", exact_snapshot),
    ):
        with pytest.raises(AttributeError):
            object.__setattr__(forged, attribute, value)

    assert forged.decision("/api/catalog") is IngressDecision.DENY
    with pytest.raises(AppProxyConfigurationError, match="state is invalid"):
        _ = forged.environment


def test_exposure_policy_state_cannot_be_replaced_or_transplanted() -> None:
    production = GatewayExposurePolicy(DeploymentEnvironment.PRODUCTION, "/proxy")
    development = GatewayExposurePolicy(
        DeploymentEnvironment.DEVELOPMENT,
        "/owned",
        allow_development_direct_origin=True,
    )
    exact_development_snapshot = security._ExposurePolicySnapshot(
        development.environment,
        development.proxy_route_prefix,
        development.direct_api_route_prefix,
        development.allow_development_direct_origin,
    )

    with pytest.raises(AttributeError):
        object.__getattribute__(development, "_snapshot")
    for attribute in ("_snapshot", "_state"):
        with pytest.raises(AttributeError):
            object.__setattr__(production, attribute, exact_development_snapshot)
    with pytest.raises(AppProxyConfigurationError, match="already initialized"):
        GatewayExposurePolicy.__init__(
            production,
            DeploymentEnvironment.DEVELOPMENT,
            "/owned",
            allow_development_direct_origin=True,
        )

    assert production.decision("/api/catalog") is IngressDecision.DENY
    assert production.decision("/owned/catalog") is IngressDecision.DENY
    assert production.decision("/proxy/catalog") is IngressDecision.REQUIRE_APP_PROXY


def test_exposure_policy_subclasses_are_not_a_runtime_state_boundary() -> None:
    class ForgedPolicy(GatewayExposurePolicy):
        pass

    with pytest.raises(AppProxyConfigurationError, match="type is invalid"):
        ForgedPolicy(DeploymentEnvironment.DEVELOPMENT, "/proxy")

    forged = object.__new__(ForgedPolicy)
    assert forged.decision("/api/catalog") is IngressDecision.DENY
    with pytest.raises(AppProxyConfigurationError, match="state is invalid"):
        _ = forged.environment


@pytest.mark.parametrize(
    "environment",
    [DeploymentEnvironment.STAGING, DeploymentEnvironment.PRODUCTION],
)
def test_direct_origin_bypass_fails_startup_outside_development(
    environment: DeploymentEnvironment,
) -> None:
    with pytest.raises(AppProxyConfigurationError, match="forbidden outside development"):
        GatewayExposurePolicy(
            environment,
            "/proxy",
            allow_development_direct_origin=True,
        )


@pytest.mark.parametrize(
    "values",
    [
        {"environment": "production", "proxy_route_prefix": "/proxy"},
        {"environment": DeploymentEnvironment.PRODUCTION, "proxy_route_prefix": "proxy"},
        {
            "environment": DeploymentEnvironment.PRODUCTION,
            "proxy_route_prefix": "/proxy",
            "direct_api_route_prefix": "api",
        },
        {
            "environment": DeploymentEnvironment.PRODUCTION,
            "proxy_route_prefix": "/api/proxy",
            "direct_api_route_prefix": "/api",
        },
        {
            "environment": DeploymentEnvironment.PRODUCTION,
            "proxy_route_prefix": "/proxy",
            "direct_api_route_prefix": "/proxy/api",
        },
        {
            "environment": DeploymentEnvironment.DEVELOPMENT,
            "proxy_route_prefix": "/proxy",
            "allow_development_direct_origin": 1,
        },
    ],
)
def test_invalid_exposure_policy_fails_at_startup(values: dict[str, object]) -> None:
    with pytest.raises(AppProxyConfigurationError):
        GatewayExposurePolicy(**values)  # type: ignore[arg-type]


def test_public_error_and_security_header_contracts_are_fixed_and_non_sensitive() -> None:
    assert set(security.PUBLIC_APP_PROXY_ERRORS) == set(AppProxyErrorCode)
    headers = security.CATALOG_JSON_SECURITY_HEADERS
    assert headers["Cache-Control"] == "private, no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "Access-Control-Allow-Origin" not in headers
    with pytest.raises(TypeError):
        headers["Access-Control-Allow-Origin"] = "*"  # type: ignore[index]
