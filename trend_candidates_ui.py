"""Manual multi-stock RS/DMI/ATR observation panel for Miner Terminal.

Not a market-wide scanner and not a validated trading strategy. Yahoo Finance
adjusted daily prices can be delayed; per-instrument index dates are aligned.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from stock_analysis_ui import dmi_snapshot, history

MAX_MANUAL_SYMBOLS = 15  # Per-click safety limit, not a limit on the TOP200 universe.


# MINER_STOCK_NAMES_V2
ROOT = Path(__file__).resolve().parent


def normalize_name(value: str) -> str:
    """Normalize whitespace/case, but never guess a ticker from a partial name."""
    return re.sub(r"\s+", "", str(value)).casefold()


def load_stock_names():
    """Get validated ticker/name/market pairs from existing TOP200 snapshot."""
    by_symbol, by_code, by_name = {}, {}, {}
    source_date = "미확인"
    try:
        obj = json.loads((ROOT / "data" / "kr_flow.json").read_text(encoding="utf-8"))
        if obj.get("status") != "verified" or not isinstance(obj.get("top200"), list):
            raise ValueError("종목명 목록 상태 미검증")
        source_date = str(obj.get("date") or "미확인")
        for row in obj["top200"]:
            code, market, name = str(row.get("ticker") or ""), row.get("market"), str(row.get("name") or "").strip()
            if not re.fullmatch(r"\d{6}", code) or market not in ("KOSPI", "KOSDAQ") or not name:
                continue
            symbol = code + (".KS" if market == "KOSPI" else ".KQ")
            if symbol in by_symbol:
                continue
            by_symbol[symbol] = name
            by_code.setdefault(code, []).append(symbol)
            by_name.setdefault(normalize_name(name), []).append(symbol)
        # Stock exchange uses NAVER; Korean-language alias is an exact synonym.
        if "035420.KS" in by_symbol and normalize_name(by_symbol["035420.KS"]) == "naver":
            by_name.setdefault(normalize_name("네이버"), []).append("035420.KS")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}, {}, {}, "미확인"
    return by_symbol, by_code, by_name, source_date


def resolve_symbols(raw: str, by_symbol: dict, by_code: dict, by_name: dict):
    """Accept an exact stock name, six-digit code, or full Yahoo symbol."""
    tokens = [x.strip() for x in re.split(r"[,;\n]+", raw) if x.strip()]
    if not tokens:
        raise ValueError("종목명 또는 종목코드를 하나 이상 입력하세요.")
    found = {}
    for token in tokens:
        up = token.upper()
        if re.fullmatch(r"\d{6}\.(KS|KQ)", up):
            symbol = up
            if symbol[:6] in by_code and symbol not in by_code[symbol[:6]]:
                raise ValueError(f"{token}: 시장 구분(.KS/.KQ)이 종목명 목록과 일치하지 않습니다.")
        elif re.fullmatch(r"\d{6}", token):
            matches = by_code.get(token, [])
            if len(matches) != 1:
                raise ValueError(f"{token}: 시장 구분을 확인할 수 없습니다. 000000.KS 또는 .KQ를 입력하세요.")
            symbol = matches[0]
        else:
            matches = list(dict.fromkeys(by_name.get(normalize_name(token), [])))
            if len(matches) != 1:
                raise ValueError(f"'{token}' 종목명을 현재 TOP200에서 정확히 찾을 수 없습니다. 종목코드(예: 005930.KS)로 입력하세요.")
            symbol = matches[0]
        found[symbol] = by_symbol.get(symbol, "종목명 미확인")
        if len(found) > MAX_MANUAL_SYMBOLS:
            raise ValueError(f"한 번에 {MAX_MANUAL_SYMBOLS}개 종목까지 수동 비교할 수 있습니다. TOP200 전체 종목 수 제한은 아닙니다.")
    return found


def symbols_from_text(raw: str) -> list[str]:
    """Backward-compatible public helper, now supports exact stock names."""
    names, codes, lookup, _ = load_stock_names()
    return list(resolve_symbols(raw, names, codes, lookup))


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
        '종목명으로 검색하고 RS·DI/ADX·ATR을 비교합니다. '
        '종목명 검색은 저장된 TOP200 목록 기준이며, 목록 외 종목도 .KS/.KQ 종목코드로 조회할 수 있습니다.'
    )
    by_symbol, by_code, by_name, name_date = load_stock_names()
    with st.form('miner_trend_compare_form'):
        raw = st.text_input(
            '종목명 또는 종목코드 (쉼표로 구분)',
            value='삼성전자, SK하이닉스, 네이버, 카카오',
            key='miner_trend_compare_names_v2',
            help='예: 삼성전자, SK하이닉스, 네이버 / 005930.KS, 000660.KS',
        )
        cutoff = st.slider('ADX 최소 기준', min_value=15, max_value=35,
                           value=20, step=1, key='miner_trend_compare_adx')
        submitted = st.form_submit_button('🔎 비교표 계산')
    st.caption(f'종목명 조회 목록: TOP200 · 기준일 {name_date}. 주가·지표는 Yahoo 최신 공통 거래일 기준입니다.')
    if submitted:
        try:
            selected = resolve_symbols(raw, by_symbol, by_code, by_name)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state['miner_trend_compare_request_v2'] = (selected, cutoff)
    request = st.session_state.get('miner_trend_compare_request_v2')
    if request is None:
        st.info('종목명을 입력하고 비교표 계산을 누르면 조회합니다. 페이지 진입 시 대량 요청하지 않습니다.')
        return
    chosen, cutoff = request
    output, failures = [], []
    with st.spinner('Yahoo 일별 가격과 시장 지수를 비교하는 중...'):
        for symbol, original_name in chosen.items():
            benchmark = '^KS11' if symbol.endswith('.KS') else '^KQ11'
            try:
                item = analyze_pair(symbol, history(symbol), history(benchmark), cutoff)
                # Refresh names if the verified stock-name snapshot was updated.
                item['종목명'] = by_symbol.get(symbol, original_name)
                item['종목코드'] = symbol[:6]
                output.append(item)
            except Exception as exc:
                failures.append(f'{original_name} ({symbol}): {type(exc).__name__} / {str(exc)[:110]}')
    if output:
        frame = pd.DataFrame(output).sort_values(
            ['_score', '_raw_rs'], ascending=[False, False]
        ).drop(columns=['_score', '_raw_rs']).reset_index(drop=True)
        frame.insert(0, '순위', range(1, len(frame) + 1))
        front = ['순위', '종목명', '종목코드']
        frame = frame[front + [c for c in frame.columns if c not in front]]
        # MINER_DART_YOY_QOQ_TABLE_V1
        from quarter_fundamentals_ui import enrich_comparison
        frame, dart_ready = enrich_comparison(frame)
        if not dart_ready:
            st.caption('OpenDART 분기 실적 미수집 · 설치 후 수집 실행 시 YoY/QoQ 열 표시')
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
            '수익성은 검증되지 않았으며 실적·밸류에이션 심사는 포함하지 않습니다.'
        )
        st.caption(
            '2ATR 거리 = 현재 일봉 ATR의 두 배를 주가 대비 표시한 참고치. '
            '예시 비중은 계좌 손실 허용 1%, 2ATR 손절을 가정한 단순 산식(최대 100%). '
            '갭하락·비용·포지션 상관관계는 반영하지 않습니다.'
        )
    if failures:
        with st.expander(f'수집 실패 / 데이터 부족 {len(failures)}건'):
            for msg in failures:
                st.warning(msg)
    st.caption('Yahoo Finance 수정 일봉 · 15분 캐시 · 지연 가능. 기준일이 다른 시세를 합쳐 현재 신호로 표시하지 않습니다.')
