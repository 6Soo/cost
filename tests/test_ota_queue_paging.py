import json

import pytest

from app.ota_queue_paging import (
    QUEUES,
    PagingError,
    build_queue_index,
    list_queue_page,
)


KEY = b"synthetic-test-signing-key-0123456789"


def row(event_id, *, queue="needs_action", provider="agoda", paid_on="2026-01-02",
        booking_ref="B-1", item="Hotel", merchant="Example", status="HOLD_AMBIGUOUS",
        reason_codes=("HOLD_AMBIGUOUS",), **extra):
    event = {
        "ota_event_id": event_id,
        "provider": provider,
        "booking_ref": booking_ref,
        "event_type": "booking",
        "paid_on": paid_on,
        "item": item,
        "merchant": merchant,
        "amount": 1200,
        "currency": "KRW",
        "status": status,
        "private_sentinel": "DO_NOT_RETURN_9ab3",
    }
    event.update(extra)
    return {"queue": queue, "reason_codes": list(reason_codes), "event": event}


def make_index(rows, generation=4, nonce="snapshot-nonce-A"):
    return build_queue_index(rows, generation=generation,
                             snapshot_nonce=nonce, signing_key=KEY)


def test_pages_keep_all_rows_and_cursor_walk_is_stable():
    rows = [row(f"id-{n:02}") for n in range(44)]
    rows += [row("duplicate"), row("duplicate"), row(None)]
    index = make_index(rows)
    seen = []
    cursor = None
    page_sizes = []
    while True:
        page = list_queue_page(index, limit=20, cursor=cursor)
        page_sizes.append(len(page["items"]))
        seen.extend(item["event"]["ota_event_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert page_sizes == [20, 20, 7]
    assert len(seen) == len(rows)
    assert seen.count("duplicate") == 2
    assert seen.count(None) == 1
    assert len(list_queue_page(index, limit=20)["items"]) == 20


def test_sort_priority_valid_dates_unknown_last_id_and_ordinal_tiebreak():
    rows = [
        row("same", paid_on="2026-02-02"),
        row("same", paid_on="2026-02-02"),
        row("z", paid_on="2026-99-99"),
        row("a", paid_on="2026-01-01", queue="completed", reason_codes=()),
        row("b", paid_on="2026-01-01"),
    ]
    items = list_queue_page(make_index(rows))["items"]
    assert [i["event"]["ota_event_id"] for i in items] == ["b", "same", "same", "z", "a"]
    assert items[-2]["event"]["paid_on"] is None


def test_queue_provider_and_q_filters_are_bounded_to_allowlisted_search_fields():
    rows = [
        row("1", provider="Agoda", booking_ref="ABCD", queue="needs_action"),
        row("2", provider="expedia", booking_ref="other", queue="waiting_source",
            reason_codes=("SOURCE_OR_DATE_PENDING",)),
        row("3", provider="agoda", merchant="Needle merchant", item="unrelated"),
    ]
    index = make_index(rows)
    assert list_queue_page(index, queue="waiting_source")["total_count"] == 1
    assert list_queue_page(index, provider="AGODA")["total_count"] == 2
    assert list_queue_page(index, q="abcd")["total_count"] == 1
    assert list_queue_page(index, q="needle")["total_count"] == 1
    assert list_queue_page(index, q="DO_NOT_RETURN")["total_count"] == 0
    assert list_queue_page(index, queue="historical")["items"] == []


def test_output_is_minimal_json_safe_and_input_is_not_mutated():
    source = row("event-1", booking_ref="secret booking",
                 private_sentinel="DO_NOT_RETURN_9ab3")
    before = json.dumps(source, sort_keys=True)
    index = make_index([source])
    output = list_queue_page(index)
    assert json.dumps(output)
    assert "DO_NOT_RETURN_9ab3" not in json.dumps(output)
    # The event id and booking reference are explicitly public allowlist fields;
    # private sentinels in unrelated metadata must never escape.
    assert "private_sentinel" not in output["items"][0]["event"]
    assert "secret booking" in output["items"][0]["event"]["booking_ref"]
    assert json.dumps(source, sort_keys=True) == before


def test_index_discards_arbitrary_object_values_without_calling_repr_or_str():
    class HostileValue:
        def __repr__(self):
            raise AssertionError("repr must not be called")

        def __str__(self):
            raise AssertionError("str must not be called")

    source = row("safe-id", amount=HostileValue(), merchant=HostileValue(),
                 private_sentinel=HostileValue())
    page = list_queue_page(make_index([source]))
    assert page["items"][0]["event"]["amount"] is None
    assert "merchant" not in page["items"][0]["event"]
    assert "private_sentinel" not in json.dumps(page)


def test_cursor_binds_generation_nonce_filters_and_limit_with_safe_errors():
    rows = [row(str(i)) for i in range(25)]
    first = list_queue_page(make_index(rows), limit=10)
    cursor = first["next_cursor"]
    assert cursor
    assert "DO_NOT_RETURN_9ab3" not in cursor
    index = make_index(rows)
    assert list_queue_page(index, limit=10, cursor=cursor)["total_count"] == 25
    cases = [
        (make_index(rows, generation=5), {"limit": 10}),
        (make_index(rows, nonce="snapshot-nonce-B"), {"limit": 10}),
        (index, {"limit": 10, "provider": "expedia"}),
        (index, {"limit": 11}),
    ]
    for changed_index, args in cases:
        with pytest.raises(PagingError) as caught:
            list_queue_page(changed_index, cursor=cursor, **args)
        assert (caught.value.code, caught.value.status_code) == ("SNAPSHOT_CHANGED", 409)
    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    for bad in (tampered, "not-a-token", "x" * 1025, "eyJ4IjoxfQ.AA"):
        with pytest.raises(PagingError) as caught:
            list_queue_page(index, limit=10, cursor=bad)
        assert (caught.value.code, caught.value.status_code) == ("BAD_CURSOR", 400)
        assert bad not in str(caught.value)


@pytest.mark.parametrize("kwargs", [
    {"limit": True}, {"limit": 0}, {"limit": 101}, {"limit": "20"},
    {"queue": "unknown"}, {"provider": "bad provider"}, {"provider": "x" * 65},
    {"q": ""}, {"q": "x" * 121}, {"q": object()},
])
def test_invalid_filters_and_limits_fail_safely(kwargs):
    with pytest.raises(PagingError) as caught:
        list_queue_page(make_index([row("x")]), **kwargs)
    assert caught.value.status_code == 400
    assert "object at" not in str(caught.value)


def test_input_schema_generation_and_key_are_strict():
    good = row("x")
    invalid_rows = [
        [dict(good, queue="other")],
        [dict(good, reason_codes=["raw customer reason"])],
        [dict(good, event=[])],
    ]
    for rows in invalid_rows:
        with pytest.raises(PagingError):
            make_index(rows)
    for generation, nonce, key in ((True, "n", KEY), (1, "n", b"short"),
                                   (1, "", KEY), (1, "n", bytearray(KEY))):
        with pytest.raises(PagingError):
            build_queue_index([good], generation=generation,
                              snapshot_nonce=nonce, signing_key=key)


def test_serialized_payload_tracks_page_size_not_total_index_size():
    small = make_index([row(f"i{n:06}") for n in range(10_000)])
    large = make_index([row(f"i{n:06}") for n in range(100_000)])
    small_page = list_queue_page(small, limit=20)
    large_page = list_queue_page(large, limit=20)
    assert len(small_page["items"]) == len(large_page["items"]) == 20
    assert json.dumps(small_page["items"]) == json.dumps(large_page["items"])
    assert abs(len(json.dumps(small_page)) - len(json.dumps(large_page))) < 32
    assert large_page["total_count"] == 100_000


def test_missing_or_invalid_providers_never_duplicate_unfiltered_rows():
    rows = [row('a', provider=None), row('b', provider='bad provider'), row('c')]
    page = list_queue_page(make_index(rows))
    assert page['total_count'] == 3
    assert [item['event']['ota_event_id'] for item in page['items']] == ['a', 'b', 'c']
    assert list_queue_page(make_index(rows), queue='needs_action')['total_count'] == 3


def test_amount_text_is_numeric_only_and_preserves_original_format():
    page = list_queue_page(make_index([row('a', amount='PRIVATE_SENTINEL'), row('b', amount='001.20')]))
    assert page['items'][0]['event']['amount'] is None
    assert page['items'][1]['event']['amount'] == '001.20'
    assert 'PRIVATE_SENTINEL' not in json.dumps(page)


def test_queue_enum_contains_only_projection_queues():
    assert QUEUES == ("needs_action", "waiting_source", "evidence_missing",
                      "auto_recheck", "completed", "historical")
