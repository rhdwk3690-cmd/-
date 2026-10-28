"""KR market EOD money flow and traded-value Top 200 screens."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

FILE = Path(__file__).resolve().parent / 'data' / 'kr_flow.json'


def _read():
    if not FILE.exists():
        st.warning('아직 국내 수급 데이터 파일이 없습니다. GitHub Actions의 Collect KR flows 작업을 먼저 실행해 주세요.')
        return None
    try:
        obj = json.loads(FILE.read_text(encoding='utf-8'))
        st.caption(f"데이터 기준일: {obj.get('date') or '미확인'} | 클라우드 수집: {obj.get('collected_at_kst', '미확인')[:16]} KST | 출처: {obj.get('source', '')}")
        st.info('장 마감 확정 데이터 연구용 화면입니다. 장중 실시간 데이터가 아닙니다. 수집 시각과 거래일을 구분해 확인하세요.')
        if obj.get('status') != 'ok':
            st.error('국내 원자료 확보 실패 또는 일부 누락. 수치를 보완하거나 추정해 표시하지 않습니다.')
        with st.expander('수집 로그 / 데이터 문제'):
            for msg in obj.get('errors', [])[-30:]: st.text(msg)
        return obj
    except Exception as exc:
        st.error(f'데이터 파일을 읽지 못했습니다: {exc}')
        return None


def _won(value):
    if pd.isna(value): return '자료없음'
    return f'{value / 100_000_000:,.1f}억'


def cashflow():
    st.title('💸 자금 흐름 | 현물 확정 순매수')
    obj = _read()
    if obj is None: return
    flows = obj.get('market_flows') or {}
    if not flows:
        st.warning('시장별 투자자 순매수 원자료가 없습니다. KRX 제공 데이터 응답을 확인해야 합니다.')
        return
    tabs = st.tabs(['KOSPI', 'KOSDAQ'])
    for tab, market in zip(tabs, ['KOSPI', 'KOSDAQ']):
        with tab:
            df = pd.DataFrame(flows.get(market, []))
            if df.empty:
                st.warning(f'{market} 수급 조회 실패')
                continue
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').drop_duplicates('date')
            latest = df.iloc[-1]
            cols = st.columns(3)
            for col, label, field in zip(cols, ['외국인', '기관합계', '개인'], ['foreign_krw', 'institution_krw', 'individual_krw']):
                col.metric(label + ' 순매수', _won(latest[field]))
            f = go.Figure()
            for field, label in [('foreign_krw', '외국인'), ('institution_krw', '기관'), ('individual_krw', '개인')]:
                f.add_trace(go.Bar(x=df['date'], y=df[field] / 100_000_000, name=label))
            f.update_layout(barmode='relative', height=340, yaxis_title='억원', margin=dict(l=0,r=0,t=20,b=0))
            st.plotly_chart(f, use_container_width=True)
            st.subheader('외국인·기관 누적 순매수')
            f2 = go.Figure()
            for field, label in [('foreign_krw','외국인'), ('institution_krw','기관')]:
                f2.add_trace(go.Scatter(x=df['date'], y=df[field].cumsum() / 100_000_000, name=label))
            f2.update_layout(height=290, yaxis_title='억원', margin=dict(l=0,r=0,t=20,b=0))
            st.plotly_chart(f2, use_container_width=True)
            st.caption('조회된 날짜 범위 내 누적치입니다. 선물 포지션과 ETF 설정·환매는 포함되지 않습니다.')


def top200():
    st.title('📊 거래대금 TOP 200 | 국내 주식')
    obj = _read()
    if obj is None: return
    df = pd.DataFrame(obj.get('top200') or [])
    if df.empty:
        st.warning('전종목 데이터가 아직 확보되지 않았습니다.')
        return
    if len(df) != 200:
        st.warning(f'현재 {len(df)}개만 조회되었습니다. 완전한 TOP 200이 아닙니다.')
    market = st.selectbox('시장', ['전체','KOSPI','KOSDAQ'])
    if market != '전체': df = df[df['market'] == market].copy()
    term = st.text_input('종목명 / 종목코드 검색', '')
    if term: df = df[df['name'].str.contains(term, case=False, regex=False, na=False) | df['ticker'].str.contains(term, regex=False)]
    df['거래대금(억)'] = (df['traded_krw'] / 100_000_000).round(1)
    df['외국인 순매수(억)'] = (pd.to_numeric(df['foreign_net_krw'], errors='coerce') / 100_000_000).round(1)
    df['기관 순매수(억)'] = (pd.to_numeric(df['institution_net_krw'], errors='coerce') / 100_000_000).round(1)
    df['수급 합계(억)'] = df['외국인 순매수(억)'] + df['기관 순매수(억)']
    df.insert(0, '순위', range(1, len(df)+1)) if market == '전체' and not term else None
    cols = ['순위'] if '순위' in df else []
    cols += ['name','ticker','market','close','거래대금(억)','외국인 순매수(억)','기관 순매수(억)','수급 합계(억)']
    st.dataframe(df[cols], use_container_width=True, hide_index=True,
                 column_config={'name':'종목명','ticker':'종목코드','market':'시장','close':'종가'})
    st.caption('시장별 보통주·우선주 등 주식 시세 기준. ETF·ETN을 제외한 종목 집합이며, 외국인/기관 데이터 부재는 빈칸으로 처리합니다.')
    st.download_button('TOP 200 CSV 저장', df[cols].to_csv(index=False).encode('utf-8-sig'), 'kr_top200.csv', 'text/csv')
