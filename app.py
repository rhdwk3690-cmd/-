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
