"""Individual stock study: verified source dates, trend and RS; not trade advice."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

ROOT = Path(__file__).resolve().parent

@st.cache_data(ttl=900, show_spinner=False)
def history(symbol: str):
    df = yf.download(symbol, period='1y', interval='1d', auto_adjust=True,
                     progress=False, threads=False)
    if df is None or df.empty:
        raise ValueError(f'{symbol}: 가격 이력이 없습니다')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    needed = {'High','Low','Close'}
    if not needed.issubset(df.columns):
        raise ValueError(f'{symbol}: OHLC 누락')
    df = df[['High','Low','Close']].apply(pd.to_numeric, errors='coerce').dropna()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df = df.loc[~df.index.duplicated(keep='last')].sort_index()
    if len(df)<90:
        raise ValueError(f'{symbol}: DI·ADX·RS 분석 이력 부족 ({len(df)}거래일)')
    return df


def dmi_snapshot(prices, period=14):
    high, low, close = prices['High'], prices['Low'], prices['Close']
    rise, fall = high.diff(), -low.diff()
    positive = rise.where((rise>fall)&(rise>0),0.0)
    negative = fall.where((fall>rise)&(fall>0),0.0)
    tr = pd.concat([high-low,(high-close.shift()).abs(),
                    (low-close.shift()).abs()],axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period,adjust=False,min_periods=period).mean()
    plus = 100*positive.ewm(alpha=1/period,adjust=False,min_periods=period).mean()/atr.replace(0,np.nan)
    minus = 100*negative.ewm(alpha=1/period,adjust=False,min_periods=period).mean()/atr.replace(0,np.nan)
    dx = 100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    adx = dx.ewm(alpha=1/period,adjust=False,min_periods=period).mean()
    last = {'plus_di':plus.iloc[-1],'minus_di':minus.iloc[-1],
            'adx':adx.iloc[-1],'atr_pct':atr.iloc[-1]/close.iloc[-1]*100}
    if any(pd.isna(v) for v in last.values()):
        raise ValueError('DMI/ATR 계산에 필요한 유효 데이터가 부족합니다')
    return {key:float(value) for key,value in last.items()}


def render():
    st.title('🔎 종목분석 | 가치 × 수급 × 추세')
    st.caption('실적·리포트·수급·추세를 연결하는 종목 연구 공간. 현재는 검증된 수급과 DMI/ADX/ATR·RS부터 제공')
    rank = json.loads((ROOT/'data'/'kr_flow.json').read_text(encoding='utf-8'))
    if rank.get('status') != 'verified' or not isinstance(rank.get('top200'),list):
        st.warning('종목 목록의 확정 데이터가 없습니다.')
        return
    stocks = rank['top200']
    options = {f"{x['name']} · {x['ticker']} ({x['market']})":x for x in stocks
               if x.get('ticker') and x.get('market') in ('KOSPI','KOSDAQ')}
    if not options:
        st.warning('종목 목록이 비었습니다.');return
    name = st.selectbox('거래대금 TOP200 종목 검색', list(options), key='miner_study_stock')
    row = options[name]
    code, market = row['ticker'], row['market']
    benchmark = '^KS11' if market=='KOSPI' else '^KQ11'
    symbol = code+('.KS' if market=='KOSPI' else '.KQ')
    asof = rank['date']
    st.caption(f"KRX 기준일 {asof} · 거래대금 순위 {stocks.index(row)+1}위 · 당일 자료 아닐 수 있음")
    cols = st.columns(3)
    cols[0].metric('KRX 거래대금',f"{row['traded_krw']/1e8:,.0f}억")
    cols[1].metric('KRX 확정 종가',f"{row['close']:,.0f}원")
    cols[2].metric('시장',market)
    flows = ROOT/'data'/'kr_investor_flow.json'
    if flows.exists():
        try:
            f=json.loads(flows.read_text(encoding='utf-8'))
            if f.get('date')==asof:
                record=(f.get('rows') or {}).get(code)
                if record and record.get('date')==asof:
                    st.markdown('#### 매동 종목별 투자자 순매수 (공식 KRX 직접연결 아님)')
                    cols=st.columns(3)
                    for c,key,label in zip(cols,['foreign_net_krw','institution_net_krw','individual_net_krw'],['외국인','기관','개인']):
                        v=record.get(key)
                        c.metric(label,f'{v/1e8:+,.1f}억' if type(v) is int else '자료 없음')
        except (OSError, ValueError, TypeError, KeyError):
            st.caption('수급 파일을 검증할 수 없습니다.')
    st.caption('종목별 투자자 순매수는 기존 매동 공개 API 자료입니다. KRX 공식 종목별 상세 수급 및 NXT 수급은 미연결입니다.')
    st.markdown('#### 추세 · 상대강도 (일봉)')
    try:
        stock = history(symbol)
        index = history(benchmark)
        dmi = dmi_snapshot(stock)
        st.caption(f'가격일 {stock.index[-1]:%Y-%m-%d} · 지수일 {index.index[-1]:%Y-%m-%d} · 출처 Yahoo Finance (지연 가능)')
        cols=st.columns(4)
        cols[0].metric('+DI',f"{dmi['plus_di']:.1f}")
        cols[1].metric('-DI',f"{dmi['minus_di']:.1f}")
        cols[2].metric('ADX',f"{dmi['adx']:.1f}")
        cols[3].metric('ATR / 주가',f"{dmi['atr_pct']:.2f}%")
        common = stock['Close'].to_frame('stock').join(index['Close'].to_frame('index'),how='inner').dropna()
        if len(common)>=61:
            dstock = common['stock'].iloc[-1]/common['stock'].iloc[-61]-1
            dindex = common['index'].iloc[-1]/common['index'].iloc[-61]-1
            st.metric('60거래일 상대수익률(RS)',f'{(dstock-dindex)*100:+.2f}%p')
            st.caption('RS = 종목 60거래일 수익률 − 비교지수 60거래일 수익률. DI/ADX와 결합해도 매수 신호로 검증된 것은 아닙니다.')
        else:
            st.info('RS 비교를 위한 공통 거래일이 부족합니다.')
        st.line_chart(stock['Close'].tail(120),height=250)
    except (ValueError, KeyError, TypeError) as exc:
        st.warning(f'추세 데이터가 아직 준비되지 않았습니다: {exc}')
    except Exception as exc:
        st.warning(f'외부 가격 데이터 수집 오류: {type(exc).__name__}')
    with st.expander('📄 실적·증권사 리포트 연결 계획'):
        st.info('OpenDART 분기 성장률·영업이익률, 리포트 목표주가 변화를 검증된 출처와 발표일 기준으로 연결할 예정입니다. 아직 자동 수집·리포트 평가 기능은 활성화되지 않았습니다.')
