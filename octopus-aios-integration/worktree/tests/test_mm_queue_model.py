"""Tests for the queue model pure helpers."""

from __future__ import annotations

from scripts.aios.collectors.mm_queue_model import (
    assign_buckets,
    extract_touch_events,
    fill_prob,
)


def _snap(ts, bid, ask, mid, bqty=10.0, aqty=10.0):
    return {
        "ts": ts,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "bids": [[str(bid), str(bqty)]],
        "asks": [[str(ask), str(aqty)]],
    }


def test_extract_touch_events_splits_on_price_change():
    snaps = [
        _snap(0.0, 100.0, 101.0, 100.5),
        _snap(1.0, 100.0, 101.0, 100.5),
        _snap(2.0, 99.0, 100.0, 99.5),
        _snap(3.0, 99.0, 100.0, 99.5),
    ]
    evs = extract_touch_events(snaps, "bid")
    assert [e["px"] for e in evs] == [100.0, 99.0]
    assert evs[0]["start_ts"] == 0.0 and evs[0]["end_ts"] == 1.0
    assert evs[0]["size_at_join"] == 10.0


def test_assign_buckets_attaches_and_drops_ambiguous():
    snaps = [
        _snap(0.0, 100.0, 101.0, 100.5),
        _snap(5.0, 100.0, 101.0, 100.5),
        _snap(10.0, 99.0, 100.0, 99.5),
    ]
    events = extract_touch_events(snaps, "bid")
    buckets = [
        {"ts": 5.0, "buy": 1.0, "sell": 2.0},  # [0,5] same bid=100 -> attach
        {"ts": 10.0, "buy": 1.0, "sell": 3.0},  # [5,10] bid changed -> drop
        {"ts": 15.0, "buy": 1.0, "sell": 4.0},  # [10,15] same bid=99 -> attach
    ]
    out = assign_buckets(snaps, events, buckets, "bid")
    cum0 = [v for _, v in out[0]["cum"]]
    cum1 = [v for _, v in out[1]["cum"]]
    assert cum0 == [2.0]  # only first bucket
    assert cum1 == [4.0]  # only third bucket


def test_fill_prob_back_of_queue():
    # events alive >= 5s; size_at_join=10; q=5 -> need cum >= 15
    events = [
        {"start_ts": 0.0, "end_ts": 9.0, "size_at_join": 10.0, "cum": [(4.0, 20.0)]},  # fills
        {"start_ts": 0.0, "end_ts": 9.0, "size_at_join": 10.0, "cum": [(4.0, 5.0), (8.0, 12.0)]},  # no
    ]
    assert fill_prob(events, tau=5.0, q_base=5.0, min_n=2) == 0.5
    assert fill_prob(events, tau=5.0, q_base=50.0, min_n=2) == 0.0
    assert fill_prob([events[0]], tau=10.0, q_base=5.0) is None  # <30 alive
