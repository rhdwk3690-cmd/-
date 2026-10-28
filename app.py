"""광부 투자터미널: sidebar single-navigation entrypoint.
Replace repository root app.py; keep pages/ and fear_greed_engine.py intact.
"""
import os
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from fear_greed_engine import load_us, load_kr, metrics

st.set_page_config(page_title='광부 투자터미널', page_icon='⛏️', layout='wide', initial_sidebar_state='expanded')
st.markdown('''<style>
.block-container{padding-top:1.4rem;max-width:1500px}
[data-testid="stMetric"]{border:1px solid rgba(128,135,150,.25);border-radius:12px;padding:.8rem}
[data-testid="stSidebar"]{border-right:1px solid rgba(128,135,150,.20)}
</style>''',unsafe_allow_html=True)


def placeholder(title, description, next_steps):
    st.title(title)
    st.caption('⛏️ MINER’S TERMINAL | 단계별 기능 개발')
    st.info(description)
    st.subheader('연결 예정 항목')
    for step in next_steps:
        st.write('•', step)
    st.warning('데이터 소스와 수급 원자료가 검증되기 전까지 실제 수급 수치를 만들어 표시하지 않습니다.')


def cashflow():
    placeholder('💸 자금 흐름','외국인·기관·개인 순매수 및 선물·현물 흐름을 연결할 예정입니다.',[
        'KRX 투자자별 순매수 원자료 확보와 기준일 표시',
        '5·20·60일 순매수 누적 및 거래대금 대비 순매수',
        '선물·현물 괴리: 매매대금과 순포지션의 차이 구분'])

def etfs():
    placeholder('📦 ETF 분석','기존 종합 상황판의 ETF 거래활동 오실레이터는 계속 이용할 수 있습니다.',[
        'ETF 설정·환매 / 상장좌수 / NAV 기반 실제 자금 흐름',
        'ETF 투자자별 순매수와 거래활동 신호 분리',
        '섹터 ETF 자금 흐름 및 상대강도 순위'])

def top200():
    placeholder('📊 거래대금 TOP 200','ETF·ETN 제외 한국 주식 거래대금 상위 종목을 분석할 예정입니다.',[
        '당일 거래대금 기준과 최근 20일 평균 기준 각각 산출',
        '외국인·기관별 수급 오실레이터',
        '수급 확산도, 동시순매수, 다이버전스 탐지'])

def individual():
    placeholder('🔎 개별 종목','기존 종합 상황판의 개별 종목 가격·거래활동 분석은 그대로 이용할 수 있습니다.',[
        '종목명 검색과 관심종목',
        '수급·상대강도·실적 및 밸류에이션 분리',
        '수급 전환 신호와 위험관리 백테스트'])

@st.cache_data(ttl=3600, show_spinner='미국 시장 데이터를 불러오는 중입니다...')
def get_us(start):
    return load_us(start=start)

@st.cache_data(show_spinner='한국 엑셀 데이터를 계산하는 중입니다...')
def get_kr(content):
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/'market.xlsx'
        path.write_bytes(content)
        return load_kr(str(path))

