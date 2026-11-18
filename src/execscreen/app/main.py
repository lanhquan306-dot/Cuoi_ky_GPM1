"""ExecScreen browser application served by FastAPI."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from execscreen.ai.nl_to_config import apply_overrides, rule_based_parse
from execscreen.analytics.forward_test import (
    PicksAlreadyFrozen,
    evaluate_run,
    freeze_picks,
    load_picks,
    summarize_runs,
)
from execscreen.analytics.pipeline import calibrate_thresholds, run_screen
from execscreen.analytics.scoring import GATE_LABELS, explain_row
from execscreen.app import charts
from execscreen.config import ROOT, db_path, load_config, load_dotenv_if_present
from execscreen.data.mock import business_days, generate_mock_history
from execscreen.data.storage import Store
from execscreen.finance.execution import ASK_P, ASK_V, BID_P, BID_V, cost_table, walk_book
from execscreen.finance.fees import FeeSchedule
from execscreen.timeutil import TZ_NAME, now_vn

templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
app = FastAPI(title="ExecScreen", docs_url=None, redoc_url=None, openapi_url=None)
load_dotenv_if_present()

DISCLAIMER = (
    "Công cụ phân tích học thuật phục vụ môn học, không phải khuyến nghị đầu tư. "
    "Sản phẩm không đặt, sửa hay hủy lệnh thật."
)
TAB_LINKS = [
    ("ranking", "Xếp hạng"),
    ("details", "Chi tiết mã"),
    ("forward-test", "Forward-test"),
    ("quality", "Chất lượng dữ liệu"),
    ("method", "Phương pháp & giới hạn"),
]


def _db_signature(path: Path) -> float:
    return max(
        [item.stat().st_mtime for item in (path, Path(str(path) + "-wal")) if item.exists()]
        or [0.0]
    )


def load_snaps(db: str, signature: float) -> pd.DataFrame:
    del signature
    store = Store(db)
    try:
        return store.read_snapshots()
    finally:
        store.close()


def load_universe() -> pd.DataFrame:
    return pd.read_csv(ROOT / "config" / "universe_sample.csv")


def make_demo_db(path: Path, n_days: int = 10, interval_s: int = 30) -> None:
    universe = load_universe()
    days = business_days(date.today(), n_days)
    frame = generate_mock_history(
        universe["symbol"].tolist(),
        dict(zip(universe["symbol"], universe["tier"])),
        days,
        interval_s,
    )
    store = Store(path)
    try:
        store.insert_frame(frame.assign(ts=frame["ts"]))
    finally:
        store.close()


def _json_figure(figure) -> dict[str, Any]:
    return json.loads(figure.to_json())


def _display(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(value, (float, np.floating)):
        return f"{value:,.2f}"
    return str(value)


def _table(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "columns": [str(column) for column in frame.columns],
        "rows": [[_display(value) for value in row] for row in frame.itertuples(index=False, name=None)],
    }


def _base_context(request: Request, **values: Any) -> dict[str, Any]:
    return {
        "request": request,
        "title": "ExecScreen - Bộ lọc cổ phiếu theo quy mô vốn",
        "disclaimer": DISCLAIMER,
        "tabs": TAB_LINKS,
        "message": None,
        "error": None,
        **values,
    }


def _render(request: Request, context: dict[str, Any]) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html", context=context)


def _form_float(form, key: str, default: float, minimum: float, maximum: float) -> float:
    raw = form.get(key)
    if raw in (None, ""):
        return default
    value = float(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} phải nằm trong khoảng {minimum:g} đến {maximum:g}.")
    return value


def _form_config(form, base_cfg: dict) -> tuple[dict, float, str | None, str | None]:
    cfg = json.loads(json.dumps(base_cfg))
    capital_m = _form_float(
        form,
        "capital_m",
        float(cfg["execution"]["capital_vnd"]) / 1e6,
        10,
        100_000,
    )
    capital = capital_m * 1e6
    message = None
    preview = None
    nl = str(form.get("nl", "")).strip()
    if nl:
        try:
            overrides = rule_based_parse(nl)
            preview = json.dumps(overrides.model_dump(exclude_defaults=True), ensure_ascii=False, indent=2)
            if form.get("apply_nl") == "on":
                cfg, override_capital = apply_overrides(base_cfg, overrides)
                capital = override_capital or capital
                message = "Đã áp dụng yêu cầu nhanh theo bộ quy tắc."
            else:
                message = "Đã phân tích yêu cầu nhanh; đánh dấu ô áp dụng để sử dụng."
        except (ValueError, TypeError) as exc:
            message = f"Không hiểu yêu cầu nhanh: {exc}"

    for name, spec in cfg["factors"].items():
        weight = _form_float(form, f"weight__{name}", float(spec["weight"]) if spec.get("enabled") else 0, 0, 3)
        spec["weight"] = weight
        spec["enabled"] = weight > 0
    cfg["scoring"]["cost_penalty_lambda"] = _form_float(
        form,
        "cost_penalty_lambda",
        float(cfg["scoring"]["cost_penalty_lambda"]),
        0,
        2,
    )
    return cfg, capital, message, preview


def _empty_page(request: Request, message: str | None = None) -> HTMLResponse:
    return _render(
        request,
        _base_context(
            request,
            empty=True,
            message=message,
            db_path=str(db_path()),
        ),
    )


@app.get("/", response_class=HTMLResponse)
@app.post("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    form = await request.form() if request.method == "POST" else {}
    action = str(form.get("action", ""))
    db = db_path()
    message = None
    if action == "generate_demo":
        make_demo_db(db)
        message = "Đã tạo dữ liệu mô phỏng. Dữ liệu mock chỉ dùng để thử giao diện."

    snaps = load_snaps(str(db), _db_signature(db)) if db.exists() else pd.DataFrame()
    if snaps.empty:
        return _empty_page(request, message)

    base_cfg = load_config()
    try:
        cfg, capital, config_message, nl_preview = _form_config(form, base_cfg)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Tham số không hợp lệ: {exc}") from exc
    message = config_message or message
    sources = sorted(snaps["source"].dropna().unique().tolist())
    dates = sorted(snaps["trade_date"].dropna().astype(str).unique().tolist())
    selected_date = str(form.get("date", dates[-1]))
    if selected_date not in dates:
        selected_date = dates[-1]

    day_frame = snaps[snaps["trade_date"].astype(str) == selected_date]
    last_ts = day_frame["ts"].max()
    default_time = last_ts.time() if selected_date == dates[-1] else time(10, 0)
    default_time = min(default_time, time(14, 30))
    raw_time = str(form.get("time", default_time.strftime("%H:%M")))
    try:
        selected_time = time.fromisoformat(raw_time)
    except ValueError:
        selected_time = default_time
        message = "Thời điểm không hợp lệ; đã dùng thời điểm mặc định."
    as_of = pd.Timestamp(datetime.combine(date.fromisoformat(selected_date), selected_time), tz=TZ_NAME)

    k_cal = int(cfg["forward_test"]["calibration_sessions"])
    calibration_dates = dates[:k_cal]
    use_frozen = selected_date not in calibration_dates and len(dates) > k_cal
    frozen = (
        calibrate_thresholds(snaps, cfg, calibration_dates, capital) or None
        if use_frozen
        else None
    )
    ranked, thresholds = run_screen(snaps, as_of, cfg, capital, frozen)
    if ranked.empty:
        return _render(
            request,
            _base_context(
                request,
                empty=False,
                no_ranked=True,
                message=message,
                dates=dates,
                selected_date=selected_date,
                selected_time=selected_time.strftime("%H:%M"),
                sources=sources,
                capital_m=capital / 1e6,
                factors=cfg["factors"],
                cost_penalty_lambda=cfg["scoring"]["cost_penalty_lambda"],
                timezone=TZ_NAME,
                nl=str(form.get("nl", "")),
                nl_preview=nl_preview,
                apply_nl=form.get("apply_nl") == "on",
            ),
        )

    eligible = ranked[ranked["eligible"]]
    status_store = Store(db)
    try:
        status = status_store.get_status()
        quality = status_store.read_quality()
        all_picks = load_picks(status_store.conn)
    finally:
        status_store.close()
    collector_status = status

    if action == "freeze":
        store = Store(db)
        try:
            run_id = freeze_picks(store.conn, ranked, as_of, cfg, capital)
            message = f"Đã chốt {run_id}. Danh sách này bất biến."
            all_picks = load_picks(store.conn)
        except PicksAlreadyFrozen as exc:
            message = str(exc)
        finally:
            store.close()

    show_out = form.get("show_out") == "on"
    selected_symbols = form.getlist("symbols") if hasattr(form, "getlist") else []
    selected_symbols = [symbol for symbol in selected_symbols if symbol in ranked.index]
    table_frame = ranked if show_out else eligible
    if selected_symbols:
        table_frame = table_frame[table_frame.index.isin(selected_symbols)]
    ranking_table = pd.DataFrame(
        {
            "Hạng": table_frame["rank"],
            "Mã": table_frame.index,
            "Điểm 0-100": table_frame["score_0_100"],
            "Điểm ròng": table_frame["net_score"],
            "Điểm yếu tố": table_frame["comp_score"],
            "Chi phí P50 (bps)": table_frame["cost_p50_bps"],
            "Chi phí P90 (bps)": table_frame["cost_p90_bps"],
            "Độ phủ sổ lệnh (x vốn)": table_frame["coverage_med"],
            "% snapshot vượt độ sâu": table_frame["beyond_share"] * 100,
            "Vốn/GTGD TB (%)": table_frame["participation"] * 100,
            "RVOL": table_frame["rvol_tod"],
            "OBI": table_frame["obi3"],
            "Động lượng (%)": table_frame["mom_ref"] * 100,
            "Lý do loại": table_frame["gate_reasons"].map(
                lambda reasons: "; ".join(
                    GATE_LABELS.get(code, code) for code in reasons.split(",") if code
                )
            ),
        }
    ).round(2)

    last_prices = ranked["last"]
    reference = snaps[
        (snaps["trade_date"].astype(str) == selected_date) & (snaps["ts"] <= as_of)
    ].groupby("symbol")["ref"].last()
    changes = last_prices / reference.reindex(last_prices.index) - 1
    selected_symbol = str(form.get("symbol", ""))
    detail_pool = list(eligible.index) or list(ranked.index)
    if selected_symbol not in detail_pool:
        selected_symbol = str(detail_pool[0])
    row = ranked.loc[selected_symbol]
    detail = {
        "symbol": selected_symbol,
        "explanation": explain_row(row, cfg),
        "eligible": bool(row["eligible"]),
        "charts": {},
        "warning": None,
        "metrics": [],
    }
    if detail["eligible"]:
        detail["charts"]["contribution"] = _json_figure(charts.contrib_bar(row))
    today = snaps[
        (snaps["trade_date"].astype(str) == selected_date)
        & (snaps["symbol"] == selected_symbol)
        & (snaps["ts"] <= as_of)
    ]
    continuous = today[today["phase"] == "CONTINUOUS"]
    side = str(form.get("side", "Mua"))
    if side not in ("Mua", "Bán"):
        side = "Mua"
    if continuous.empty:
        detail["warning"] = "Mã này chưa có snapshot trong phiên liên tục tại thời điểm đã chọn."
    else:
        snapshot = continuous.iloc[-1]
        price_columns, volume_columns, direction = (
            (ASK_P, ASK_V, "buy") if side == "Mua" else (BID_P, BID_V, "sell")
        )
        levels = [(snapshot[price], snapshot[volume]) for price, volume in zip(price_columns, volume_columns)]
        mid = (snapshot["bid1_p"] + snapshot["ask1_p"]) / 2
        result = walk_book(levels, direction, capital, mid, int(cfg["execution"]["lot_size"]))
        detail["metrics"] = [
            ("Trượt giá so với giá giữa (bps)", _display(result.slippage_bps)),
            ("VWAP khớp", _display(result.vwap)),
            ("Trạng thái", "Vượt độ sâu 3 mức" if result.beyond_depth else result.status),
        ]
        taken = []
        remaining = result.filled_shares
        for _, volume in levels:
            taken_volume = min(remaining, volume if np.isfinite(volume) else 0)
            taken.append(taken_volume)
            remaining -= taken_volume
        detail["charts"]["depth"] = _json_figure(
            charts.depth_chart(
                [price for price, _ in levels],
                [volume for _, volume in levels],
                taken,
                f"Lệnh {side.lower()} {capital / 1e6:,.0f} triệu 'ăn' sổ lệnh lúc "
                f"{snapshot['ts'].strftime('%H:%M:%S')}",
            )
        )
        costs = cost_table(
            continuous,
            capital,
            int(cfg["execution"]["lot_size"]),
            FeeSchedule.from_config(cfg),
        )
        detail["charts"]["cost"] = _json_figure(
            charts.cost_timeseries(
                continuous["ts"],
                costs["rt_cost_bps"],
                row.get("cost_p50_bps"),
                row.get("cost_p90_bps"),
            )
        )

    forward_results = []
    if not all_picks.empty:
        for run_id, run_picks in all_picks.groupby("run_id"):
            result = evaluate_run(
                run_picks,
                snaps,
                cfg,
                horizon=int(cfg["forward_test"]["horizons_sessions"][0]),
            )
            item = {"run_id": run_id, **result}
            if result.get("status") == "OK":
                item["chart"] = _json_figure(charts.forward_bar(result["trades"]))
            forward_results.append(item)
    summary = summarize_runs(forward_results, cfg)

    coverage = (
        snaps.groupby("trade_date")
        .agg(rows=("symbol", "size"), symbols=("symbol", "nunique"), first=("ts", "min"), last=("ts", "max"))
        .reset_index()
    )
    flag_counts = (
        snaps["q_flags"].fillna("").str.get_dummies(sep=",").sum().to_dict()
        if len(snaps)
        else {}
    )
    age_seconds = (now_vn() - last_ts).total_seconds()
    connection = collector_status.get("connected")
    context = _base_context(
        request,
        empty=False,
        no_ranked=False,
        message=message,
        error=None,
        title="ExecScreen - Bộ lọc cổ phiếu theo quy mô vốn",
        subtitle=(
            "Xếp hạng cổ phiếu theo tín hiệu giá, khối lượng và sổ lệnh sau khi trừ chi phí thực thi "
            "ở đúng quy mô vốn."
        ),
        dates=dates,
        selected_date=selected_date,
        selected_time=selected_time.strftime("%H:%M"),
        sources=sources,
        is_mock="mock" in sources,
        capital_m=capital / 1e6,
        factors=cfg["factors"],
        cost_penalty_lambda=cfg["scoring"]["cost_penalty_lambda"],
        timezone=TZ_NAME,
        nl=str(form.get("nl", "")),
        nl_preview=nl_preview,
        apply_nl=form.get("apply_nl") == "on",
        selected_symbols=selected_symbols,
        show_out=show_out,
        ranked_symbols=list(ranked.index),
        ranking_table=_table(ranking_table.reset_index(drop=True)),
        ranking_chart=_json_figure(charts.scatter_score_cost(ranked)),
        eligible_count=len(eligible),
        ranked_count=len(ranked),
        median_cost=_display(eligible["cost_p50_bps"].median()) if len(eligible) else "-",
        beyond_count=int(ranked["gate_reasons"].str.contains("BEYOND_DEPTH").sum()),
        market_breadth=f"{int((changes > 0).sum())} / {int((changes < 0).sum())}",
        threshold=_display(thresholds.get("max_cost_p90_bps")),
        calibration_text=(
            f"cố định từ {k_cal} phiên hiệu chỉnh" if use_frozen else "tính từ lát cắt hiện tại"
        ),
        updated_at=last_ts.strftime("%d/%m %H:%M:%S"),
        age_text=f"{age_seconds / 3600:.1f} giờ" if age_seconds > 3600 else f"{age_seconds:.0f} giây",
        connection_text=(
            "đang nhận tin" if connection == "true" else ("đã dừng" if connection == "false" else "chưa rõ")
        ),
        detail=detail,
        detail_pool=detail_pool,
        selected_side=side,
        forward_results=forward_results,
        summary=summary,
        coverage=_table(coverage),
        quality=_table(quality),
        sources_text=", ".join(sources),
        flag_counts=flag_counts,
        collector_status=collector_status,
        calibration_dates=", ".join(calibration_dates),
        max_participation=cfg["gates"]["max_participation"],
        lookback_minutes=cfg["execution"]["lookback_minutes"],
        cost_penalty=cfg["scoring"]["cost_penalty_lambda"],
        db_path=str(db),
    )
    return _render(request, context)
