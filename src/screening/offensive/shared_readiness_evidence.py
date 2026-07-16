"""Exact-date, network-free shared evidence for Daily Action readiness."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pandas as pd

from src.screening.offensive.cache_readiness import DailyActionRefreshResult
from src.screening.offensive.daily_action_readiness import (
    BOARD_RULE_VERSION,
    DAILY_ACTION_REGIMES,
    NORMALIZATION_VERSION,
    ManifestValidationError,
    SharedReadinessEvidence,
)
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION


def _repository_sources(
    *, data_dir: Path, universe_tickers: tuple[str, ...], signal_date: str
) -> tuple[pd.DataFrame, dict[str, str], dict[tuple[str, str], float]]:
    """Copy same-process or persisted repository evidence without API calls."""

    from src.tools import tushare_api

    with tushare_api._stock_basic_cache_lock:
        stock_basic = (
            None
            if tushare_api._stock_basic_cache is None
            else tushare_api._stock_basic_cache.copy(deep=True)
        )
    with tushare_api._sw_industry_cache_lock:
        sw_mapping = (
            {}
            if tushare_api._sw_industry_cache is None
            else dict(tushare_api._sw_industry_cache)
        )

    if stock_basic is None:
        stock_cache_key = tushare_api._make_tushare_query_cache_key(
            "stock_basic",
            exchange="",
            list_status="L",
            fields=(
                "ts_code,symbol,name,area,industry,market,list_date,"
                "list_status,is_hs"
            ),
        )
        stock_basic = tushare_api._get_tushare_cached_df(stock_cache_key)
        if stock_basic is None:
            stock_basic = tushare_api._get_persisted_tushare_cached_df(
                stock_cache_key
            )
    if not isinstance(stock_basic, pd.DataFrame):
        raise ManifestValidationError("repository stock_basic evidence unavailable")

    missing = set(universe_tickers) - {
        str(code).split(".", 1)[0] for code in sw_mapping
    }
    if missing:
        snapshots_dir = data_dir / "snapshots"
        dated_paths: list[tuple[str, Path]] = []
        if snapshots_dir.exists():
            for path in snapshots_dir.glob("candidate_pool_*.json"):
                match = re.search(r"candidate_pool_(\d{8})", path.name)
                if match and match.group(1) <= signal_date:
                    dated_paths.append((match.group(1), path))
        for _snapshot_date, path in sorted(dated_paths, reverse=True):
            if not missing:
                break
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            records: list[object] = []
            if isinstance(raw, list):
                records = raw
            elif isinstance(raw, dict):
                for key in (
                    "candidates",
                    "candidate_pool",
                    "selected_candidates",
                    "shadow_candidates",
                    "recommendations",
                ):
                    value = raw.get(key)
                    if isinstance(value, list):
                        records.extend(value)
            for record in records:
                if not isinstance(record, dict):
                    continue
                ticker = str(
                    record.get("ticker") or record.get("ts_code") or ""
                ).split(".", 1)[0]
                industry = str(
                    record.get("industry_sw") or record.get("industry") or ""
                ).strip()
                if ticker in missing and industry:
                    sw_mapping[ticker] = industry
                    missing.remove(ticker)
    if missing:
        raise ManifestValidationError("repository SW industry evidence unavailable")

    industry_pct = _load_exact_industry_pct(data_dir, signal_date)
    return stock_basic, sw_mapping, industry_pct


def _load_exact_industry_pct(
    data_dir: Path, signal_date: str
) -> dict[tuple[str, str], float]:
    industry_cache = data_dir / "industry_index_cache"
    try:
        codes = json.loads(
            (industry_cache / "_industry_codes.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError("industry code evidence unavailable") from exc
    if not isinstance(codes, dict):
        raise ManifestValidationError("industry code evidence malformed")

    result: dict[tuple[str, str], float] = {}
    for index_code, industry_name in codes.items():
        if type(index_code) is not str or type(industry_name) is not str:
            raise ManifestValidationError("industry code evidence malformed")
        try:
            frame = pd.read_csv(
                industry_cache / f"{index_code}.csv",
                dtype={"trade_date": str},
            )
        except (OSError, UnicodeDecodeError, pd.errors.ParserError):
            continue
        if not {"trade_date", "pct_chg"}.issubset(frame.columns):
            continue
        matching = frame[
            frame["trade_date"].astype(str).str.replace("-", "", regex=False)
            == signal_date
        ]
        if len(matching) != 1:
            continue
        value = matching.iloc[0]["pct_chg"]
        if isinstance(value, bool):
            continue
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(normalized):
            result[(industry_name, signal_date)] = normalized
    return result


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_shared_readiness_evidence_for_auto(
    refresh_result: DailyActionRefreshResult,
    report_payload: dict,
    *,
    data_dir: Path | None = None,
    stock_basic: pd.DataFrame | None = None,
    sw_industry_by_ticker: dict[str, str] | None = None,
    industry_day_pct: dict[tuple[str, str], float] | None = None,
) -> SharedReadinessEvidence:
    """Bind regime, industry, and security evidence to one frozen signal date."""

    if type(refresh_result) is not DailyActionRefreshResult:
        raise ManifestValidationError(
            "shared evidence requires exact DailyActionRefreshResult"
        )
    expected_date = refresh_result.trade_date.strftime("%Y%m%d")
    if report_payload.get("date") != expected_date:
        raise ManifestValidationError("Auto payload date does not match refresh result")
    market_state = report_payload.get("market_state")
    if not isinstance(market_state, dict):
        raise ManifestValidationError("market_state regime evidence is missing")
    regime = market_state.get("regime_gate_level")
    if type(regime) is not str or regime not in DAILY_ACTION_REGIMES:
        raise ManifestValidationError("regime evidence is not canonical")

    if stock_basic is None or sw_industry_by_ticker is None or industry_day_pct is None:
        if data_dir is None:
            raise ManifestValidationError("repository evidence data_dir is required")
        stock_basic, sw_industry_by_ticker, industry_day_pct = _repository_sources(
            data_dir=Path(data_dir),
            universe_tickers=refresh_result.universe_tickers,
            signal_date=expected_date,
        )
    if not isinstance(stock_basic, pd.DataFrame):
        raise ManifestValidationError("stock_basic evidence must be a DataFrame")
    if not {"ts_code", "name", "list_status"}.issubset(stock_basic.columns):
        raise ManifestValidationError("stock_basic evidence schema is incomplete")
    if not isinstance(sw_industry_by_ticker, dict) or not isinstance(
        industry_day_pct, dict
    ):
        raise ManifestValidationError("industry evidence is malformed")

    universe = refresh_result.universe_tickers
    security_by_ticker: dict[str, str] = {}
    for _, row in stock_basic.copy(deep=True).iterrows():
        raw_code = row["ts_code"]
        if type(raw_code) is not str:
            raise ManifestValidationError("stock_basic ticker identity is malformed")
        ticker = raw_code.split(".", 1)[0]
        if ticker not in universe:
            continue
        if ticker in security_by_ticker:
            raise ManifestValidationError("stock_basic ticker identity is duplicated")
        name = row["name"]
        list_status = row["list_status"]
        if type(name) is not str or type(list_status) is not str:
            raise ManifestValidationError("stock_basic security fields are malformed")
        if list_status != "L":
            raise ManifestValidationError("frozen universe contains unlisted security")
        normalized_name = name.strip().upper()
        is_st = normalized_name.startswith(("ST", "*ST", "S*ST", "SST"))
        security_by_ticker[ticker] = "st" if is_st else "listed"
    if set(security_by_ticker) != set(universe):
        raise ManifestValidationError(
            "security evidence must exactly cover frozen universe"
        )

    normalized_sw: dict[str, str] = {}
    for raw_ticker, raw_industry in sw_industry_by_ticker.items():
        if type(raw_ticker) is not str or type(raw_industry) is not str:
            raise ManifestValidationError("SW industry evidence is malformed")
        ticker = raw_ticker.split(".", 1)[0]
        industry = raw_industry.strip()
        if ticker in universe and industry:
            if ticker in normalized_sw and normalized_sw[ticker] != industry:
                raise ManifestValidationError("SW industry identity is ambiguous")
            normalized_sw[ticker] = industry
    if set(normalized_sw) != set(universe):
        raise ManifestValidationError(
            "industry mapping must exactly cover frozen universe"
        )

    pct_by_ticker: dict[str, float] = {}
    for ticker, industry in normalized_sw.items():
        value = industry_day_pct.get((industry, expected_date))
        if isinstance(value, bool) or type(value) not in (int, float):
            raise ManifestValidationError(
                "industry day pct must exactly cover signal date"
            )
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ManifestValidationError("industry day pct must be finite")
        pct_by_ticker[ticker] = normalized

    as_of = refresh_result.trade_date.isoformat()
    regime_row = {"trade_date": as_of, "regime": regime}
    return SharedReadinessEvidence(
        as_of_date=refresh_result.trade_date,
        regime_row=regime_row,
        industry_by_ticker=normalized_sw,
        industry_day_pct=pct_by_ticker,
        security_status_by_ticker=security_by_ticker,
        regime_fingerprint=_fingerprint(
            {"as_of_date": as_of, "regime_row": regime_row}
        ),
        industry_fingerprint=_fingerprint(
            {
                "as_of_date": as_of,
                "industry_by_ticker": normalized_sw,
                "industry_day_pct": pct_by_ticker,
            }
        ),
        security_fingerprint=_fingerprint(
            {
                "as_of_date": as_of,
                "security_status_by_ticker": security_by_ticker,
            }
        ),
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )
