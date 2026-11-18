import asyncio
import json
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from execscreen.ai.nl_to_config import (apply_overrides, llm_parse, rule_based_parse, validate_overrides)
from execscreen.data.collector import FrameSource, Sampler, run_collector
from execscreen.data.quality import QualityChecker
from execscreen.neo_api.auth import MissingCredentials, TokenProvider, mask
from execscreen.neo_api.field_map import FieldMapper, ParseError, StateMerger, dig, parse_ts
from execscreen.neo_api.models import Snapshot
from execscreen.neo_api.ratelimit import TokenBucket
from execscreen.neo_api.stream import NeoStreamClient, backoff_delays
from execscreen.timeutil import TZ, SessionCalendar


def T(h, m, s=0, day=17):
    return datetime(2026, 11, day, h, m, s, tzinfo=TZ)


def snap(sym="AAA", ts=None, **v):
    base = dict(ref=50_000, ceiling=53_500, floor=46_500, last=50_000, bid1_p=49_900, bid1_v=1000,
                ask1_p=50_000, ask1_v=1000, cum_volume=1000, cum_value=5e7)
    base.update(v)
    return Snapshot(sym, ts or T(10, 0), "test", None, base)


@pytest.fixture()
def qc(cfg):
    return QualityChecker(SessionCalendar.from_config(cfg), check_future=False)


# ---------- thời gian & phiên ----------
def test_session_phases(cfg):
    cal = SessionCalendar.from_config(cfg)
    got = {(h, m): cal.phase(T(h, m)) for h, m in [(8, 0), (9, 5), (9, 15), (11, 29), (11, 30), (12, 0),
                                                    (13, 0), (14, 29), (14, 35), (15, 0)]}
    assert got == {(8, 0): "PRE", (9, 5): "ATO", (9, 15): "CONTINUOUS", (11, 29): "CONTINUOUS",
                   (11, 30): "BREAK", (12, 0): "BREAK", (13, 0): "CONTINUOUS", (14, 29): "CONTINUOUS",
                   (14, 35): "ATC", (15, 0): "CLOSED"}
    assert cal.effective_sod(12 * 3600) == 11 * 3600 + 1800


def test_timezone_is_vietnam():
    assert T(10, 0).utcoffset().total_seconds() == 7 * 3600
    assert parse_ts(1_800_000_000, "epoch_s").utcoffset().total_seconds() == 7 * 3600


# ---------- chất lượng dữ liệu ----------
def test_quality_drops_and_flags(qc):
    assert qc.check(snap(ts=T(10, 0)))[0]
    assert qc.check(snap(ts=T(10, 0))) == (False, ["DUPLICATE"])
    assert qc.check(snap(ts=T(9, 59))) == (False, ["OUT_OF_ORDER"])
    assert qc.check(snap(ts=T(10, 1), cum_volume=500)) == (False, ["CUM_DECREASE"])
    assert qc.check(snap("BBB", T(10, 1), bid1_p=50_100, ask1_p=50_000)) == (False, ["CROSSED_BOOK"])
    assert qc.check(snap("CCC", T(10, 1), last=60_000)) == (False, ["OUT_OF_BAND"])
    assert qc.check(snap("DDD", T(10, 1), bid1_v=-5)) == (False, ["NEG_VALUE"])
    assert qc.check(Snapshot("", T(10, 1), "t", None, {})) == (False, ["NO_SYMBOL"])
    ok, flags = qc.check(snap("EEE", T(10, 2), ask1_p=None, ask1_v=None))
    assert ok and "NO_QUOTE" in flags                       # khóa trần: hợp lệ, chỉ gắn cờ
    ok, flags = qc.check(snap("FFF", T(9, 5)))
    assert ok and "NONCONT" in flags
    late = snap("GGG", T(10, 3))
    late.ingest_ts = T(10, 3, 30)
    assert "LATE" in qc.check(late)[1]
    c = qc.drain_counts()
    assert c["DUPLICATE"] == 1 and c["OUT_OF_ORDER"] == 1 and c["CROSSED_BOOK"] == 1 and c["ACCEPTED"] == 4


def test_quality_rejects_future_timestamps(cfg):
    q = QualityChecker(SessionCalendar.from_config(cfg), check_future=True)
    assert q.check(snap(ts=datetime(2099, 1, 1, 10, 0, tzinfo=TZ))) == (False, ["FUTURE_TS"])


