"""광부 투자터미널: KRX 코스피/코스닥 *전체 주식시장* 투자자별 순매수(금액).

공식 KRX 투자자별 거래실적을 pykrx의 KRX 스크래퍼로 조회한다.
- ETFs/ETNs/ELWs 제외 (주식시장 범위)
- 원 단위 순매수; 명확한 날짜가 있는 일별 응답만 인정
- 코스피/코스닥 둘 다 있는 날짜만 기록
- 실데이터가 없으면 기존 검증된 파일을 훼손하지 않음
- 데이터 제공처가 접근 차단/변경되면 실패: 절대 가짜 값으로 대체하지 않음
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from numbers import Integral
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = ROOT / "data" / "kr_market_total_flow.json"
KST = ZoneInfo("Asia/Seoul")
MARKETS = ("KOSPI", "KOSDAQ")
COLUMNS = {
    "foreign_net_krw": "외국인합계",
    "institution_net_krw": "기관합계",
    "individual_net_krw": "개인",
}
MAX_HISTORY = 260


def _int_krw(value):
    """Missing values are not zero. Avoid lossy floating-point money."""
    if value is None or isinstance(value, bool) or pd.isna(value):
        raise ValueError("missing investor net value")
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+|[+-]?\d+", value.strip()):
        return int(value.strip().replace(",", ""))
    raise ValueError(f"non-integer KRW value: {type(value).__name__}")


def parse_dated_market_frame(frame: pd.DataFrame, market: str, through: date):
    """Requires explicitly returned day in the index; refuses aggregated undated frames."""
    if market not in MARKETS:
        raise ValueError("unknown market")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{market}: no dated KRX rows")
    if not all(k in frame.columns for k in COLUMNS.values()):
        raise ValueError(f"{market}: missing KRX investor columns ({list(frame.columns)})")
    if frame.index.name not in ("날짜", "TRD_DD", None):
        raise ValueError(f"{market}: unexpected date index name")

    results = {}
    for idx, row in frame.iterrows():
        # Parse an actual returned date, never stamp the request date onto an undated table.
        if isinstance(idx, pd.Timestamp):
            if idx.tzinfo is not None:
                raise ValueError(f"{market}: timezone-bearing index")
            day = idx.date()
        elif isinstance(idx, (datetime, date)):
            day = idx.date() if isinstance(idx, datetime) else idx
        elif isinstance(idx, str) and re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", idx):
            day = date.fromisoformat(idx.replace("/", "-"))
        else:
            raise ValueError(f"{market}: no explicit, parseable KRX trading date")
        if day > through:
            raise ValueError(f"{market}: future returned day {day}")
        if day.weekday() >= 5:
            raise ValueError(f"{market}: weekend returned day {day}")
        key = day.isoformat()
        if key in results:
            raise ValueError(f"{market}: duplicate day {key}")
        v = {k: _int_krw(row[col]) for k, col in COLUMNS.items()}
        # 0 for a specific investor is permitted; all groups zero suggests no market data.
        if all(vv == 0 for vv in v.values()):
            continue
        results[key] = v
    if not results:
        raise ValueError(f"{market}: no usable trading days")
    return results


def fetch_from_krx(start: date, through: date, fetcher=None):
    """Use KRX daily index via pykrx website wrapper (not an undated period aggregate)."""
    if fetcher is None:
        from pykrx.website.krx.market.wrap import get_market_trading_value_and_volume_on_market_by_date
        fetcher = get_market_trading_value_and_volume_on_market_by_date
    market_rows = {}
    for market in MARKETS:
        df = fetcher(start.strftime("%Y%m%d"), through.strftime("%Y%m%d"), market,
                     False, False, False, "거래대금", "순매수", False)
        market_rows[market] = parse_dated_market_frame(df, market, through)
    return market_rows


def combine(market_rows, previous=None, *, max_age=8, today=None):
    today = today or datetime.now(timezone.utc).astimezone(KST).date()
    if not isinstance(market_rows, dict) or set(market_rows) != set(MARKETS):
        raise ValueError("both KOSPI and KOSDAQ are required")
    # Only dates explicitly provided by BOTH full markets may be merged.
    shared = sorted(set(market_rows["KOSPI"]) & set(market_rows["KOSDAQ"]))
    if not shared:
        raise ValueError("KRX trading dates do not overlap between markets")
    latest = date.fromisoformat(shared[-1])
    if (today - latest).days > max_age:
        raise ValueError(f"stale KRX latest day {latest}, today {today}")
    if latest > today:
        raise ValueError("future latest date")

    by_date = {}
    old_history = previous.get("history", []) if isinstance(previous, dict) else []
    for v in old_history if isinstance(old_history, list) else []:
        if (isinstance(v, dict) and isinstance(v.get("date"), str) and
                isinstance(v.get("KOSPI"), dict) and isinstance(v.get("KOSDAQ"), dict)):
            try:
                date.fromisoformat(v["date"])
                for m in MARKETS:
                    for key in COLUMNS:
                        if not isinstance(v[m][key], int) or isinstance(v[m][key], bool):
                            raise ValueError("not integer")
            except (ValueError, KeyError, TypeError):
                continue
            by_date[v["date"]] = v
    for d in shared:
        if date.fromisoformat(d) > today:
            raise ValueError("future history")
        by_date[d] = {"date": d, **{m: market_rows[m][d] for m in MARKETS}}
    history = [by_date[d] for d in sorted(by_date)[-MAX_HISTORY:]]
    now = datetime.now(timezone.utc).astimezone(KST).isoformat()
    return {
        "status": "verified",
        "source": "KRX investor daily trading value via pykrx (KRX data website)",
        "source_page": "https://data.krx.co.kr/",
        "scope": "KOSPI/KOSDAQ all stocks; ETF/ETN/ELW excluded; amount in KRW",
        "includes_etf_etn_elw": False,
        "collected_at_kst": now,
        "latest_date": shared[-1],
        "observations": len(history),
        "history": history,
        "futures_status": "not_connected",
        "note": "Dated KRX market-level daily investor net trading value. Market totals, NOT TOP200."
    }


def atomic_save(payload, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, dest)


def run(dest=DEFAULT_DEST, *, fetcher=None, today=None):
    today = today or datetime.now(timezone.utc).astimezone(KST).date()
    start = today - timedelta(days=56)
    try:
        old = json.loads(dest.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        old = None
    # Refuse weekend future date and long-stale data. Do not silently substitute previous day.
    data = fetch_from_krx(start, today, fetcher=fetcher)
    current = combine(data, old, today=today)
    atomic_save(current, dest)
    print(f"Market total flows: VERIFIED latest={current['latest_date']}, ")
    print(f"history={current['observations']} (KOSPI and KOSDAQ, ETFs excluded)")
    return current


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_DEST))
    args = parser.parse_args()
    try:
        run(dest=Path(args.output))
    except Exception as exc:
        # Existing verified snapshot is retained. GitHub Actions logs show the exact failure.
        print(f"Market total collection FAILED (old snapshot preserved): {exc}", file=sys.stderr)
        sys.exit(1)
