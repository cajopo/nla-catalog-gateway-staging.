import copy
import sqlite3
from contextlib import closing

import pytest

from nla_catalog_gateway import expansion_collections as collections


def candidate(**changes):
    return (
        dict(game="lorcana", sourceExpansionId=4, sourceExpansionName="The First Chapter") | changes
    )


def remote(spec=None, **changes):
    spec = spec or collections.expansion_collection_spec(candidate())
    return (
        dict(
            id="gid://shopify/Collection/123",
            handle=spec["handle"],
            identity=dict(type="single_line_text_field", value=spec["identity"]),
            resourcePublicationsCount=dict(count=0),
            sources=[
                dict(
                    __typename="CollectionConditionsSource",
                    targetType="PRODUCTS",
                    inclusion=dict(
                        matchType="ALL",
                        selections=dict(nodes=[]),
                        conditions=[
                            dict(
                                __typename="CollectionSourceInclusionConditionProductTag",
                                relation="TAGGED_WITH",
                                matchType="ALL",
                                values=spec["tags"],
                            )
                        ],
                    ),
                    exclusion=None,
                )
            ],
        )
        | changes
    )


class API:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.creates = []
        self.failure = None

    def graphql(self, query, variables):
        if query == collections.LIST_COLLECTIONS:
            assert variables == dict(after=None)
            return dict(
                collections=dict(nodes=copy.deepcopy(self.rows), pageInfo=dict(hasNextPage=False))
            )
        if query == collections.READ_COLLECTION:
            return dict(
                collection=copy.deepcopy(next(r for r in self.rows if r["id"] == variables["id"]))
            )
        assert query == collections.CREATE_COLLECTION
        value = variables["collection"]
        self.creates.append(copy.deepcopy(value))
        spec = collections.expansion_collection_spec(
            candidate(
                game=value["metafields"][0]["value"].split(":")[1],
                sourceExpansionId=int(value["metafields"][0]["value"].split(":")[2]),
                sourceExpansionName=value["title"],
            )
        )
        row = remote(spec, id=f"gid://shopify/Collection/{len(self.rows) + 123}")
        if self.failure == "rejected":
            return dict(
                collectionCreate=dict(collection=None, userErrors=[dict(message="rejected")])
            )
        self.rows.append(row)
        if self.failure == "lost":
            raise OSError("lost response")
        if self.failure == "handle":
            row["handle"] += "-1"
        return dict(collectionCreate=dict(collection=row, userErrors=[]))


def reconcile(tmp_path, api, specs=None, **kwargs):
    return collections.reconcile_expansion_collections(
        graphql=api.graphql,
        specs=[candidate()] if specs is None else specs,
        state_dir=tmp_path / "state",
        enabled=True,
        **kwargs,
    )


def test_preview_is_default_and_does_not_touch_api_or_files(tmp_path):
    result = collections.reconcile_expansion_collections(
        graphql=None, specs=[candidate()], state_dir=tmp_path / "unused"
    )
    assert result == dict(status="preview", planned=1, created=0, existing=0)
    assert reconcile(tmp_path, API(), []) == dict(
        status="preview", planned=0, created=0, existing=0
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"game": []},
        {"game": "pokemon"},
        {"sourceExpansionId": True},
        {"sourceExpansionId": 0},
        {"sourceExpansionId": 2**63},
        {"sourceExpansionName": None},
        {"sourceExpansionName": " "},
        {"sourceExpansionName": " padded"},
        {"sourceExpansionName": "x" * 256},
        {"sourceExpansionName": "hello\nthere"},
        {"sourceExpansionName": "hello,there"},
        {"sourceExpansionName": "---"},
        {"sourceExpansionName": "LoRcAnA"},
        {"collectionTags": ["Riftbound", "The First Chapter"]},
    ],
)
def test_reject_bad_source_identity(changes):
    with pytest.raises(ValueError, match="invalid_expansion_collection"):
        collections.expansion_collection_spec(candidate(**changes))