# ---------- lấy mẫu & thu thập ----------
def test_sampler_keeps_last_snapshot_of_each_bucket():
    s = Sampler(60)
    assert s.offer(snap(ts=T(10, 0, 5)), "CONTINUOUS", "") is None
    assert s.offer(snap(ts=T(10, 0, 50)), "CONTINUOUS", "") is None
    out = s.offer(snap(ts=T(10, 1, 2)), "CONTINUOUS", "")
    assert out is not None and out[0].ts == T(10, 0, 50)
    assert len(s.flush()) == 1


def test_collector_end_to_end_stores_deduplicated_rows(tmp_path, mock_df, cfg):
    from execscreen.data.storage import Store
    st = Store(tmp_path / "c.db")
    df = mock_df[mock_df["trade_date"] == mock_df["trade_date"].iloc[0]].head(3000)
    df = pd.concat([df, df.head(50)])                        # chèn 50 bản ghi trùng
    chk = QualityChecker(SessionCalendar.from_config(cfg), check_future=False)
    out = asyncio.run(run_collector(FrameSource(df), st, chk, interval_s=60))
    assert out["received"] == len(df) and 0 < out["stored"] <= len(df)
    q = st.read_quality()
    assert q.loc[q["issue"] == "DUPLICATE", "n"].sum() >= 1 or q.loc[q["issue"] == "OUT_OF_ORDER", "n"].sum() >= 1
    assert st.get_status()["connected"] == "false"
    st.close()


def test_collector_records_failure_status(tmp_path, cfg):
    from execscreen.data.storage import Store
    st = Store(tmp_path / "f.db")

    async def broken():
        yield snap()
        raise ConnectionError("mất kết nối")

    with pytest.raises(ConnectionError):
        asyncio.run(run_collector(broken(), st, QualityChecker(SessionCalendar.from_config(cfg), check_future=False)))
    assert "mất kết nối" in st.get_status()["last_error"]
    st.close()


# ---------- lưu trữ ----------
def test_storage_roundtrip_and_dedupe(store, mock_df):
    part = mock_df.head(500)
    n1 = store.insert_frame(part)
    n2 = store.insert_frame(part)                              # ghi lại: bị bỏ qua nhờ UNIQUE
    assert n1 == 500 and store.count() == 500 and n2 == 0
    back = store.read_snapshots()
    assert str(back["ts"].dt.tz) == "Asia/Ho_Chi_Minh"
    assert set(back.columns) >= {"bid1_p", "ask3_v", "fbuy_val", "room_cur", "q_flags"}
    np.testing.assert_allclose(back.sort_values(["ts", "symbol"])["last"].to_numpy(),
                               part.sort_values(["ts", "symbol"])["last"].to_numpy())
    assert store.sources() == ["mock"]


# ---------- ánh xạ trường NEO / gộp tin từng phần ----------
MAP = {"symbol": "s", "ts": "t", "ts_format": "epoch_ms", "price_scale": 1000, "last": "px.last",
       "bid1_p": "book.b.0.p", "bid1_v": "book.b.0.v", "ask1_p": "book.a.0.p", "ask1_v": "book.a.0.v",
       "room_cur": "room", "cum_volume": "TODO"}


def test_field_mapper_scales_and_ignores_todo():
    m = FieldMapper(MAP)
    sym, ts, vals = m.parse({"s": "acb", "t": 1_700_000_000_000, "px": {"last": 25.5},
                             "book": {"b": [{"p": 25.4, "v": 100}], "a": [{"p": 25.6, "v": 200}]}, "room": 1e6})
    assert sym == "ACB" and vals["last"] == pytest.approx(25_500) and vals["bid1_p"] == pytest.approx(25_400)
    assert vals["bid1_v"] == 100 and "cum_volume" not in vals and ts.utcoffset().total_seconds() == 7 * 3600


def test_field_mapper_errors():
    with pytest.raises(ParseError):
        FieldMapper({"symbol": "TODO"}).parse({})
    with pytest.raises(ParseError):
        FieldMapper(MAP).parse({"t": 1})
    with pytest.raises(ParseError):
        FieldMapper(MAP).parse({"s": "ACB", "px": {"last": "abc"}})
    assert dig({"a": [1, {"b": 2}]}, "a.1.b") == 2 and dig({"a": 1}, "a.b.c") is None