def research():
    st.title('🧪 전략 연구실 | Fear & Greed')
    st.caption('기존 인과적 정규화 기반 연구 엔진 사용 · 공식 CNN 공포탐욕 지수 아님')
    with st.sidebar:
        st.divider()
        st.subheader('연구실 설정')
        region=st.radio('데이터 출처',['미국 자동 조회','한국 원본 엑셀'],key='research_region')
        fee=st.slider('편도 거래비용(bp)',0,50,5,step=1)
        days=st.select_slider('표시 기간(거래일)',options=[60,126,252,504,756],value=252)
        if region=='미국 자동 조회':
            start=st.date_input('시작일',value=pd.Timestamp('2020-01-01').date())
            uploaded=None
        else:
            uploaded=st.file_uploader('한국 원본 엑셀',type=['xlsx','xls'])
    if st.button('🔄 데이터 갱신'):
        get_us.clear()
    try:
        if region=='미국 자동 조회':
            results=get_us(str(start))
        else:
            if uploaded is None:
                st.info('한국 원본 모델은 ATM 옵션·VKOSPI·채권 지수 자료가 들어 있는 엑셀 업로드가 필요합니다.')
                return
            results=get_kr(uploaded.getvalue())
    except Exception as exc:
        st.error(f'데이터 수집에 실패했습니다: {exc}')
        return
    market=st.selectbox('분석 지수',list(results.keys()))
    df=results[market].dropna(subset=['fg_score','superma']).copy()
    if len(df)<30:
        st.warning('유효한 분석 데이터가 충분하지 않습니다.')
        return
    prices={'KOSPI':'코스피','KOSDAQ':'코스닥','SP500':'S&P500','NASDAQ':'NASDAQ'}
    pcol=prices[market]
    last=df.iloc[-1]
    m=st.columns(5)
    m[0].metric('기준일',f'{df.index[-1]:%Y-%m-%d}')
    m[1].metric('Fear & Greed',f"{last['fg_score']:.1f}")
    m[2].metric('EMA20',f"{last['fg_ema20']:.1f}")
    m[3].metric('추세','상승' if last['trend_up'] else '약세/횡보')
    m[4].metric('모델 신호','진입/보유' if last['target']==1 else '현금 대기')
    if (pd.Timestamp.now().normalize()-pd.Timestamp(df.index[-1]).normalize()).days>7:
        st.warning('최종 유효 데이터가 7일 이상 지났습니다. 최신 신호로 사용하지 마세요.')
    view=df.tail(days)
    from plotly.subplots import make_subplots
    f=make_subplots(rows=3,cols=1,shared_xaxes=True,row_heights=[.48,.33,.19],vertical_spacing=.05)
    f.add_trace(go.Scatter(x=view.index,y=view[pcol],name='시장 가격'),row=1,col=1)
    f.add_trace(go.Scatter(x=view.index,y=view['ma200'],name='200일선'),row=1,col=1)
    f.add_trace(go.Scatter(x=view.index,y=view['fg_score'],name='F&G'),row=2,col=1)
    f.add_trace(go.Scatter(x=view.index,y=view['fg_ema20'],name='F&G EMA20'),row=2,col=1)
    f.add_trace(go.Bar(x=view.index,y=view['fg_hist']*100,name='F&G 오실레이터 ×100'),row=3,col=1)
    f.update_layout(height=700,legend=dict(orientation='h',y=-.08),hovermode='x unified',margin=dict(l=5,r=5,t=15,b=45))
    st.plotly_chart(f,use_container_width=True)
    st.subheader('전략 vs 매수 후 보유')
    test=df.copy()
    test['position']=test['target'].shift(1).fillna(0)
    test['turnover']=test['position'].diff().abs().fillna(test['position'].abs())
    test['net_return']=test['position']*test['asset_return']-test['turnover']*fee/10000
    test['equity']=(1+test['net_return']).cumprod()
    test['benchmark']=(1+test['asset_return']).cumprod()
    a,b=st.columns([1.5,1])
    with a:
        ch=go.Figure()
        ch.add_trace(go.Scatter(x=test.index,y=test['equity'],name='전략'))
        ch.add_trace(go.Scatter(x=test.index,y=test['benchmark'],name='단순 보유'))
        ch.update_layout(height=320,hovermode='x unified')
        st.plotly_chart(ch,use_container_width=True)
    with b:
        sm=metrics(test,'net_return'); bm=metrics(test,'asset_return')
        for key,label in [('cagr','CAGR'),('mdd','MDD'),('annual_vol','연환산 변동성')]:
            st.write(f"**{label}**: 전략 {sm.get(key,float('nan')):.1%} | 단순 보유 {bm.get(key,float('nan')):.1%}")
        st.caption(f"편도 비용 {fee}bp · 구간 {test.index[0]:%Y-%m-%d} ~ {test.index[-1]:%Y-%m-%d}")
    with st.expander('전체 지표 및 CSV 내보내기'):
        st.dataframe(test.tail(100).sort_index(ascending=False),use_container_width=True)
        st.download_button('CSV 다운로드',test.to_csv(index_label='Date').encode('utf-8-sig'),f'{market}_research.csv','text/csv')
    st.warning('연구용 가상 백테스트입니다. 다음 거래일 수익률 반영, 종가 체결 단순화; 세금·시장충격·슬리피지 미반영. 실전 결과를 보장하지 않습니다.')

from flow_pages import cashflow as cashflow, top200 as top200
pages=[
    st.Page('pages/1_광부_종합상황판.py',title='종합 상황판',icon='🌎',default=True),
    st.Page(cashflow,title='자금 흐름',icon='💸'),
    st.Page(etfs,title='ETF 분석',icon='📦'),
    st.Page(top200,title='TOP 200',icon='📊'),
    st.Page(individual,title='개별 종목',icon='🔎'),
    st.Page('pages/2_계좌방어_리스크레이더.py' if os.path.exists('pages/2_계좌방어_리스크레이더.py') else lambda: placeholder('🛡️ 계좌 방어','계좌 방어 파일을 pages 폴더에 넣으면 활성화됩니다.',['포트폴리오 MDD·집중도·상관관계 분석']),title='계좌 방어',icon='🛡️'),
    st.Page(research,title='전략 연구실',icon='🧪'),
]
nav=st.navigation(pages,position='sidebar',expanded=True)
nav.run()
