"""Manual multi-stock RS/DMI/ATR observation panel for Miner Terminal.

Not a market-wide scanner and not a validated trading strategy. Yahoo Finance
adjusted daily prices can be delayed; per-instrument index dates are aligned.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from stock_analysis_ui import dmi_snapshot, history

MAX_MANUAL_SYMBOLS = 15  # Per-click safety limit, not a limit on the TOP200 universe.


def symbols_from_text(raw: str) -> list[str]:
    tokens = [x.strip().upper() for x in re.split(r"[,;\s]+", raw) if x.strip()]
    unique = list(dict.fromkeys(tokens))
    if len(unique) > MAX_MANUAL_SYMBOLS:
        raise ValueError(
            f"한 번에 {MAX_MANUAL_SYMBOLS}종목까지 비교할 수 있습니다. "
            "이 화면은 수동 비교이며 TOP200 전체 분석의 종목 수를 제한하지 않습니다."
        )
    for symbol in unique:
        if not re.fullmatch(r"\d{6}\.(?:KS|KQ)", symbol):
            raise ValueError(f"종목 표기 오류: {symbol} (예: 005930.KS, 000660.KS, 035420.KS)")
    if not unique:
        raise ValueError("분석할 종목코드를 하나 이상 입력하세요.")
    return unique


def analyze_pair(symbol: str, stock: pd.DataFrame, benchmark: pd.DataFrame, adx_cutoff: float) -> dict:
    """Calculate on the *last shared daily close* to prevent mixed-day RS."""
    common = stock['Close'].to_frame('stock').join(
        benchmark['Close'].to_frame('market'), how='inner'
    ).dropna().sort_index()
    if len(common) < 61:
        raise ValueError(f"{symbol}: 지수와 공통 거래일 61개 미만")
    asof = common.index[-1]
    last = stock.loc[:asof].copy()
    if len(last) < 90:
        raise ValueError(f"{symbol}: DI·ADX 계산에 필요한 90거래일 미만")
    dmi = dmi_snapshot(last)
    stock_ret = common['stock'].iloc[-1] / common['stock'].iloc[-61] - 1
    bench_ret = common['market'].iloc[-1] / common['market'].iloc[-61] - 1
    rs_pp = (stock_ret - bench_ret) * 100
    flags = {
        'DI': dmi['plus_di'] > dmi['minus_di'],
        'ADX': dmi['adx'] >= adx_cutoff,
        'RS': rs_pp > 0,
    }
    score = sum(flags.values())
    # Distance only: not a trade instruction or a validated stop technique.
    atr_pct = dmi['atr_pct']
    stop_distance_pct = 2 * atr_pct
    example_weight_pct = min(100.0, 100.0 / stop_distance_pct) if stop_distance_pct > 0 else None
    return {
        '종목코드': symbol,
        '비교지수': 'KOSPI' if symbol.endswith('.KS') else 'KOSDAQ',
        '기준일': asof.strftime('%Y-%m-%d'),
        '종가': round(float(common['stock'].iloc[-1]), 2),
        '+DI': round(dmi['plus_di'], 1),
        '-DI': round(dmi['minus_di'], 1),
        'ADX': round(dmi['adx'], 1),
        '60일 RS(%p)': round(float(rs_pp), 2),
        'ATR(%)': round(atr_pct, 2),
        '2ATR 거리(%)': round(stop_distance_pct, 2),
        '예시 비중(%)': round(example_weight_pct, 1) if example_weight_pct is not None else None,
        '조건': f'{score}/3',
        '관찰 상태': '추세·RS 관찰' if score == 3 else ('부분 충족' if score > 0 else '관망'),
        '_score': score,
        '_raw_rs': rs_pp,
    }


def render_candidates() -> None:
    st.divider()
    st.markdown('### 🧭 여러 종목 비교 | RS · DI/ADX · ATR')
    st.caption(
        '개별 종목을 60거래일 동안 코스피·코스닥 대비 비교합니다. '
        '기존 TOP200 순위와 별개의 수동 관찰표이며, 공시 실적 심사는 아직 미연결입니다.'
    )
    with st.form('miner_trend_compare_form'):
        raw = st.text_input(
            '종목코드 (쉼표로 구분, 코스피 .KS / 코스닥 .KQ)',
            value='005930.KS, 000660.KS, 035420.KS, 035720.KS',
            key='miner_trend_compare_codes',
        )
        cutoff = st.slider('ADX 최소 기준', min_value=15, max_value=35,
                           value=20, step=1, key='miner_trend_compare_adx')
        submitted = st.form_submit_button('🔎 비교표 계산')
    if submitted:
        try:
            codes = symbols_from_text(raw)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state['miner_trend_compare_request'] = (codes, cutoff)
    request = st.session_state.get('miner_trend_compare_request')
    if request is None:
        st.info('코드를 선택한 뒤 비교표 계산을 누르면 조회합니다. 페이지를 열자마자 대량 요청하지 않습니다.')
        return
    codes, cutoff = request
    output, failures = [], []
    with st.spinner('Yahoo 일별 가격과 시장 지수를 비교하는 중...'):
        for symbol in codes:
            benchmark = '^KS11' if symbol.endswith('.KS') else '^KQ11'
            try:
                output.append(analyze_pair(symbol, history(symbol), history(benchmark), cutoff))
            except Exception as exc:
                # No fake scores; isolate one ticker failure from the remaining watchlist.
                failures.append(f'{symbol}: {type(exc).__name__} / {str(exc)[:110]}')
    if output:
        frame = pd.DataFrame(output).sort_values(
            ['_score', '_raw_rs'], ascending=[False, False]
        ).drop(columns=['_score', '_raw_rs']).reset_index(drop=True)
        frame.insert(0, '순위', range(1, len(frame) + 1))
        st.dataframe(frame, hide_index=True, use_container_width=True)
        st.download_button('📥 비교 결과 CSV',
                           frame.to_csv(index=False).encode('utf-8-sig'),
                           file_name='miner_rs_dmi_atr_comparison.csv', mime='text/csv',
                           key='miner_trend_compare_csv')
        all_dates = sorted(set(frame['기준일'].tolist()))
        if len(all_dates) > 1:
            st.warning('종목별 최종 공통 거래일이 다릅니다. 기준일 열을 비교해 주세요.')
        st.caption(
            '3/3 = +DI>-DI, ADX가 설정 기준 이상, 60일 RS가 양수. '
            '신호의 수익성은 검증되지 않았으며 실적·밸류에이션 심사는 포함하지 않습니다.'
        )
        st.caption(
            '2ATR 거리는 현재 일봉 ATR의 두 배를 주가 대비 표시한 참고치. '
            '예시 비중은 계좌 손실 허용 1%, 2ATR 손절을 가정한 단순 산식(최대 100%). '
            '갭하락·비용·포지션 상관관계는 반영하지 않습니다.'
        )
    if failures:
        with st.expander(f'수집 실패 / 데이터 부족 {len(failures)}건'):
            for msg in failures:
                st.warning(msg)
    st.caption('Yahoo Finance 수정 일봉 · 15분 캐시 · 지연 가능. 기준일이 다른 시세를 합쳐 현재 신호로 표시하지 않습니다.')