def test_state_merger_combines_partial_messages():
    mg = StateMerger()
    assert mg.update("ACB", None, {"room_cur": 5.0}) is None                      # chưa đủ để lập snapshot
    s = mg.update("ACB", T(10, 0), {"last": 25_000.0})
    assert s.get("last") == 25_000 and s.get("room_cur") == 5.0
    s2 = mg.update("ACB", T(10, 1), {"bid1_p": 24_900.0})
    assert s2.get("last") == 25_000 and s2.get("bid1_p") == 24_900


def test_stream_client_survives_bad_messages():
    c = NeoStreamClient("wss://x", TokenProvider(), FieldMapper(MAP), ["ACB"],
                        {"subscribe_template": "{}", "auth_header": "A", "auth_scheme": "B"})
    assert c._handle("không phải json") is None
    assert c._handle(json.dumps({"x": 1})) is None
    assert c.parse_errors == 2
    ok = c._handle(json.dumps({"s": "acb", "t": 1_700_000_000_000, "px": {"last": 25.5}}))
    assert ok is not None and ok.symbol == "ACB"
    d = backoff_delays(1, 8)
    seq = [next(d) for _ in range(6)]
    assert max(seq) <= 8 * 1.2 and seq[3] > seq[0]


# ---------- giới hạn tần suất & xác thực ----------
def test_token_bucket_never_exceeds_rate():
    clock = {"t": 0.0}
    slept = []

    def sleep(s):
        slept.append(s)
        clock["t"] += s

    tb = TokenBucket(5, clock=lambda: clock["t"], sleep=sleep)
    for _ in range(5):
        assert tb.acquire() == 0                              # xả hết 5 token đầu: không chờ
    waited = sum(tb.acquire() for _ in range(10))             # 10 yêu cầu tiếp theo phải chờ ~2 giây
    assert waited == pytest.approx(2.0, abs=1e-6)
    assert clock["t"] == pytest.approx(2.0, abs=1e-6)


def test_auth(monkeypatch):
    import base64
    monkeypatch.delenv("NEO_ACCESS_TOKEN", raising=False)
    with pytest.raises(MissingCredentials):
        TokenProvider().get()
    body = base64.urlsafe_b64encode(json.dumps({"exp": 2_000_000_000}).encode()).decode().rstrip("=")
    assert TokenProvider.expiry_of(f"h.{body}.s") == 2_000_000_000
    assert TokenProvider.expiry_of("không-phải-jwt") is None
    monkeypatch.setenv("NEO_ACCESS_TOKEN", "abcdefghij")
    assert TokenProvider().get() == "abcdefghij"
    assert "abcdefghij" not in mask("abcdefghij") and mask("") == "***"


# ---------- AI tùy chọn: kiểm tra đầu ra ----------
def test_nl_validation_rejects_bad_output():
    for bad in ('{"weights": {"hack": 1}}', '{"top_n": 500}', '{"capital_vnd": -5}', '{"lenh": "mua VNM"}',
                "không phải json", "[1,2]", '{"weights": {"obi3": 99}}'):
        with pytest.raises(ValueError):
            validate_overrides(bad)
    ov = validate_overrides('{"capital_vnd": 3e8, "top_n": 8, "weights": {"obi3": 2}}')
    assert ov.top_n == 8


def test_rule_based_and_llm_parse_and_apply(cfg):
    ov = rule_based_parse("vốn 300 triệu, top 8, ưu tiên khối lượng và sổ lệnh")
    assert ov.capital_vnd == 3e8 and ov.top_n == 8 and ov.weights == {"rvol_tod": 2.0, "obi3": 2.0}
    assert rule_based_parse("vốn 1,5 tỷ").capital_vnd == 1.5e9
    fenced = llm_parse("x", lambda prompt: '```json\n{"top_n": 3}\n```')
    assert fenced.top_n == 3
    with pytest.raises(ValueError):
        llm_parse("x", lambda prompt: '{"mua": "VNM"}')       # mô hình cố đưa ra nội dung ngoài phạm vi
    c2, cap = apply_overrides(cfg, ov)
    assert c2["factors"]["obi3"]["weight"] == 2.0 and cap == 3e8
    assert cfg["factors"]["obi3"]["weight"] == 1.0           # cấu hình gốc không bị sửa
