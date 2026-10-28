"""광부 투자터미널: 계좌 방어 레이더 / 종목명 검색 지원."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.title('🛡️ 광부 투자터미널 | 계좌 방어 레이더')
st.caption('실제 계좌가 아닌, 입력한 종목·비중에 대한 과거 위험 분석입니다.')

KNOWN = {
    '삼성전자': '005930.KS', '삼성전자우': '005935.KS',
    'SK하이닉스': '000660.KS', '하이닉스': '000660.KS',
    '삼성전기': '009150.KS', '두산': '000150.KS',
    '네이버': '035420.KS', 'NAVER': '035420.KS',
    '현대차': '005380.KS', '기아': '000270.KS',
    'LG에너지솔루션': '373220.KS', '현금': 'CASH', 'CASH': 'CASH',
}

def normalize(value):
    return re.sub(r'\s+', '', str(value).strip()).casefold()

@st.cache_data(ttl=3600)
def stock_catalog():
    catalog = {normalize(name): {(name, ticker)} for name, ticker in KNOWN.items()}
    code_map = {}
    file = Path(__file__).resolve().parents[1] / 'data' / 'kr_flow.json'
    if file.exists():
        try:
            for item in json.loads(file.read_text(encoding='utf-8')).get('top200', []):
                code = str(item.get('ticker', '')).zfill(6)
                market = item.get('market')
                name = str(item.get('name', '')).strip()
                if re.fullmatch(r'\d{6}', code) and market in ('KOSPI', 'KOSDAQ') and name:
                    ticker = code + ('.KS' if market == 'KOSPI' else '.KQ')
                    catalog.setdefault(normalize(name), set()).add((name, ticker))
                    code_map[code] = ticker
        except (OSError, ValueError, TypeError):
            pass
    for name, ticker in KNOWN.items():
        if re.fullmatch(r'\d{6}\.(KS|KQ)', ticker):
            code_map.setdefault(ticker[:6], ticker)
    return catalog, code_map

def resolve_stock(raw, catalog, code_map):
    raw = str(raw).strip()
    if not raw:
        return None, '빈 종목명이 있습니다.'
    key = normalize(raw)
    if key in catalog:
        tickers = {ticker for _, ticker in catalog[key]}
        if len(tickers) == 1:
            return next(iter(tickers)), None
        return None, f'{raw}: 같은 이름의 종목이 여러 개입니다. 코드를 입력해 주세요.'
    if re.fullmatch(r'\d{6}\.(KS|KQ)', raw, flags=re.I):
        return raw.upper(), None
    if re.fullmatch(r'\d{6}', raw):
        if raw in code_map:
            return code_map[raw], None
        return None, f'{raw}: 시장 구분이 필요합니다. .KS 또는 .KQ를 붙여 주세요.'
    partial = [(n, t) for name, matches in catalog.items() if key in name for n, t in matches]
    unique = {t for _, t in partial}
    if len(unique) == 1:
        return next(iter(unique)), None
    if partial:
        examples = ', '.join(f'{n} ({t})' for n, t in sorted(set(partial))[:5])
        return None, f'{raw}: 검색 후보가 여러 개입니다. {examples}'
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9.\-]{0,11}', raw):
        return raw.upper(), None
    return None, f'{raw}: 종목명을 찾지 못했습니다. 정확한 종목명 또는 티커로 입력해 주세요.'

DEFAULT = pd.DataFrame([
    {'종목': '삼성전자', '비중(%)': 25.0},
    {'종목': 'SK하이닉스', '비중(%)': 25.0},
    {'종목': '삼성전기', '비중(%)': 25.0},
    {'종목': '두산', '비중(%)': 25.0},
])
st.warning('아래 네 종목과 비중은 예시입니다. 실제 보유 현황으로 수정하세요.')
with st.expander('① 보유 종목과 비중 입력', expanded=True):
    portfolio = st.data_editor(
        DEFAULT, num_rows='dynamic', use_container_width=True, hide_index=True,
        column_config={
            '종목': st.column_config.TextColumn('종목명 또는 티커', required=True),
            '비중(%)': st.column_config.NumberColumn('비중(%)', min_value=0.0, max_value=100.0, step=1.0),
        }, key='portfolio_name_editor_v10')
    a, b, c = st.columns(3)
    with a:
        benchmark = st.selectbox('비교 지수', ['^KS11', '^KQ11', '^GSPC'],
            format_func=lambda x: {'^KS11': 'KOSPI', '^KQ11': 'KOSDAQ', '^GSPC': 'S&P500'}[x])
    with b:
        period = st.selectbox('분석 기간', ['1y', '2y', '3y', '5y'], index=1)
    with c:
        warning_limit = st.slider('경고 낙폭(%)', 5, 40, 15)
    refresh = st.button('🔄 최신 데이터 다시 조회')

@st.cache_data(ttl=3600, show_spinner=False)
def get_prices(ticker, span):
    data = yf.download(ticker, period=span, auto_adjust=True, progress=False, threads=False)
    if data.empty:
        raise ValueError('시세 데이터가 없습니다')
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    prices = pd.to_numeric(data['Close'], errors='coerce').dropna()
    prices.index = pd.DatetimeIndex(prices.index).tz_localize(None).normalize()
    return prices.loc[~prices.index.duplicated(keep='last')].sort_index()

if refresh:
    get_prices.clear()
    stock_catalog.clear()

try:
    df = portfolio.copy()
    df['종목'] = df['종목'].fillna('').astype(str).str.strip()
    df['비중(%)'] = pd.to_numeric(df['비중(%)'], errors='coerce')
    df = df[(df['종목'] != '') & df['비중(%)'].notna() & (df['비중(%)'] > 0)].copy()
    if df.empty:
        st.info('종목과 비중을 입력해 주세요.')
        st.stop()
    catalog, code_map = stock_catalog()
    resolved = [resolve_stock(raw, catalog, code_map) for raw in df['종목']]
    issues = [issue for _, issue in resolved if issue]
    if issues:
        st.error('종목 검색 오류: ' + ' / '.join(issues))
        st.stop()
    df['티커'] = [ticker for ticker, _ in resolved]
    if df['티커'].duplicated().any():
        st.error('같은 종목이 중복 입력되어 있습니다. 한 행으로 합쳐 주세요.')
        st.stop()
    total = float(df['비중(%)'].sum())
    if not np.isclose(total, 100, atol=0.01):
        st.error(f'비중 합계가 {total:.2f}%입니다. 100%로 맞춰 주세요. 현금은 현금 또는 CASH로 입력할 수 있습니다.')
        st.stop()
    st.caption('인식된 종목: ' + ' · '.join(f'{row["종목"]} → {row["티커"]}' for _, row in df.iterrows()))
    tickers = [t for t in df['티커'] if t != 'CASH']
    if not tickers:
        st.info('현금 100% 구성은 주가 위험 분석 대상이 아닙니다.')
        st.stop()
    needed = list(dict.fromkeys(tickers + [benchmark]))
    series, errors = {}, []
    with st.spinner('시세를 조회하고 포트폴리오 위험을 계산합니다…'):
        for ticker in needed:
            try:
                series[ticker] = get_prices(ticker, period)
            except Exception as exc:
                errors.append(f'{ticker}: {exc}')
    if errors:
        st.error('필요한 시세를 일부 조회하지 못해 계산하지 않습니다: ' + '; '.join(errors))
        st.stop()
    prices = pd.concat({t: series[t] for t in needed}, axis=1, join='inner').dropna()
    if len(prices) < 65:
        st.error('공통 거래일이 65일 미만입니다. 분석할 수 없습니다.')
        st.stop()
    returns = prices.pct_change(fill_method=None).dropna()
    weights = df.set_index('티커')['비중(%)'].div(100)
    portfolio_returns = sum(returns[t] * float(weights[t]) for t in tickers)
    curve = (1 + portfolio_returns).cumprod()
    benchmark_curve = (1 + returns[benchmark]).cumprod()
    drawdown = curve / curve.cummax() - 1
    mdd = float(drawdown.min())
    annual_vol = float(portfolio_returns.std() * np.sqrt(252))
    hhi = float((weights ** 2).sum())
    latest_date = prices.index[-1].date()
    age = (pd.Timestamp.now(tz='Asia/Seoul').date() - latest_date).days

    st.subheader('② 포트폴리오 위험 요약')
    k = st.columns(5)
    k[0].metric('시세 기준일', str(latest_date))
    k[1].metric('과거 최대 낙폭 (MDD)', f'{mdd:.1%}')
    k[2].metric('연환산 변동성', f'{annual_vol:.1%}')
    k[3].metric('최대 종목 비중', f'{weights.max():.0%}')
    k[4].metric('집중도 HHI', f'{hhi:.3f}')
    if age > 3:
        st.warning(f'마지막 공통 시세가 {age}일 전입니다. 최신 판단에 사용하지 마세요.')
    if mdd <= -warning_limit / 100:
        st.error('⚠️ 과거 최대 낙폭이 설정한 경고 수준을 넘었습니다.')
    else:
        st.info('관측된 과거 MDD가 경고 이내입니다. 미래 손실 제한을 의미하지는 않습니다.')

    left, right = st.columns(2)
    with left:
        chart = go.Figure()
        chart.add_trace(go.Scatter(x=curve.index, y=curve, name='포트폴리오'))
        chart.add_trace(go.Scatter(x=benchmark_curve.index, y=benchmark_curve, name='비교 지수'))
        chart.update_layout(title='누적 가치 (초기값 1)', height=350)
        st.plotly_chart(chart, use_container_width=True)
    with right:
        chart = go.Figure(go.Scatter(x=drawdown.index, y=drawdown * 100, fill='tozeroy', name='낙폭'))
        chart.add_hline(y=-warning_limit, line_dash='dash', line_color='red')
        chart.update_layout(title='포트폴리오 낙폭 (%)', height=350)
        st.plotly_chart(chart, use_container_width=True)

    st.subheader('③ 종목별 성과 및 동반 하락')
    left, right = st.columns(2)
    with left:
        display = dict(zip(df['티커'], df['종목']))
        rows = []
        for ticker in tickers:
            price = prices[ticker]
            rows.append({
                '종목': display[ticker], '티커': ticker, '비중(%)': float(weights[ticker]) * 100,
                '20거래일(%)': (price.iloc[-1] / price.iloc[-21] - 1) * 100,
                '60거래일(%)': (price.iloc[-1] / price.iloc[-61] - 1) * 100,
                '60일 실현변동성(%)': returns[ticker].tail(60).std() * np.sqrt(252) * 100,
            })
        st.dataframe(pd.DataFrame(rows).round(2), hide_index=True, use_container_width=True)
    with right:
        corr = returns[tickers].tail(60).corr()
        chart = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index,
            zmin=-1, zmax=1, zmid=0, colorscale='RdBu', reversescale=True,
            text=np.round(corr.values, 2), texttemplate='%{text}'))
        chart.update_layout(title='최근 60거래일 수익률 상관관계', height=350)
        st.plotly_chart(chart, use_container_width=True)

    st.subheader('④ 과거 스트레스 구간')
    rolling5 = (1 + portfolio_returns).rolling(5).apply(np.prod, raw=True) - 1
    rolling20 = (1 + portfolio_returns).rolling(20).apply(np.prod, raw=True) - 1
    st.write(f'최악 1일: **{portfolio_returns.min():.2%}** · 최악 5거래일: **{rolling5.min():.2%}** · 최악 20거래일: **{rolling20.min():.2%}**')
    st.download_button('📥 위험 계산 CSV 저장',
        pd.DataFrame({'portfolio_return': portfolio_returns,
            'benchmark_return': returns[benchmark], 'drawdown': drawdown}).to_csv(index_label='Date').encode('utf-8-sig'),
        'miner_portfolio_risk.csv', 'text/csv')
except Exception as exc:
    st.error(f'분석 중 오류가 발생했습니다: {exc}')

st.divider()
st.caption('주의: 고정 비중으로 매일 재조정한 가상 포트폴리오의 과거 분석입니다. 실제 계좌 실현 손익, 세금, 수수료, 환율, 시장충격은 반영하지 않습니다.')
