"""광부 투자터미널: *시장 전체* 코스피·코스닥 외국인/기관/개인 수급 화면.

기존 거래대금 TOP200과 독립된 수집 파일만 사용한다.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA = Path(__file__).resolve().parent / "data" / "kr_market_total_flow.json"
MARKETS = ("KOSPI", "KOSDAQ")
COLUMNS = ("foreign_net_krw", "institution_net_krw", "individual_net_krw")
LABELS = {"foreign_net_krw": "외국인", "institution_net_krw": "기관", "individual_net_krw": "개인"}


def read_verified_market_total():
    """No joined market amount is ever shown if the snapshot is malformed."""
    if not DATA.is_file():
        return None, "시장 전체 수급 수집 파일이 아직 없습니다. GitHub Actions의 'Collect KR full-market investor net flows'를 실행하세요."
    try:
        obj = json.loads(DATA.read_text(encoding="utf-8"))
        if obj.get("status") != "verified" or obj.get("source") not in ("KRX investor daily trading value via pykrx (KRX data website)", "Naver Finance - market investor daily net trading"):
            raise ValueError("시장 전체 수급 출처 또는 검증 상태가 맞지 않음")
        hist = obj.get("history")
        if not isinstance(hist, list) or not hist:
            raise ValueError("수급 일별 이력이 없음")
        valid = {}
        for r in hist:
            if not isinstance(r, dict):
                raise ValueError("일별 수급 형식 오류")
            d = date.fromisoformat(r["date"])
            for market in MARKETS:
                for key in COLUMNS:
                    v = r[market][key]
                    if not isinstance(v, int) or isinstance(v, bool):
                        raise ValueError("시장/투자자별 원 단위 금액 오류")
            if d.isoformat() in valid:
                raise ValueError("중복 거래일")
            valid[d.isoformat()] = r
        history = [valid[d] for d in sorted(valid)]
        if obj.get("latest_date") != history[-1]["date"]:
            raise ValueError("최신 거래일과 이력 날짜 불일치")
        return (obj, history), None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, OSError) as exc:
        return None, f"시장 전체 수급 파일 검증 실패: {exc}"


def _money_text(won):
    return f"{won / 100_000_000:+,.0f}억"


def _total(rows, markets, fields):
    return sum(row[market][key] for row in rows for market in markets for key in fields)


def _recent_window(history, n):
    if len(history) < n:
        return None
    recent = history[-n:]
    span = (date.fromisoformat(recent[-1]["date"]) - date.fromisoformat(recent[0]["date"])).days
    if span > (12 if n == 5 else 43):
        return None
    return recent


def render_market_totals():
    st.subheader("코스피 · 코스닥 전체 현물 수급")
    st.caption("시장별 투자자 순매수 **금액(원)** · TOP 200 표본 집계와 구별 · 선물 미포함")
    value, issue = read_verified_market_total()
    if issue:
        st.warning(issue)
        st.info("전체 시장 원자료가 검증되기 전까지 수치를 임의로 채우지 않습니다. 아래에서 기존 TOP 200 표본 분석은 계속 볼 수 있습니다.")
        return False
    obj, history = value
    st.caption(f"자료 제공처: {obj.get('source', '미확인')} · {obj.get('source_page', '')}")
    if obj.get('includes_etf_etn_elw') is not False:
        st.warning('네이버 시장 통계는 KRX 공식 API가 아닙니다. ETF·ETN·ELW 포함 여부는 독립 검증되지 않았으므로 동일 범위의 공식 KRX 집계와 혼동하지 마세요.')
    day = history[-1]["date"]
    now = datetime.now(ZoneInfo("Asia/Seoul")).date()
    age = (now - date.fromisoformat(day)).days
    st.caption(f"**자료 기준일: {day}** · 저장 {obj.get('collected_at_kst', '미확인')} · 보관된 거래일 {len(history)}개")
    if age > 3:
        st.warning(f"마지막 수급 자료가 {age}일 전 거래일 기준입니다. 최신 장세를 나타내지 않을 수 있습니다.")

    latest = history[-1]
    summary = []
    for title, markets in (("코스피", ("KOSPI",)), ("코스닥", ("KOSDAQ",)), ("합계", MARKETS)):
        foreign = _total([latest], markets, ("foreign_net_krw",))
        institution = _total([latest], markets, ("institution_net_krw",))
        individual = _total([latest], markets, ("individual_net_krw",))
        summary.append({"시장": title, "외국인(억)": foreign / 1e8,
                        "기관(억)": institution / 1e8, "개인(억)": individual / 1e8,
                        "외국인+기관(억)": (foreign + institution) / 1e8})

    st.markdown("#### 기준일 투자자별 순매수")
    st.dataframe(pd.DataFrame(summary).round(1), hide_index=True, use_container_width=True)
    metrics = st.columns(3)
    metrics[0].metric("코스피 · 외국인+기관", _money_text(_total([latest], ("KOSPI",), COLUMNS[:2])))
    metrics[1].metric("코스닥 · 외국인+기관", _money_text(_total([latest], ("KOSDAQ",), COLUMNS[:2])))
    metrics[2].metric("양 시장 합계", _money_text(_total([latest], MARKETS, COLUMNS[:2])))

    fig = go.Figure()
    for key in COLUMNS:
        fig.add_bar(name=LABELS[key], x=["코스피", "코스닥"],
                    y=[latest[m][key] / 1e8 for m in MARKETS])
    fig.add_hline(y=0, line_width=1)
    fig.update_layout(barmode="relative", height=300, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="순매수 (억원)")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 5·20거래일 누적 순매수")
    cumulative = []
    for days in (5, 20):
        chunk = _recent_window(history, days)
        if chunk is None:
            cumulative.append({"기간": f"최근 {days}일", "외국인(억)": None, "기관(억)": None,
                               "합산(억)": None, "상태": "자료 축적 중 / 거래일 간격 확인 필요"})
        else:
            f = _total(chunk, MARKETS, COLUMNS[:1]); i = _total(chunk, MARKETS, COLUMNS[1:2])
            cumulative.append({"기간": f"최근 {days}일", "외국인(억)": round(f / 1e8, 1),
                               "기관(억)": round(i / 1e8, 1), "합산(억)": round((f+i)/1e8, 1),
                               "상태": f"{chunk[0]['date']} ~ {chunk[-1]['date']}"})
    st.dataframe(pd.DataFrame(cumulative), hide_index=True, use_container_width=True)
    st.caption("누적치는 **실제로 확보한 서로 다른 거래일**만 사용합니다. 자료가 부족하거나 날짜 간격이 크면 계산하지 않습니다.")

    rows = []
    for r in reversed(history[-60:]):
        for market in MARKETS:
            rows.append({"거래일": r["date"], "시장": market,
                         **{LABELS[k] + "(억)": round(r[market][k] / 1e8, 2) for k in COLUMNS},
                         "외국인+기관(억)": round((r[market]["foreign_net_krw"] + r[market]["institution_net_krw"]) / 1e8, 2)})
    detail = pd.DataFrame(rows)
    with st.expander("시장 전체 수급 거래일별 내역 / CSV 다운로드"):
        st.dataframe(detail, hide_index=True, use_container_width=True)
        st.download_button("📥 시장 전체 수급 CSV", detail.to_csv(index=False).encode("utf-8-sig"),
                           file_name="miner_full_market_flow.csv", mime="text/csv", key="miner_full_market_csv")
    st.caption("주의: 시장 간 합산은 KOSPI+KOSDAQ 두 시장만 해당합니다. KONEX·파생상품은 미포함. 네이버 공급 데이터의 ETF·ETN·ELW 포함 여부는 미검증입니다.")
    return True
