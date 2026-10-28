import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scripts.snapshot_panel import show_cloud_snapshot
from pathlib import Path
import json
import re
st.title('⛏️ 광부 투자터미널 · 종합상황판')
st.caption('클라우드 수집 종가 스냅샷과 Yahoo 차트 조회 | 실시간 시세가 아닙니다')
st.divider()
st.subheader('시장 상세 조회 · Yahoo Finance')
MARKETS = {'코스피':'^KS11','코스닥':'^KQ11','S&P500':'^GSPC','나스닥':'^IXIC','원/달러':'KRW=X','미국 10년 국채 수익률':'^TNX','VIX':'^VIX','WTI 선물':'CL=F','Brent 선물':'BZ=F'}
ETFS = {'KODEX 200':'069500.KS','TIGER 200':'102110.KS','KODEX 반도체':'091160.KS','TIGER 반도체':'091230.KS','KODEX 2차전지산업':'305720.KS','KODEX 은행':'091170.KS'}

@st.cache_data(ttl=900)
def load(ticker):
    df=yf.download(ticker,period='2y',auto_adjust=False,progress=False,threads=False)
    if df.empty: raise ValueError('시세 데이터가 없습니다')
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    return df.sort_index()

def price(df): return pd.to_numeric(df['Close'],errors='coerce').dropna()

def osc(df):
    p=price(df); v=pd.to_numeric(df['Volume'],errors='coerce').reindex(p.index)
    traded=p*v; base=traded.rolling(20,min_periods=20).mean()
    relative=100*(traded/base.replace(0,np.nan)-1)
    return relative.ewm(span=5,adjust=False).mean()-relative.ewm(span=20,adjust=False).mean()

def graph(series,title,zero=False):
    f=go.Figure(go.Scatter(x=series.index,y=series,mode='lines',name=title))
    if zero:f.add_hline(y=0,line_dash='dot')
    f.update_layout(height=300,title=title,margin=dict(l=10,r=10,t=35,b=10))
    st.plotly_chart(f,use_container_width=True)

# FDR provides a wider Korean stock-name directory; local TOP200 provides an offline fallback.
@st.cache_data(ttl=86400,show_spinner=False)
def stock_directory():
    names={
        '삼성전자':('005930','KOSPI'),'SK하이닉스':('000660','KOSPI'),
        '삼성전기':('009150','KOSPI'),'삼성전자우':('005935','KOSPI'),
        '현대차':('005380','KOSPI'),'NAVER':('035420','KOSPI'),
        '카카오':('035720','KOSPI'),'LG에너지솔루션':('373220','KOSPI'),
    }
    # A saved Cloud TOP200 list remains usable if a listing source is unavailable.
    snapshot=Path(__file__).resolve().parents[1]/'data'/'kr_flow.json'
    if snapshot.exists():
        try:
            for item in json.loads(snapshot.read_text(encoding='utf-8')).get('top200',[]):
                code=str(item.get('ticker','')).zfill(6)
                name=str(item.get('name','')).strip()
                market=str(item.get('market','')).upper()
                if name and re.fullmatch(r'\d{6}',code) and market in ('KOSPI','KOSDAQ'):
                    names[name]=(code,market)
        except (ValueError,OSError,TypeError): pass
    source='TOP 200 저장 목록 + 기본 종목'
    try:
        import FinanceDataReader as fdr
        listing=fdr.StockListing('KRX')
        if listing is not None and not listing.empty and {'Code','Name'}.issubset(listing.columns):
            added=0
            for _, row in listing.iterrows():
                name=str(row['Name']).strip()
                code=str(row['Code']).strip().zfill(6)
                market=str(row.get('Market',row.get('MarketId',''))).upper()
                if market in ('KOSPI','STK','KS'): market='KOSPI'
                elif market in ('KOSDAQ','KSQ','KQ'): market='KOSDAQ'
                else: continue
                if name and re.fullmatch(r'\d{6}',code):
                    names[name]=(code,market)
                    added+=1
            if added>100: source='KRX 종목 목록 (FinanceDataReader)'
    except Exception:
        pass
    return names,source

if st.button('🔄 Yahoo 차트 데이터 새로 조회'):
    load.clear();st.rerun()
a,b,c,d=st.tabs(['🌎 시장 종합','🛢️ 유가','📦 ETF 거래활동','🔎 개별 종목'])
with a:
    cols=st.columns(3)
    for i,(name,ticker) in enumerate(MARKETS.items()):
        with cols[i%3]:
            try:
                p=price(load(ticker));delta=100*(p.iloc[-1]/p.iloc[-2]-1)
                st.metric(name,f'{p.iloc[-1]:,.2f}',f'{delta:+.2f}%')
                st.caption(f'기준일 {p.index[-1]:%Y-%m-%d} · Yahoo')
            except Exception as e:st.warning(f'{name} 조회 실패: {e}')
    st.info('시장 Breadth와 투자자별 현물·선물 수급은 국내 종목별 과거 자료 연결 후 추가합니다.')