def test_normalizes_source_name_and_provided_exact_tags():
    spec = collections.expansion_collection_spec(
        candidate(
            game="riftbound",
            sourceExpansionName="Origini: L'Étape",
            collectionTags=["Riftbound", "Origini: L'Étape"],
        )
    )
    assert spec["handle"] == "origini-l-etape"
    assert spec["identity"] == "cardtrader:riftbound:4"


def test_create_and_repeat_preserve_owner_publication_and_existing_resources(tmp_path):
    legacy = dict(id="gid://shopify/Collection/1", handle="legacy", identity=None)
    api = API([legacy])
    first = reconcile(tmp_path, api, [candidate(), candidate()])
    assert (first["created"], first["existing"], first["planned"]) == (1, 0, 1)
    (value,) = api.creates
    assert set(value) == {"title", "handle", "sortOrder", "metafields", "sources"}
    assert value["sortOrder"] == "BEST_SELLING"
    assert value["sources"][0]["source"]["inclusion"]["conditions"] == [
        dict(
            productTag=dict(
                relation="TAGGED_WITH",
                matchType="ALL",
                values=["Lorcana", "The First Chapter"],
            )
        )
    ]
    api.rows[-1]["resourcePublicationsCount"]["count"] = 1
    api.rows[-1]["handle"] = "owner-renamed"
    second = reconcile(tmp_path, api)
    assert (second["created"], second["existing"]) == (0, 1)
    assert api.rows[0] == legacy and len(api.creates) == 1


def test_existing_identity_is_adopted_read_only_even_if_published(tmp_path):
    api = API([remote(resourcePublicationsCount=dict(count=2))])
    result = reconcile(tmp_path, api)
    assert result["created"] == 0 and result["existing"] == 1 and not api.creates


def test_lost_response_reconciles_by_identity_never_reissues_create(tmp_path):
    api = API()
    api.failure = "lost"
    with pytest.raises(OSError, match="lost response"):
        reconcile(tmp_path, api)
    api.rows[0]["resourcePublicationsCount"]["count"] = 1
    assert reconcile(tmp_path, api)["existing"] == 1
    assert len(api.creates) == 1


@pytest.mark.parametrize(
    "failure,reason", [("rejected", "create_rejected"), ("handle", "handle_changed")]
)
def test_rejected_or_changed_creation_is_durable_and_never_blindly_retried(
    tmp_path, failure, reason
):
    api = API()
    api.failure = failure
    with pytest.raises(ValueError, match=reason):
        reconcile(tmp_path, api)
    api.rows.clear()
    with pytest.raises(ValueError, match="missing_inspect"):
        reconcile(tmp_path, api)
    assert len(api.creates) == 1


def test_completed_collection_cannot_disappear_or_change_id(tmp_path):
    api = API()
    reconcile(tmp_path, api)
    api.rows[0]["id"] = "gid://shopify/Collection/999"
    with pytest.raises(ValueError, match="gid_changed"):
        reconcile(tmp_path, api)
    api.rows.clear()
    with pytest.raises(ValueError, match="missing_inspect"):
        reconcile(tmp_path, api)


def test_source_name_drift_is_not_an_update(tmp_path):
    api = API()
    reconcile(tmp_path, api)
    with pytest.raises(ValueError, match="source_drift"):
        reconcile(tmp_path, api, [candidate(sourceExpansionName="New Source Name")])
    assert len(api.creates) == 1


@pytest.mark.parametrize(
    "specs,reason",
    [
        (
            [candidate(), candidate(sourceExpansionName="Different")],
            "conflicting_expansion_collection_identity",
        ),
        ([candidate(), candidate(sourceExpansionId=5)], "conflicting_expansion_collection_handle"),
    ],
)
def test_batch_conflicts_fail_before_api(tmp_path, specs, reason):
    with pytest.raises(ValueError, match=reason):
        reconcile(tmp_path, API(), specs)
    assert list(tmp_path.iterdir()) == []


