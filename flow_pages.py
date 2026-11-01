"""광부 투자터미널: 검증된 거래대금 TOP200 + 별도 자동 수집 외국인/기관 금액."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from flow_signals import summarize_snapshot, merge_history, rolling_strength, valid_history

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
RANK_FILE = ROOT / 'data' / 'kr_flow.json'
FLOW_FILE = ROOT / 'data' / 'kr_investor_flow.json'


@st.cache_data(ttl=120, show_spinner=False)
def load_top():
    obj = json.loads(RANK_FILE.read_text(encoding='utf-8'))
    if obj.get('status') != 'verified' or not obj.get('date'):
        raise ValueError('검증된 TOP200 거래 기준일이 없습니다. 수집 작업을 점검하세요.')
    df = pd.DataFrame(obj.get('top200') or [])
    required = {'ticker', 'name', 'market', 'traded_krw', 'close'}
    if len(df) != 200 or not required.issubset(df.columns):
        raise ValueError('TOP200 개수 또는 필수 컬럼이 맞지 않습니다.')
    df['ticker'] = df['ticker'].astype(str).str.zfill(6)
    if df['ticker'].duplicated().any():
        raise ValueError('TOP200 종목코드 중복')
    df['traded_krw'] = pd.to_numeric(df['traded_krw'], errors='coerce')
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
        return {}, '외국인·기관 자동 수집 파일이 아직 없습니다. GitHub Actions에서 Collect verified TOP200 investor flows를 실행하세요.', None
    codes = df['ticker'].tolist()
    expected = hashlib.sha256((meta['date'] + '|' + ','.join(codes)).encode('utf-8')).hexdigest()
    if flow.get('date') != meta['date'] or flow.get('fingerprint') != expected:
        return {}, '수급 파일과 거래대금 TOP200의 거래일/종목 구성이 다릅니다. 수급을 표시하지 않습니다.', flow
    if not isinstance(flow.get('rows'), dict):
        return {}, '수급 파일 형식 오류: rows가 객체가 아닙니다.', flow
    return flow['rows'], None, flow


def prepare():
    try:
        frame, meta = load_top()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        st.error(f'TOP200 원자료 오류: {exc}')
        return None
    st.caption(f'거래대금: {meta.get("source", "미확인")} · 거래 기준일 {meta["date"]} · 검증 완료 (확정 EOD)')
    records, issue, flow = get_snapshot(frame, meta)
    if issue:
        st.warning(issue)
    elif flow:
        st.caption(f'수급: {flow.get("source", "매동 공개 API")} · 수집시각 {flow.get("collected_at_kst", "-")}')
        st.caption(f'조회 {len(flow.get("attempted_codes") or [])}/200종목 · 금액 확인 {flow.get("published_codes", 0)}종목 · 외국인·기관 모두 확인 {flow.get("complete_codes", 0)}종목')
        if flow.get('errors'):
            with st.expander(f'API 조회 실패 {len(flow["errors"])}건'):
                for x in flow['errors'][:50]:
                    st.text(str(x)[:180])
    for key, label in [
        ('foreign_net_krw', '외국인 순매수(억)'),
        ('institution_net_krw', '기관 순매수(억)'),
        ('individual_net_krw', '개인 순매수(억)')
    ]:
        frame[label] = frame['ticker'].map(
            lambda code: (records.get(code) or {}).get(key)
        )
        frame[label] = pd.to_numeric(frame[label], errors='coerce') / 100_000_000

    frame['수급 기준일'] = frame['ticker'].map(
        lambda code: (records.get(code) or {}).get('date')
    )
    same_date = frame['수급 기준일'].eq(meta['date'])
    money_cols = ['외국인 순매수(억)', '기관 순매수(억)', '개인 순매수(억)']
    frame[money_cols] = frame[money_cols].where(same_date, other=float('nan'))
    frame['수급 합계(억)'] = frame[money_cols[:2]].sum(axis=1, min_count=2)
    frame['거래대금(억)'] = frame['traded_krw'] / 100_000_000
    frame['수급강도(%)'] = (frame['수급 합계(억)'] / frame['거래대금(억)'] * 100).where(frame['거래대금(억)'] > 0)
    frame['확인상태'] = '미수집'
    partial = frame[money_cols[:2]].notna().any(axis=1)
    complete = frame[money_cols[:2]].notna().all(axis=1)
    frame.loc[partial, '확인상태'] = '일부 확인'
    frame.loc[complete, '확인상태'] = '확인'
    frame['외국인 강도(%)'] = (frame['외국인 순매수(억)'] / frame['거래대금(억)'] * 100).where(frame['거래대금(억)'] > 0)
    frame['기관 강도(%)'] = (frame['기관 순매수(억)'] / frame['거래대금(억)'] * 100).where(frame['거래대금(억)'] > 0)
    frame['수급 분류'] = '미확인'
    f = frame['외국인 순매수(억)']
    i = frame['기관 순매수(억)']
    frame.loc[complete, '수급 분류'] = '혼조/보합'
    frame.loc[complete & (f > 0) & (i > 0), '수급 분류'] = '동반 순매수'
    frame.loc[complete & (f < 0) & (i < 0), '수급 분류'] = '동반 순매도'
    for x in ['외국인 강도(%)', '기관 강도(%)']:
        frame[x] = frame[x].round(2)
    for x in money_cols + ['수급 합계(억)', '수급강도(%)', '거래대금(억)']:
        frame[x] = frame[x].round(2)
    return frame



def _as_100m(value):
    return '자료 없음' if value is None else f'{value / 100_000_000:+,.1f}억'


def show_flow_signals(meta, market='ALL'):
    """시장 전체 지표가 아닌 '거래대금 TOP200 표본'의 수급 요약."""
    flow = load_flow()
    if flow is None:
        st.info('수급강도는 아직 데이터 수집 전입니다. 기존 TOP200 거래대금 표시는 유지됩니다.')
        return
    try:
        summary = summarize_snapshot(meta, flow)
    except (ValueError, KeyError, TypeError) as exc:
        st.warning(f'수급강도 계산 보류: {exc}')
        return

    m = summary['metrics'][market]
    st.markdown('### 💰 수급강도 · 매수 확산도')
    st.caption(f"거래 기준일 {summary['date']} · KOSPI·KOSDAQ 전체가 아닌 거래대금 TOP200 중 {market} 표본 · 외국인+기관 순매수 금액 기준")
    if m['paired_count'] == 0:
        st.warning('해당 시장의 외국인·기관 순매수 금액이 확인되지 않았습니다.')
        return
    if m['coverage_pct'] < 95 or m['turnover_coverage_pct'] < 98:
        st.warning(f"금액 데이터가 일부 누락됨: {m['paired_count']}/{m['target_count']}종목, 거래대금 포괄 {m['turnover_coverage_pct']:.1f}%. 현재 확인된 표본만 계산하며 추세 판정에서는 제외합니다.")

    cols = st.columns(4)
    cols[0].metric('외국인 순매수', _as_100m(m['foreign_net_krw']))
    cols[1].metric('기관 순매수', _as_100m(m['institution_net_krw']))
    cols[2].metric('합산 수급강도', f"{m['joint_strength_pct']:+.2f}%")
    cols[3].metric('동반 매수 / 매도', f"{m['both_buy_count']} / {m['both_sell_count']}종목")
    st.caption(f"확산도 {(m['diffusion_pct']):+.1f}%p = (외국인·기관 동반 순매수 {m['both_buy_count']}종목 − 동반 순매도 {m['both_sell_count']}종목) ÷ 수급 확인 {m['paired_count']}종목 × 100. 합산 강도는 확인 종목 순매수 금액 합계 ÷ 동일 종목 거래대금 합계 × 100.")

    chart = go.Figure()
    chart.add_bar(x=['외국인', '기관', '합산'],
                  y=[m['foreign_strength_pct'], m['institution_strength_pct'], m['joint_strength_pct']],
                  marker_color=['#57badd', '#efb96a', '#8bcfa7'])
    chart.add_hline(y=0, line_color='#8b9caa', line_width=1)
    chart.update_layout(height=240, margin=dict(l=10, r=10, t=12, b=10),
                        yaxis_title='순매수 / 거래대금 (%)',
                        paper_bgcolor='#101a28', plot_bgcolor='#101a28',
                        font=dict(color='#e5edf6'))
    st.plotly_chart(chart, use_container_width=True)
    if m['joint_strength_pct'] > 0 and m['diffusion_pct'] < 0:
        st.info('⚖️ 금액은 순매수인데 동반 순매도 종목이 더 많습니다. 일부 대형주 매수 집중 가능성에 유의하세요.')
    elif m['joint_strength_pct'] < 0 and m['diffusion_pct'] > 0:
        st.info('⚖️ 다수 종목으로 매수세가 퍼지더라도 큰 종목에서 자금 유출이 더 클 수 있습니다.')

    # 저장된 날짜별 검증 집계만 추세를 구성. 부족하면 숫자를 채우지 않음.
    history = merge_history(flow.get('history'), summary)
    valid = valid_history(history, market)
    o5 = rolling_strength(history, market, 5)
    o20 = rolling_strength(history, market, 20)
    st.markdown('#### 5·20회 수급 오실레이터')
    s5, s20 = st.columns(2)
    s5.metric('최근 5개 유효 수집일', f"{o5['pct']:+.2f}%" if o5 else '자료 축적 중')
    s20.metric('최근 20개 유효 수집일', f"{o20['pct']:+.2f}%" if o20 else '자료 축적 중')
    if o5 and o20:
        st.caption(f"단기-중기 수급강도 차이: {o5['pct'] - o20['pct']:+.2f}%p. 매매 신호가 아닌 현금 흐름의 관찰치입니다.")
    else:
        st.caption(f"현재 품질 검증을 통과한 수집일 {len(valid)}개. 5개·20개가 모일 때까지 오실레이터를 임의 계산하지 않습니다. 날짜가 빠진 경우 연속 거래일 지표가 아닐 수 있습니다.")
    if len(valid) >= 5:
        dates, v5, v20 = [], [], []
        for k in range(5, len(valid) + 1):
            segment = valid[:k]
            dates.append(segment[-1]['date'])
            x5 = rolling_strength(segment, market, 5)
            x20 = rolling_strength(segment, market, 20)
            v5.append(x5['pct'] if x5 else None)
            v20.append(x20['pct'] if x20 else None)
        trend = go.Figure()
        trend.add_scatter(x=dates, y=v5, mode='lines+markers', name='5개 유효일', line=dict(color='#70cbe0'))
        if any(v is not None for v in v20):
            trend.add_scatter(x=dates, y=v20, mode='lines+markers', name='20개 유효일', line=dict(color='#f4bd62'))
        trend.add_hline(y=0, line_color='#8b9caa', line_width=1)
        trend.update_layout(height=285, margin=dict(l=10,r=10,t=15,b=10),
                            yaxis_title='합산 수급강도 (%)', paper_bgcolor='#101a28',
                            plot_bgcolor='#101a28', font=dict(color='#e5edf6'))
        st.plotly_chart(trend, use_container_width=True)
    st.caption('표본은 매일 거래대금 TOP200에 따라 달라집니다. 원자료: 매동 순매수 금액 및 한국주식데이터 종가/거래대금. 전체 시장 KRX 공식 매매동향과 동일하지 않습니다.')


def cashflow():
    st.title('💸 자금 흐름 | 외국인·기관 순매수 금액')
    frame = prepare()
    if frame is None:
        return
    market = st.selectbox('시장', ['전체', 'KOSPI', 'KOSDAQ'], key='cashmarket')
    if market != '전체':
        frame = frame[frame['market'].eq(market)]
    try:
        meta = json.loads(RANK_FILE.read_text(encoding='utf-8'))
        show_flow_signals(meta, 'ALL' if market == '전체' else market)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        st.warning(f'수급 요약판 보류: {exc}')
    st.caption('종목별 순매수 금액(억원)만 표시. 미수집은 빈칸, 실제 0원은 0으로 구분합니다.')
    cols = ['순위', 'name', '수급 기준일', '확인상태', '외국인 순매수(억)', '기관 순매수(억)', '개인 순매수(억)', '수급 합계(억)']
    st.dataframe(frame[cols], hide_index=True, use_container_width=True, column_config={'name': '종목명'})
    paired = frame.dropna(subset=['외국인 순매수(억)', '기관 순매수(억)']).head(20)
    if not paired.empty:
        fig = go.Figure()
        fig.add_bar(name='외국인', x=paired['name'], y=paired['외국인 순매수(억)'])
        fig.add_bar(name='기관', x=paired['name'], y=paired['기관 순매수(억)'])
        fig.update_layout(barmode='relative', height=350, yaxis_title='억원')
        st.plotly_chart(fig, use_container_width=True)
    st.download_button('📥 투자자별 수급 CSV', frame[cols].to_csv(index=False).encode('utf-8-sig'), 'miner_cashflow.csv', mime='text/csv')


def top200():
    st.title('📊 TOP 200 | 거래대금 순위 · 투자자별 순매수')
    frame = prepare()
    if frame is None:
        return
    market = st.selectbox('시장', ['전체', 'KOSPI', 'KOSDAQ'], key='topmarket')
    if market != '전체':
        frame = frame[frame['market'].eq(market)]
    try:
        meta = json.loads(RANK_FILE.read_text(encoding='utf-8'))
        show_flow_signals(meta, 'ALL' if market == '전체' else market)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        st.warning(f'수급 요약판 보류: {exc}')
    term = st.text_input('종목명 또는 종목코드 검색').strip()
    if term:
        frame = frame[frame['name'].str.contains(term, case=False, regex=False, na=False) |
                      frame['ticker'].str.contains(term, regex=False, na=False)]
    cols = ['순위', 'name', 'ticker', 'market', 'close', '거래대금(억)',
            '수급 기준일', '확인상태', '외국인 순매수(억)', '기관 순매수(억)',
            '개인 순매수(억)', '수급 합계(억)', '외국인 강도(%)',
            '기관 강도(%)', '수급강도(%)', '수급 분류']
    sort_choice = st.selectbox('정렬', ['거래대금 순위', '합산 수급강도', '외국인 순매수', '기관 순매수'], key='miner_flow_sort')
    sort_col = {'합산 수급강도': '수급강도(%)', '외국인 순매수': '외국인 순매수(억)',
                '기관 순매수': '기관 순매수(억)'}.get(sort_choice)
    if sort_col:
        frame = frame.sort_values(sort_col, ascending=False, na_position='last', kind='stable')
    st.dataframe(frame[cols], hide_index=True, use_container_width=True,
                 column_config={'name': '종목명', 'ticker': '종목코드', 'market': '시장', 'close': '종가'})
    st.caption('검색해도 원래 거래대금 TOP200 순위는 유지합니다. 외국인·기관 모두 게시되고 날짜가 같은 경우에만 수급강도를 표시합니다.')
    st.download_button('📥 TOP 200 수급 CSV', frame[cols].to_csv(index=False).encode('utf-8-sig'), 'miner_flow_top200.csv', mime='text/csv')
