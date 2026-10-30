"""MINER terminal: KOSPI/KOSDAQ all-universe MA20/50/200 breadth.

Data: dated Hugging Face baseline (through 2026-09-17) + overlapping public
30-trading-day daily quote archive from aikstockdata.com. Read-only computation.
The snapshot is NOT regularly updated; fail closed if the archive no longer
bridges the snapshot. Never silently compute stale or partial market breadth.

Personal, non-commercial research only. Unadjusted public-sector closing prices.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
import re

import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go

AIK = "https://aikstockdata.com/data/public"
HF_PARQUET = "https://huggingface.co/datasets/aikstockdata/korea-equity-daily/resolve/main/daily_prices.parquet"
KST = ZoneInfo("Asia/Seoul")
HEADERS = {"User-Agent": "MinerTerminal/1.0 (personal noncommercial research)",
           "Accept": "application/json, text/csv, application/octet-stream"}
MARKETS = ("KOSPI", "KOSDAQ")
PERIODS = (20, 50, 200)
MIN_MARKET_STOCKS = 300
MIN_COVERAGE = 0.70


def _get(url, timeout=30):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.content


def _as_date(value):
    x = str(value).strip().replace("-", "")[:8]
    if not re.fullmatch(r"\d{8}", x):
        raise ValueError(f"유효하지 않은 거래일: {value}")
    return pd.Timestamp(pd.to_datetime(x, format="%Y%m%d", errors="raise")).normalize()


def _field(frame, *choices):
    columns = {str(x).strip().lower(): x for x in frame.columns}
    for name in choices:
        if name.lower() in columns:
            return columns[name.lower()]
    raise ValueError(f"전 종목 파일 필드 누락: {', '.join(choices)}")


def parse_daily_csv(data: bytes, expected_date: pd.Timestamp) -> pd.DataFrame:
    """Public daily archives have Korean raw columns, not HF snapshot schema."""
    frame = pd.read_csv(BytesIO(data), dtype=str, encoding="utf-8-sig", low_memory=False)
    code_col = _field(frame, "종목코드", "code", "stock_code", "srtnCd")
    market_col = _field(frame, "mrktCtg", "market", "market_name")
    close_col = _field(frame, "clpr", "close", "close_krw", "closePrice")
    date_col = _field(frame, "basDt", "date", "base_date_yyyymmdd", "as_of")
    code = frame[code_col].astype(str).str.strip().str.zfill(6)
    market = frame[market_col].astype(str).str.strip().str.upper()
    close = pd.to_numeric(frame[close_col].astype(str).str.replace(",", "", regex=False), errors="coerce")
    raw_dates = frame[date_col].astype(str).str.replace("-", "", regex=False).str.slice(0, 8)
    if not raw_dates.eq(expected_date.strftime("%Y%m%d")).all():
        raise ValueError(f"일별 파일 내부 날짜가 URL과 다름: {expected_date.date()}")
    mask = code.str.fullmatch(r"\d{6}") & market.isin(MARKETS)
    out = pd.DataFrame({"code": code[mask], "market": market[mask],
                        "date": expected_date, "close": close[mask]}).reset_index(drop=True)
    if len(out) < 1500 or out['code'].duplicated().any():
        raise ValueError(f"전 종목 파일 종목 누락/중복: {expected_date.date()} ({len(out)}개)")
    if out['close'].isna().any() or out['close'].le(0).any():
        raise ValueError(f"종가 결측/0: {expected_date.date()}")
    return out


def _download_daily(day):
    return parse_daily_csv(_get(f"{AIK}/daily/quotes_{day:%Y%m%d}.csv", timeout=25), day)


def _read_baseline() -> pd.DataFrame:
    try:
        frame = pd.read_parquet(BytesIO(_get(HF_PARQUET, timeout=45)),
                                columns=["code", "market", "date", "close_krw"])
    except ImportError as exc:
        raise ValueError("pyarrow 패키지가 필요합니다. requirements.txt에 pyarrow>=16 추가") from exc
    required = {"code", "market", "date", "close_krw"}
    if not required.issubset(frame.columns):
        raise ValueError("과거 종가 데이터셋 필드 변경")
    if len(frame) < 500000:
        raise ValueError("과거 종가 데이터셋 행 수 부족")
    out = pd.DataFrame({
        "code": frame["code"].astype(str).str.zfill(6),
        "market": frame["market"].astype(str).str.upper(),
        "date": pd.to_datetime(frame["date"].astype(str), format="%Y%m%d", errors="coerce"),
        "close": pd.to_numeric(frame["close_krw"], errors="coerce")
    })
    out = out[out["market"].isin(MARKETS) & out["date"].notna()
              & out["close"].gt(0)].copy()
    if out.duplicated(["code", "date"]).any():
        raise ValueError("과거 데이터셋 종목·날짜 중복")
    return out


def compute_ma_breadth(history: pd.DataFrame, current: pd.DataFrame,
                       min_market_stocks=MIN_MARKET_STOCKS) -> pd.DataFrame:
    """No forward fills; MA averages the last N *market sessions*.

    Denominator = current stocks with all N valid historical closes.
    Coverage is exposed alongside every percentage (never quietly treat
    missing history as below-MA).
    """
    needed = {"code", "market", "date", "close"}
    if not needed.issubset(history) or not needed.issubset(current):
        raise ValueError("이동평균 집계 컬럼이 부족합니다")
    current = current[current["market"].isin(MARKETS)].copy()
    if current.duplicated("code").any():
        raise ValueError("현재일 종목 코드 중복")
    history = history[history["date"].le(current["date"].max())].copy()
    history = history.sort_values("date").drop_duplicates(["code", "date"], keep="last")
    # Align on global market sessions, not 200 arbitrary trading observations
    matrix = history.pivot(index="date", columns="code", values="close").sort_index()
    latest = current.set_index("code")["close"]
    result = []
    for period in PERIODS:
        ma = matrix.rolling(window=period, min_periods=period).mean().iloc[-1]
        joined = current[["code", "market"]].copy()
        joined["price"] = joined["code"].map(latest)
        joined["ma"] = joined["code"].map(ma)
        for market in MARKETS:
            group = joined[joined["market"] == market]
            total = len(group)
            if total < min_market_stocks:
                raise ValueError(f"{market}: 당일 전체 종목 수 부족 ({total})")
            valid = group["price"].gt(0) & group["ma"].gt(0) & group["ma"].notna()
            count = int(valid.sum())
            above = int((group.loc[valid, "price"] > group.loc[valid, "ma"]).sum())
            ratio = round(100 * above / count, 1) if count and count / total >= MIN_COVERAGE else None
            result.append({"시장": market, "이동평균": f"MA{period}",
                           "상회 비율(%)": ratio, "상회 종목": above,
                           "계산 가능 종목": count, "당일 전체 종목": total,
                           "이력 충족률(%)": round(100 * count / total, 1)})
    return pd.DataFrame(result)


@st.cache_data(ttl=21600, show_spinner=False, max_entries=1)
def load_ma_breadth():
    digest = requests.get(f"{AIK}/today.json", headers=HEADERS, timeout=18)
    digest.raise_for_status()
    digest = digest.json()
    current_date = _as_date(digest.get("quote_as_of_iso") or digest.get("as_of_iso"))
    if (datetime.now(KST).date() - current_date.date()).days > 7:
        raise ValueError(f"원자료 갱신이 7일 이상 지연됨: {current_date:%Y-%m-%d}")
    index = requests.get(f"{AIK}/index.json", headers=HEADERS, timeout=18)
    index.raise_for_status()
    catalog = index.json()
    archive = catalog.get("daily_archive") or {}
    raw_days = archive.get("quotes_available_dates") or []
    days = sorted(set(_as_date(x) for x in raw_days))
    if not days or current_date not in days:
        raise ValueError("최신 거래일 파일이 날짜별 아카이브 목록에 없음")

    baseline = _read_baseline()
    base_last = baseline["date"].max()
    if base_last > current_date:
        raise ValueError("과거 기준 데이터 날짜가 최신 종가보다 뒤입니다")
    target_days = [d for d in days if base_last < d <= current_date]
    if target_days:
        # The fixed HF snapshot and rolling 30-day archive MUST join without
        # a lost market session. No silently interpolated or backfilled prices.
        skipped_bdays = len(pd.bdate_range(base_last + pd.Timedelta(days=1),
                                           target_days[0] - pd.Timedelta(days=1)))
        if skipped_bdays:
            raise ValueError("과거 데이터(9월 스냅샷)와 최근 30일 CSV 사이의 거래일이 끊겼습니다. "
                             "전체 이동평균 비율 계산을 보류합니다. 갱신된 기준 데이터가 필요합니다.")
        # Overlapping days provide an independent format/price consistency check.
        overlap_days = [d for d in days if d <= base_last][-2:]
        fetch_days = sorted(set(target_days + overlap_days))
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_download_daily, d): d for d in fetch_days}
            downloaded = {}
            for future in as_completed(futures):
                downloaded[futures[future]] = future.result()
        for d in overlap_days:
            a = baseline[baseline['date'].eq(d)][['code', 'close']]
            b = downloaded[d][['code', 'close']]
            overlap = a.merge(b, on='code', suffixes=('_base', '_new'))
            if len(overlap) < 1500:
                raise ValueError(f"과거 자료와 최신 자료의 종목 교집합 부족: {d:%Y-%m-%d}")
            agreement = ((overlap['close_new'] / overlap['close_base'] - 1).abs() <= 0.005).mean()
            if agreement < 0.97:
                raise ValueError(f"과거 기준 데이터와 일별 CSV 종가 불일치: {d:%Y-%m-%d}")
        daily = [downloaded[d] for d in target_days]
        merged = pd.concat([baseline, *daily], ignore_index=True)
        latest = downloaded[current_date]
    else:
        merged = baseline
        latest = baseline[baseline['date'].eq(current_date)].copy()
        if latest.empty:
            raise ValueError("최신 종가 자료가 없습니다")
    result = compute_ma_breadth(merged, latest)
    return result, current_date.strftime("%Y-%m-%d"), base_last.strftime("%Y-%m-%d"), len(target_days)


def show_ma_breadth():
    st.markdown("#### 📈 코스피·코스닥 MA20·MA50·MA200 상회 비율")
    st.caption("전체 종목 확정 종가 이력을 기준으로 계산합니다. TOP 200 표본이 아닙니다. "
               "과거 시세는 수정주가가 아니며, 이력 부족 종목은 별도 집계합니다.")
    if st.button("📊 전체 종목 이동평균 상회 비율 계산", key="miner_ma_breadth_run"):
        st.session_state["miner_ma_breadth_open"] = True
    if not st.session_state.get("miner_ma_breadth_open", False):
        st.info("무료 전 종목 과거 시세 데이터를 읽는 작업이므로 버튼을 눌러 계산합니다.")
        return
    try:
        with st.spinner("전체 종목 20·50·200거래일 가격 이력과 누락 여부를 확인하는 중..."):
            table, asof, base, added = load_ma_breadth()
        st.caption(f"시세 기준일: {asof} · 과거 기준: {base} · 추가 아카이브 {added}거래일")
        for market in MARKETS:
            subset = table[table["시장"] == market]
            st.markdown(f"**{market}**")
            cols = st.columns(3)
            for col, (_, row) in zip(cols, subset.iterrows()):
                with col:
                    label = row["이동평균"]
                    ratio = row["상회 비율(%)"]
                    st.metric(f"{label} 위 종목 비율", "자료 부족" if pd.isna(ratio) else f"{ratio:.1f}%")
                    st.caption(f'집계 {int(row["계산 가능 종목"]):,}/{int(row["당일 전체 종목"]):,}종목')
        chart_data = table.dropna(subset=["상회 비율(%)"])
        if not chart_data.empty:
            fig = go.Figure()
            for label, color in [("MA20", "#70cbe0"), ("MA50", "#f4bd62"), ("MA200", "#88d5a0")]:
                rows = chart_data[chart_data["이동평균"] == label]
                fig.add_bar(x=rows["시장"], y=rows["상회 비율(%)"], name=label, marker_color=color)
            fig.update_layout(barmode="group", height=300, yaxis_range=[0,100],
                              paper_bgcolor="#101a28", plot_bgcolor="#101a28",
                              font=dict(color="#eef6ff"),
                              legend=dict(orientation="h", y=1.15, font=dict(color="#eef6ff")),
                              margin=dict(l=10,r=10,t=25,b=15))
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(table, hide_index=True, use_container_width=True)
        st.download_button("📥 MA20·50·200 전체시장 근거 요약 CSV",
                           table.to_csv(index=False).encode("utf-8-sig"),
                           "miner_ma_breadth.csv", mime="text/csv", key="miner_ma_csv")
        st.caption("자료: 한국주식데이터(aikstockdata.com), 금융위원회 공공데이터포털, "
                   "Hugging Face 공개 과거 종가 스냅샷. 비영리 개인 연구용. "
                   "상장폐지 종목 미포함(생존 편향), 분할 미조정, 집계 가능 종목 기준 비율. "
                   "과거 기준 데이터와 최근 30일 아카이브 연결이 끊기면 계산을 중지합니다.")
    except (ValueError, requests.RequestException, KeyError, OSError,
            ImportError, pd.errors.ParserError) as exc:
        st.warning(f"전체 종목 이동평균 상회 비율 산출 보류: {exc}")