def test_invalid_apply_flag():
    with pytest.raises(ValueError, match="invalid_expansion_collection_apply"):
        collections.reconcile_expansion_collections(
            graphql=None, specs=[], state_dir=None, enabled=1
        )


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([remote(), remote()], "duplicate_expansion_collection_identity"),
        ([remote(identity=None)], "handle_occupied"),
    ],
)
def test_handle_never_adopted_as_identity(tmp_path, rows, reason):
    api = API(rows)
    with pytest.raises(ValueError, match=reason):
        reconcile(tmp_path, api)
    assert not api.creates


@pytest.mark.parametrize(
    "path,value",
    [
        (("id",), "bad"),
        (("identity", "value"), "wrong"),
        (("sources",), []),
        (("sources", 0, "__typename"), "CollectionLegacySource"),
        (("sources", 0, "targetType"), "VARIANTS"),
        (("sources", 0, "inclusion", "matchType"), "ANY"),
        (("sources", 0, "inclusion", "selections", "nodes"), [{"product": {"id": "1"}}]),
        (("sources", 0, "inclusion", "conditions", 0, "__typename"), "Different"),
        (("sources", 0, "inclusion", "conditions", 0, "relation"), "NOT_TAGGED_WITH"),
        (("sources", 0, "inclusion", "conditions", 0, "matchType"), "ANY"),
        (("sources", 0, "inclusion", "conditions", 0, "values"), ["The First Chapter"]),
        (("sources", 0, "exclusion"), dict(conditions=[{}], selections=dict(nodes=[]))),
        (("sources", 0, "exclusion"), dict(conditions=[], selections=dict(nodes=[{}]))),
        (("resourcePublicationsCount", "count"), 1),
    ],
)
def test_verify_rejects_broader_rules_or_published_creation(path, value):
    row = remote()
    field = row
    for component in path[:-1]:
        field = field[component]
    field[path[-1]] = value
    with pytest.raises(ValueError, match="readback_mismatch"):
        collections.verify_collection(
            row, collections.expansion_collection_spec(candidate()), unpublished=True
        )


@pytest.mark.parametrize("row", [{}, None, remote(id=None)])
def test_verify_rejects_missing_or_invalid_readback(row):
    with pytest.raises(ValueError, match="readback_mismatch"):
        collections.verify_collection(
            row, collections.expansion_collection_spec(candidate()), unpublished=True
        )


def test_explicit_empty_exclusion_is_valid():
    row = remote()
    row["sources"][0]["exclusion"] = dict(conditions=[], selections=dict(nodes=[]))
    assert (
        collections.verify_collection(
            row, collections.expansion_collection_spec(candidate()), unpublished=True
        )
        == row["id"]
    )


@pytest.mark.parametrize("cursor", [None, "repeat"])
def test_inventory_cursors_must_advance(cursor):
    def graphql(query, variables):
        return dict(collections=dict(nodes=[], pageInfo=dict(hasNextPage=True, endCursor=cursor)))

    with pytest.raises(ValueError, match="invalid_expansion_collection_cursor"):
        collections.collection_inventory(graphql)


def test_inventory_reads_all_pages_and_is_bounded():
    cursors = []

    def graphql(query, variables):
        cursors.append(variables["after"])
        return dict(
            collections=dict(
                nodes=[len(cursors)],
                pageInfo=dict(hasNextPage=len(cursors) == 1, endCursor=str(len(cursors))),
            )
        )

    assert collections.collection_inventory(graphql) == [1, 2]
    assert cursors == [None, "1"]

    def endless(query, variables):
        cursor = int(variables["after"] or 0) + 1
        return dict(
            collections=dict(nodes=[], pageInfo=dict(hasNextPage=True, endCursor=str(cursor)))
        )

    with pytest.raises(ValueError, match="page_limit"):
        collections.collection_inventory(endless)


def test_journal_intent_is_committed_before_mutation(tmp_path):
    api = API()
    original = api.graphql

    def observed(query, variables):
        if query == collections.CREATE_COLLECTION:
            with closing(sqlite3.connect(tmp_path / "state" / "collections.sqlite3")) as db:
                assert db.execute("SELECT state,gid FROM collections").fetchall() == [
                    ("pending", None)
                ]
        return original(query, variables)

    api.graphql = observed
    reconcile(tmp_path, api)
