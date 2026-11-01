"""광부 투자터미널: 시장 전체 현물 수급과 거래대금 TOP200 표본을 구분.

전체 현물은 독립된 KRX 일별 검증 파일에서, TOP200은 별도 표본 수급에서 표시한다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from flow_signals import merge_history, rolling_strength, summarize_snapshot, valid_history
from market_total_ui import render_market_totals

ROOT = Path(__file__).resolve().parent
RANK_FILE = ROOT / 'data' / 'kr_flow.json'
FLOW_FILE = ROOT / 'data' / 'kr_investor_flow.json'
MONEY_FIELDS = ('외국인 순매수(억)', '기관 순매수(억)', '개인 순매수(억)')
MARKET_NAMES = {'ALL': 'TOP 200 전체', 'KOSPI': '코스피 표본', 'KOSDAQ': '코스닥 표본'}


@st.cache_data(ttl=120, show_spinner=False)
def load_top():
    obj = json.loads(RANK_FILE.read_text(encoding='utf-8'))
    if obj.get('status') != 'verified' or not obj.get('date'):
        raise ValueError('TOP200 거래대금 원자료의 거래일이 검증되지 않았습니다.')
    df = pd.DataFrame(obj.get('top200') or [])
    required = {'ticker', 'name', 'market', 'traded_krw', 'close'}
    if len(df) != 200 or not required.issubset(df.columns):
        raise ValueError('TOP200 종목 수 또는 필수 컬럼이 올바르지 않습니다.')
    df['ticker'] = df['ticker'].astype(str).str.zfill(6)
    if df['ticker'].duplicated().any():
        raise ValueError('TOP200 종목코드가 중복됐습니다.')
    df['traded_krw'] = pd.to_numeric(df['traded_krw'], errors='coerce')
    if df['traded_krw'].isna().any() or (df['traded_krw'] <= 0).any():
        raise ValueError('TOP200 거래대금 값이 올바르지 않습니다.')
    df = df.sort_values('traded_krw', ascending=False, kind='stable').reset_index(drop=True)
    df.insert(0, '순위', range(1, len(df) + 1))
    return df, obj


@st.cache_data(ttl=120, show_spinner=False)
def load_flow():
    if not FLOW_FILE.exists():
        return None
    return json.loads(FLOW_FILE.read_text(encoding='utf-8'))


def get_snapshot(df, meta):
    flow = load_flow()
    if not flow:
        return {}, '수급 파일이 없습니다. GitHub Actions의 수급 수집 작업을 확인해 주세요.', None
    codes = df['ticker'].tolist()
    expected = hashlib.sha256((meta['date'] + '|' + ','.join(codes)).encode('utf-8')).hexdigest()
    if flow.get('date') != meta['date'] or flow.get('fingerprint') != expected:
        return {}, '거래대금과 수급의 기준일 또는 종목 구성이 달라 수급 표시를 보류합니다.', flow
    if not isinstance(flow.get('rows'), dict):
        return {}, '수급 데이터 형식이 올바르지 않습니다.', flow
    return flow['rows'], None, flow


def prepare():
    """두 메뉴가 사용하는 하나의, 검증된 종목별 원자료."""
    try:
        frame, meta = load_top()
        records, issue, flow = get_snapshot(frame, meta)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        st.error(f'원자료 오류: {exc}')
        return None
    st.caption(f'거래대금 기준일 **{meta["date"]}** · {meta.get("source", "출처 미확인")} · 확정 종가')
    if issue:
        st.warning(issue)
    elif flow:
        st.caption(f'수급 기준일 **{flow["date"]}** · {flow.get("source", "출처 미확인")} · 수집시각 {flow.get("collected_at_kst", "-")}')
        st.caption(f'수급 확인 {flow.get("complete_codes", 0)}/200종목 · 실패/제외 {len(flow.get("errors") or [])}건')
        if flow.get('errors'):
            with st.expander('수집 오류 상세'):
                for error in flow['errors'][:50]:
                    st.text(str(error)[:180])

    def mapped(key):
        return pd.to_numeric(frame['ticker'].map(lambda code: (records.get(code) or {}).get(key)), errors='coerce')

    # 원 단위 값을 유지한 채 판정한 뒤 화면에 표시할 때만 억 단위로 반올림한다.
    foreign = mapped('foreign_net_krw')
    institution = mapped('institution_net_krw')
    personal = mapped('individual_net_krw')
    frame['수급 기준일'] = frame['ticker'].map(lambda code: (records.get(code) or {}).get('date'))
    valid_date = frame['수급 기준일'].eq(meta['date'])
    foreign = foreign.where(valid_date)
    institution = institution.where(valid_date)
    personal = personal.where(valid_date)
    traded = frame['traded_krw']
    paired = foreign.notna() & institution.notna()

    frame['확인상태'] = '미수집'
    frame.loc[foreign.notna() | institution.notna(), '확인상태'] = '일부 확인'
    frame.loc[paired, '확인상태'] = '확인'
    frame['수급 분류'] = '미확인'
    frame.loc[paired, '수급 분류'] = '혼조/보합'
    frame.loc[paired & (foreign > 0) & (institution > 0), '수급 분류'] = '동반 순매수'
    frame.loc[paired & (foreign < 0) & (institution < 0), '수급 분류'] = '동반 순매도'

    frame['거래대금(억)'] = (traded / 100_000_000).round(2)
    frame[MONEY_FIELDS[0]] = (foreign / 100_000_000).round(2)
    frame[MONEY_FIELDS[1]] = (institution / 100_000_000).round(2)
    frame[MONEY_FIELDS[2]] = (personal / 100_000_000).round(2)
    frame['수급 합계(억)'] = ((foreign + institution).where(paired) / 100_000_000).round(2)
    frame['외국인 강도(%)'] = (foreign / traded * 100).round(2)
    frame['기관 강도(%)'] = (institution / traded * 100).round(2)
    frame['수급강도(%)'] = ((foreign + institution).where(paired) / traded * 100).round(2)
    return frame


def _as_100m(value):
    return '자료 없음' if value is None else f'{value / 100_000_000:+,.1f}억'


def _summary_data():
    """요약은 금액 집계용 순수 계산 모듈을 공유하고, 미검증 스냅샷은 숨긴다."""
    try:
        meta = json.loads(RANK_FILE.read_text(encoding='utf-8'))
        flow = load_flow()
        if flow is None:
            return None, None, '아직 수급 수집 파일이 없습니다.'
        summary = summarize_snapshot(meta, flow)
        return summary, flow, None
    except (ValueError, KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        return None, None, f'수급 요약 계산 보류: {exc}'


def _market_table(summary):
    rows = []
    for key, label in MARKET_NAMES.items():
        m = summary['metrics'][key]
        rows.append({
            '구분': label,
            '종목 수': m['target_count'],
            '확인 종목': m['paired_count'],
            '외국인(억)': None if m['foreign_net_krw'] is None else round(m['foreign_net_krw'] / 1e8, 1),
            '기관(억)': None if m['institution_net_krw'] is None else round(m['institution_net_krw'] / 1e8, 1),
            '합산 수급강도(%)': None if m['joint_strength_pct'] is None else round(m['joint_strength_pct'], 2),
            '동반 순매수': m['both_buy_count'],
            '동반 순매도': m['both_sell_count'],
            '확산도(%p)': None if m['diffusion_pct'] is None else round(m['diffusion_pct'], 1),
        })
    return pd.DataFrame(rows)


def show_flow_signals(meta=None, market='ALL'):
    """자금 흐름 페이지에서만 호출하는 표본 수급 분석. 기존 함수명은 유지."""
    summary, flow, issue = _summary_data()
    if issue:
        st.warning(issue)
        return
    m = summary['metrics'][market]
    st.markdown(f'### {MARKET_NAMES[market]} · 수급강도와 매수 확산도')
    if not m['paired_count']:
        st.info('분석 가능한 외국인·기관 수급 금액이 아직 없습니다.')
        return
    if m['coverage_pct'] < 95 or m['turnover_coverage_pct'] < 98:
        st.warning(f'수급 자료 부분 누락: {m["paired_count"]}/{m["target_count"]}종목, 거래대금 커버리지 {m["turnover_coverage_pct"]:.1f}%. 추세 해석에 주의하세요.')

    cols = st.columns(4)
    cols[0].metric('외국인 순매수', _as_100m(m['foreign_net_krw']))
    cols[1].metric('기관 순매수', _as_100m(m['institution_net_krw']))
    cols[2].metric('합산 수급강도', f'{m["joint_strength_pct"]:+.2f}%')
    cols[3].metric('동반 매수 / 매도', f'{m["both_buy_count"]} / {m["both_sell_count"]}종목')
    st.caption('강도 = 확인 종목들의 순매수 합계 ÷ 동일 종목들의 거래대금 합계 × 100. 확산도 = (외국인·기관 동반 순매수 수 − 동반 순매도 수) ÷ 수급 확인 종목 수 × 100.')

    fig = go.Figure()
    fig.add_bar(x=['외국인', '기관', '합산'], y=[m['foreign_strength_pct'], m['institution_strength_pct'], m['joint_strength_pct']],
                marker_color=['#57badd', '#efb96a', '#8bcfa7'])
    fig.add_hline(y=0, line_color='#8b9caa', line_width=1)
    fig.update_layout(height=235, margin=dict(l=10, r=10, t=12, b=10), yaxis_title='순매수 / 거래대금 (%)',
                      paper_bgcolor='#101a28', plot_bgcolor='#101a28', font=dict(color='#e5edf6'))
    st.plotly_chart(fig, use_container_width=True)
    if m['joint_strength_pct'] > 0 and m['diffusion_pct'] < 0:
        st.info('자금 합계는 순매수지만 동반 순매도 종목이 더 많습니다. 매수가 소수 종목에 집중됐을 가능성을 점검하세요.')
    elif m['joint_strength_pct'] < 0 and m['diffusion_pct'] > 0:
        st.info('동반 매수 종목이 더 많아도 거래대금이 큰 종목의 순매도가 합산 수급을 누를 수 있습니다.')

    history = merge_history(flow.get('history'), summary)
    valid = valid_history(history, market)
    o5, o20 = rolling_strength(history, market, 5), rolling_strength(history, market, 20)
    st.markdown('#### 누적 수급강도 관찰 (5·20개 유효 수집일)')
    left, right = st.columns(2)
    left.metric('5개 유효일', f'{o5["pct"]:+.2f}%' if o5 else '자료 축적 중')
    right.metric('20개 유효일', f'{o20["pct"]:+.2f}%' if o20 else '자료 축적 중')
    if not o5 or not o20:
        st.caption(f'유효 거래일 {len(valid)}개. 필요한 관측일이 쌓이지 않으면 계산하지 않습니다. 표본은 날마다 바뀌며 결측일은 보간하지 않습니다.')
    else:
        st.caption(f'5개 − 20개 수급강도 차이: {o5["pct"] - o20["pct"]:+.2f}%p · 매매 신호가 아닌 관찰용 지표')
    if len(valid) >= 5:
        dates, v5, v20 = [], [], []
        for n in range(5, len(valid) + 1):
            segment = valid[:n]
            dates.append(segment[-1]['date'])
            x5, x20 = rolling_strength(segment, market, 5), rolling_strength(segment, market, 20)
            v5.append(x5['pct'] if x5 else None)
            v20.append(x20['pct'] if x20 else None)
        chart = go.Figure()
        chart.add_scatter(x=dates, y=v5, name='5개 유효일', mode='lines+markers', line=dict(color='#70cbe0'))
        if any(x is not None for x in v20):
            chart.add_scatter(x=dates, y=v20, name='20개 유효일', mode='lines+markers', line=dict(color='#f4bd62'))
        chart.add_hline(y=0, line_color='#8b9caa', line_width=1)
        chart.update_layout(height=270, margin=dict(l=10, r=10, t=12, b=10), yaxis_title='합산 수급강도 (%)',
                            paper_bgcolor='#101a28', plot_bgcolor='#101a28', font=dict(color='#e5edf6'))
        st.plotly_chart(chart, use_container_width=True)
    st.caption('시장 전체 KRX 수급이 아닌 매일 바뀌는 TOP200 종목 표본. 선물 수급은 아직 미연결입니다.')


def cashflow():
    """시장 전체 자금 흐름을 우선 표시하고 TOP200은 표본 비교로만 제공."""
    st.title('💸 자금 흐름 | 코스피·코스닥 전체 현물 수급')
    st.caption('KRX 시장 전체 현물 순매수와 거래대금 상위 TOP200 표본을 분리합니다.')
    render_market_totals()
    with st.expander('🔎 거래대금 TOP200 표본 수급 비교 (시장 전체 집계 아님)'):
        st.caption('표본 합계는 시장 전체 수급과 다르며, 두 자료는 서로 다른 거래일일 수 있습니다.')
        summary, flow, issue = _summary_data()
        if issue:
            st.warning(issue)
        else:
            table = _market_table(summary)
            st.dataframe(table, hide_index=True, use_container_width=True)
            st.download_button('📥 TOP200 표본 시장별 수급 CSV',
                               table.to_csv(index=False).encode('utf-8-sig'),
                               'miner_top200_market_flow.csv', mime='text/csv',
                               key='miner_market_flow_csv')
            choice = st.selectbox('표본 상세', ['전체 TOP200', 'KOSPI 표본', 'KOSDAQ 표본'],
                                  key='miner_market_flow_scope')
            selected = {'전체 TOP200': 'ALL', 'KOSPI 표본': 'KOSPI',
                        'KOSDAQ 표본': 'KOSDAQ'}[choice]
            show_flow_signals(market=selected)
    st.caption('KOSPI200 선물 투자자별 매매동향은 아직 미연결. 현물 수급을 선물로 오인하지 않습니다.')


def top200():
    """종목 발굴용 스크리너: 시장 오실레이터 반복 출력 없이 검색·필터·랭킹만."""
    st.title('📊 TOP 200 | 종목별 매수세 탐색')
    st.caption('거래대금 상위 200종목에서 매수세가 집중되는 기업을 찾습니다. 자금 흐름 메뉴의 시장 요약과 기능을 분리했습니다.')
    frame = prepare()
    if frame is None:
        return

    a, b, c = st.columns(3)
    with a:
        market = st.selectbox('시장', ['전체', 'KOSPI', 'KOSDAQ'], key='topmarket')
    with b:
        classification = st.selectbox('수급 조건', ['전체', '동반 순매수', '동반 순매도', '혼조/보합', '미확인'], key='miner_top200_class')
    with c:
        sort_choice = st.selectbox('정렬', ['거래대금 순위', '합산 수급강도', '외국인 강도', '기관 강도', '외국인 순매수', '기관 순매수'], key='miner_flow_sort')
    term = st.text_input('종목명 또는 종목코드 검색', key='miner_top200_search').strip()
    if market != '전체':
        frame = frame[frame['market'].eq(market)]
    # 0원은 실제 값으로 유지하고, 미수집 종목은 별도 필터로만 남긴다.
    if classification != '전체':
        if classification == '미확인':
            frame = frame[frame['확인상태'].ne('확인')]
        else:
            frame = frame[frame['수급 분류'].eq(classification)]
    if term:
        frame = frame[frame['name'].str.contains(term, regex=False, case=False, na=False) |
                      frame['ticker'].str.contains(term, regex=False, na=False)]

    n_matched = int(frame['확인상태'].eq('확인').sum())
    n_both_buy = int(frame['수급 분류'].eq('동반 순매수').sum())
    n_both_sell = int(frame['수급 분류'].eq('동반 순매도').sum())
    c1, c2, c3 = st.columns(3)
    c1.metric('현재 필터 종목', f'{len(frame)}개')
    c2.metric('외국인·기관 동반 매수', f'{n_both_buy}개')
    c3.metric('동반 매도', f'{n_both_sell}개')
    st.caption(f'금액 확인 {n_matched}개 · 수급강도는 개별 종목 순매수 합계 ÷ 해당 종목 거래대금 × 100 (매매 신호 아님)')

    sort_col = {
        '합산 수급강도': '수급강도(%)',
        '외국인 강도': '외국인 강도(%)',
        '기관 강도': '기관 강도(%)',
        '외국인 순매수': '외국인 순매수(억)',
        '기관 순매수': '기관 순매수(억)',
    }.get(sort_choice)
    if sort_col:
        frame = frame.sort_values(sort_col, ascending=False, na_position='last', kind='stable')
    # 정렬 및 검색해도 최초 TOP200 거래대금 순위는 그대로 보존한다.
    cols = ['순위', 'name', 'ticker', 'market', 'close', '거래대금(억)', '수급 기준일', '확인상태',
            '외국인 순매수(억)', '기관 순매수(억)', '개인 순매수(억)', '수급 합계(억)', '외국인 강도(%)',
            '기관 강도(%)', '수급강도(%)', '수급 분류']
    st.dataframe(frame[cols], hide_index=True, use_container_width=True,
                 column_config={'name': '종목명', 'ticker': '종목코드', 'market': '시장', 'close': '종가'})
    st.download_button('📥 필터 결과 TOP200 수급 CSV', frame[cols].to_csv(index=False).encode('utf-8-sig'),
                       'miner_flow_top200.csv', mime='text/csv', key='miner_top200_csv')
    st.caption('표본 바깥 종목은 표시하지 않습니다. 상대강도(RS)·DI·ADX·실적 필터는 아직 연결되지 않았으므로 매수 후보 확정 지표로 사용하지 않습니다.')
