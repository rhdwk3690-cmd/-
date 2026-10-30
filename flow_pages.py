"""광부 투자터미널: 검증된 거래대금 TOP200 + 별도 자동 수집 외국인/기관 금액."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
    for x in money_cols + ['수급 합계(억)', '수급강도(%)', '거래대금(억)']:
        frame[x] = frame[x].round(2)
    return frame


def cashflow():
    st.title('💸 자금 흐름 | 외국인·기관 순매수 금액')
    frame = prepare()
    if frame is None:
        return
    market = st.selectbox('시장', ['전체', 'KOSPI', 'KOSDAQ'], key='cashmarket')
    if market != '전체':
        frame = frame[frame['market'].eq(market)]
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
    term = st.text_input('종목명 또는 종목코드 검색').strip()
    if term:
        frame = frame[frame['name'].str.contains(term, case=False, regex=False, na=False) |
                      frame['ticker'].str.contains(term, regex=False, na=False)]
    cols = ['순위', 'name', 'ticker', 'market', 'close', '거래대금(억)',
            '수급 기준일', '확인상태', '외국인 순매수(억)', '기관 순매수(억)',
            '개인 순매수(억)', '수급 합계(억)', '수급강도(%)']
    st.dataframe(frame[cols], hide_index=True, use_container_width=True,
                 column_config={'name': '종목명', 'ticker': '종목코드', 'market': '시장', 'close': '종가'})
    st.caption('검색해도 원래 거래대금 TOP200 순위는 유지합니다. 외국인·기관 모두 게시되고 날짜가 같은 경우에만 수급강도를 표시합니다.')
    st.download_button('📥 TOP 200 수급 CSV', frame[cols].to_csv(index=False).encode('utf-8-sig'), 'miner_flow_top200.csv', mime='text/csv')