with b:
    l,r=st.columns(2)
    for col,name,ticker in [(l,'WTI','CL=F'),(r,'Brent','BZ=F')]:
        with col:
            try:
                p=price(load(ticker));st.metric(name+' 선물',f'${p.iloc[-1]:,.2f}')
                f=go.Figure()
                for s,n in [(p,'가격'),(p.rolling(20).mean(),'MA20'),(p.rolling(60).mean(),'MA60')]:f.add_trace(go.Scatter(x=s.index,y=s,name=n))
                f.update_layout(height=340)
                st.plotly_chart(f,use_container_width=True)
                st.caption(f'{p.index[-1]:%Y-%m-%d} · 선물 시세는 현물유가와 다름')
            except Exception as e:st.warning(f'{name} 조회 실패: {e}')
with c:
    st.warning('거래대금/거래활동 오실레이터는 ETF 설정·환매를 통한 실제 자금 순유입이 아닙니다.')
    name=st.selectbox('국내 ETF',list(ETFS))
    try:
        df=load(ETFS[name]);p=price(df);o=osc(df).dropna();l,r=st.columns(2)
        with l:graph(p.tail(252),'ETF 가격')
        with r:graph(o.tail(252),'거래활동 오실레이터',True)
        st.caption(f'가격 기준일 {p.index[-1]:%Y-%m-%d}; 거래활동 OSC = 거래대금의 20일 평균 대비 변화율에 대한 EMA5-EMA20 차이')
    except Exception as e:st.error(f'ETF 조회 실패: {e}')
    st.info('ETF 실제 자금 흐름 OSC는 설정·환매/상장좌수 변동의 시계열 공급처 확보 후 제공 예정입니다.')
with d:
    directory, source = stock_directory()
    query=st.text_input('종목명 또는 티커 검색',value='삼성전자',placeholder='예: 삼성전자, 하이닉스, 005930, NVDA').strip()
    ticker=None
    if re.fullmatch(r'\d{6}',query):
        # The exchange of an unlisted 6-digit input cannot be known in advance.
        exchange=st.selectbox('거래 시장', ['KOSPI','KOSDAQ'],index=0)
        ticker=query+('.KS' if exchange=='KOSPI' else '.KQ')
    elif re.fullmatch(r'[A-Za-z][A-Za-z0-9.\-^=]{0,24}',query) and query.upper() not in {n.upper() for n in directory}:
        ticker=query.upper()
    elif query:
        matches=[(n,code,market) for n,(code,market) in directory.items() if query.casefold() in n.casefold()]
        matches.sort(key=lambda x:(x[0].casefold()!=query.casefold(),len(x[0]),x[0]))
        if matches:
            choices=matches[:60]
            selected=st.selectbox('검색 결과에서 종목 선택',range(len(choices)),format_func=lambda i:f'{choices[i][0]} · {choices[i][1]} · {choices[i][2]}')
            name,code,market=choices[selected]
            ticker=code+('.KS' if market=='KOSPI' else '.KQ')
        else:
            st.warning('해당 이름을 찾지 못했습니다. 종목코드 6자리나 Yahoo 티커를 입력해 주세요.')
    st.caption(f'검색 목록: {source} · 선택 티커: {ticker or "없음"} · 시세: Yahoo Finance (지연 가능)')
    if ticker:
        try:
            df=load(ticker);p=price(df);o=osc(df).dropna()
            st.metric('최근 종가',f'{p.iloc[-1]:,.2f}',f'{100*(p.iloc[-1]/p.iloc[-2]-1):+.2f}%')
            st.caption(f'가격 기준일 {p.index[-1]:%Y-%m-%d}')
            l,r=st.columns(2)
            with l:
                f=go.Figure()
                for s,n in [(p,'종가'),(p.rolling(20).mean(),'MA20'),(p.rolling(60).mean(),'MA60'),(p.rolling(200).mean(),'MA200')]:f.add_trace(go.Scatter(x=s.index,y=s,name=n))
                f.update_layout(height=350)
                st.plotly_chart(f,use_container_width=True)
            with r:graph(o.tail(252),'거래활동 오실레이터',True)
            st.info('외국인·기관 순매수 오실레이터와 TOP 200 수급은 별도 한국거래소 데이터 연결이 필요합니다. 가격/거래량으로 순매수를 추정하지 않습니다.')
        except Exception as e:st.error(f'종목 조회 실패 ({ticker}): {e}')
st.caption('연구용. 자동 조회 제공 여부와 시차는 데이터 공급원 상황에 따라 달라질 수 있습니다.')
st.divider()
with st.expander('📡 클라우드 데이터 수집 현황',expanded=False):
    show_cloud_snapshot()

with st.expander("📡 클라우드 데이터 수집 현황", expanded=False):
    show_cloud_snapshot()
