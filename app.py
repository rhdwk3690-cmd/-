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

# ── MARKET SIGNAL: 독립 홈 화면 ─────────────────────────────────────────
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
import yfinance as yf

SIGNAL_TICKERS = {'KOSPI': '^KS11', 'KOSDAQ': '^KQ11'}
KST = ZoneInfo('Asia/Seoul')


@st.cache_data(ttl=900, show_spinner=False)
def load_signal_data(ticker):
    raw = yf.download(
        ticker, period='3y', interval='1d', auto_adjust=False,
        progress=False, threads=False,
    )
    if raw is None or raw.empty:
        raise ValueError('Yahoo Finance 일봉 응답 없음')
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if not {'Close', 'Volume', 'Low'}.issubset(raw.columns):
        raise ValueError('가격·거래량 필수 열이 누락됨')
    frame = raw.copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    frame = frame[~frame.index.duplicated(keep='last')].sort_index()
    for col in ('Close', 'Volume', 'Low'):
        frame[col] = pd.to_numeric(frame[col], errors='coerce')
    frame = frame.dropna(subset=['Close'])
    frame = frame[frame['Close'] > 0]
    if len(frame) < 205:
        raise ValueError(f'일봉 {len(frame)}개 — 최소 205개 필요')
    age = (datetime.now(KST).date() - frame.index[-1].date()).days
    if age < 0 or age > 7:
        raise ValueError(f'기준일이 현재와 크게 다름: {frame.index[-1]:%Y-%m-%d}')
    for days in (20, 50, 200):
        frame[f'MA{days}'] = frame['Close'].rolling(days).mean()
    return frame


def signal_snapshot(df):
    p = df['Close']
    last = df.iloc[-1]
    m20, m50, m200 = (float(last[f'MA{x}']) for x in (20, 50, 200))
    close = float(p.iloc[-1])
    conditions = [close > m20, m20 > m50, close > m200, m50 > m200]
    statuses = {0: ('경계', '#f87171'), 1: ('중립', '#fbbf24'), 2: ('양호', '#4ade80')}
    delta = p.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    if loss.iloc[-1] > 0:
        rsi = float(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1]))
    elif gain.iloc[-1] > 0:
        rsi = 100.0
    else:
        rsi = float('nan')
    high_52 = float(p.tail(252).max())
    return {
        'close': close, 'date': df.index[-1],
        'pct': float(100 * (close / float(p.iloc[-2]) - 1)),
        'ma20': m20, 'ma50': m50, 'ma200': m200,
        'short': statuses[int(conditions[0]) + int(conditions[1])],
        'long': statuses[int(conditions[2]) + int(conditions[3])],
        'flags': conditions,
        'return20': float(100 * (close / float(p.iloc[-21]) - 1)),
        'return60': float(100 * (close / float(p.iloc[-61]) - 1)),
        'drawdown52': float(100 * (close / high_52 - 1)),
        'rsi': rsi,
    }


def signal_volume_ok(df):
    v = df['Volume']
    return bool(v.tail(27).notna().all() and (v.tail(27) > 0).all())


def dd_days(df):
    # 간이 DD: 최근 25거래일, 지수 -0.2% 이하 하락 + 전일 대비 거래량 증가.
    if not signal_volume_ok(df):
        return None
    close = df['Close']
    vol = df['Volume']
    down = (close.pct_change() <= -0.002) & (vol > vol.shift(1))
    return [day for day, yes in down.tail(25).items() if bool(yes)]


def ftd_candidate(df):
    # 정식 IBD FTD가 아닌 자체 정의의 반등 후보만 검출한다.
    if not signal_volume_ok(df):
        return None
    c, v, low = df['Close'], df['Volume'], df['Low'].fillna(df['Close'])
    results = []
    n = len(df)
    for trough in range(max(62, n - 75), n - 4):
        high60 = float(c.iloc[trough - 60:trough].max())
        if c.iloc[trough] > high60 * 0.92:
            continue
        if low.iloc[trough] > low.iloc[trough - 2:trough + 3].min():
            continue
        day1 = next(
            (j for j in range(trough + 1, min(trough + 5, n))
             if c.iloc[j] > c.iloc[j - 1]), None,
        )
        if day1 is None:
            continue
        for day in range(day1 + 3, min(day1 + 10, n)):
            if low.iloc[trough + 1:day + 1].min() < low.iloc[trough]:
                break
            if (c.iloc[day] >= c.iloc[day - 1] * 1.015
                    and v.iloc[day] > v.iloc[day - 1]
                    and c.iloc[day] > c.iloc[day1]):
                results.append(df.index[day])
                break
    if not results:
        return None
    latest = max(results)
    return latest if (n - df.index.get_loc(latest) - 1) <= 25 else None


def signal_badge(label, color):
    return (
        "<span style='display:inline-block;border:1px solid " + color +
        ";color:" + color + ";background:#11202b;padding:5px 10px;"
        "border-radius:10px;font-size:13px;font-weight:800'>" + escape(label) + "</span>"
    )


def signal_data_card(name, item):
    if item is None:
        return (
            "<div class='miner-index-card'><div class='miner-label'>" + name +
            "</div><div class='miner-number'>조회 실패</div>"
            "<div class='miner-sub'>데이터가 확보되면 신호를 표시합니다</div></div>"
        )
    delta_color = '#56df9d' if item['pct'] >= 0 else '#fa8185'
    short = signal_badge('단기 ' + item['short'][0], item['short'][1])
    long = signal_badge('장기 ' + item['long'][0], item['long'][1])
    return (
        f"<div class='miner-index-card'><div class='miner-label'>{name}"
        f" <span style='float:right'>기준 {item['date']:%Y-%m-%d}</span></div>"
        f"<div class='miner-number'>{item['close']:,.2f}"
        f"<span style='color:{delta_color};font-size:17px;margin-left:10px'>"
        f"{item['pct']:+.2f}%</span></div>"
        f"<div style='display:flex;gap:9px;flex-wrap:wrap;margin:12px 0'>{short}{long}</div>"
        f"<div class='miner-sub'>MA20 {item['ma20']:,.1f}&nbsp;·&nbsp;"
        f"MA50 {item['ma50']:,.1f}&nbsp;·&nbsp;MA200 {item['ma200']:,.1f}</div></div>"
    )



def market_signal():
    # 광부 시장신호판 공통 버튼 디자인
    st.markdown("""
    <style>
    /* 핵심 근거 요약 6개 버튼 */
    body .stApp.stApp:has(.miner-hero)
    [data-testid="stHorizontalBlock"]
    [data-testid="column"] button {
        background: #15293a !important;
        border: 1px solid #35536a !important;
        color: #f0f7ff !important;
        -webkit-text-fill-color: #f0f7ff !important;
        border-radius: 14px !important;
        font-weight: 700 !important;
    }

    /* 버튼 안의 글씨도 밝게 */
    body .stApp.stApp:has(.miner-hero)
    [data-testid="stHorizontalBlock"]
    [data-testid="column"] button * {
        color: #f0f7ff !important;
        -webkit-text-fill-color: #f0f7ff !important;
        opacity: 1 !important;
    }

    /* 마우스를 올렸을 때 */
    body .stApp.stApp:has(.miner-hero)
    [data-testid="stHorizontalBlock"]
    [data-testid="column"] button:hover {
        background: #233f53 !important;
        border-color: #70cbe0 !important;
    }

    /* 새로 조회 / 뒤로가기 버튼 */
    body .stApp.stApp
    [class*="st-key-miner_signal_refresh"] button,
    body .stApp.stApp
    [class*="st-key-miner_signal_back"] button {
        background: #f8fafc !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
    }

    body .stApp.stApp
    [class*="st-key-miner_signal_refresh"] button *,
    body .stApp.stApp
    [class*="st-key-miner_signal_back"] button * {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('''<style>
    /* 시장 신호 화면에만 적용되는 검정색 터미널 스타일 */
    .stApp{background:#080e16!important;color:#e9f0f8!important}
    .stApp [data-testid="stSidebar"]{background:#0d1521!important;border-right:1px solid #253346!important}
    .stApp [data-testid="stSidebar"] a,
    .stApp [data-testid="stSidebar"] span,
    .stApp [data-testid="stSidebar"] p{color:#e1eaf4!important}
    .stApp [data-testid="stHeader"]{background:rgba(8,14,22,.96)!important}
    .stApp [data-testid="stMarkdownContainer"] h1,
    .stApp [data-testid="stMarkdownContainer"] h2,
    .stApp [data-testid="stMarkdownContainer"] h3,
    .stApp [data-testid="stMarkdownContainer"] h4{color:#edf5ff!important}
    .stApp [data-testid="stMarkdownContainer"] p,
    .stApp [data-testid="stMarkdownContainer"] li{color:#cbd8e7}
    .stApp [data-testid="stCaptionContainer"]{color:#92a9c3!important}
    .stApp [data-testid="stMetric"]{background:#121f2e!important;border:1px solid #2b4055!important;border-radius:12px}
    .stApp [data-testid="stMetric"] *{color:#f2f7fb!important}
    .stApp [data-testid="stInfo"]{background:#132438}
    .stApp div[data-testid="stHorizontalBlock"] div[data-testid="column"] div.stButton button {
       background:linear-gradient(138deg,#152334,#101a29)!important;
       border:1px solid #35495d!important;border-radius:14px!important;
       color:#eef5fb!important;width:100%;min-height:122px;
       white-space:pre-line;text-align:left!important;
       justify-content:flex-start!important;line-height:1.55;padding:17px 22px!important;
       box-shadow:0 2px 12px #0000001e;transition:all .16s ease;
    }
    .stApp div[data-testid="stHorizontalBlock"] div[data-testid="column"] div.stButton button:hover {
       background:#20364a!important;border-color:#6aaec6!important;
       transform:translateY(-2px);box-shadow:0 8px 22px #0004;
    }
    .stApp div[data-testid="stHorizontalBlock"] div[data-testid="column"] div.stButton button p{color:#eef5fb!important}
    .miner-hero{background:linear-gradient(112deg,#0d2538,#121c2e 68%,#0b1624);border:1px solid #2c4a61;border-radius:17px;padding:21px 25px;color:#f0f7fb;margin-bottom:10px}
    .miner-eyebrow{font-size:11px;letter-spacing:2px;color:#8cd5e0;font-weight:800}
    .miner-hero-title{font-size:27px;line-height:1.25;font-weight:900;margin:8px 0}
    .miner-sub{font-size:12px;color:#a5b9c9}
    .miner-index{background:linear-gradient(145deg,#152636,#0f1a29);border:1px solid #344b5c;border-radius:13px;padding:17px 20px;min-height:151px;color:#f4f7fb}
    .miner-index-title{color:#a4bfce;font-size:13px;font-weight:800}
    .miner-index-price{font-size:27px;font-weight:850;margin:8px 0}
    .miner-gauge{background:#121e2b;border:1px solid #324456;border-radius:14px;padding:18px 22px;color:white;margin:8px 0 10px}
    .miner-segments{display:flex;gap:3px;height:16px;border-radius:10px;overflow:hidden;margin-top:17px}
    .miner-segments span{flex:1}
    .miner-zones{display:flex;justify-content:space-between;color:#9aafc4;font-size:11px;margin-top:7px}
    .miner-detail-note{background:#112334;border-left:3px solid #4daaba;border-radius:7px;color:#c5d8e7;padding:11px 14px;font-size:13px;margin:7px 0}
    </style>''', unsafe_allow_html=True)

    
    # 핵심 근거 요약 6개 버튼 - 실제 Streamlit 버튼 직접 지정
    st.markdown("""
    <style>
    .stApp.stApp.stApp.stApp
    [data-testid="stHorizontalBlock"] button {
        background: #15293a !important;
        border: 1px solid #35536a !important;
        color: #f0f7ff !important;
        -webkit-text-fill-color: #f0f7ff !important;
        border-radius: 14px !important;
    }

    .stApp.stApp.stApp.stApp
    [data-testid="stHorizontalBlock"] button * {
        color: #f0f7ff !important;
        -webkit-text-fill-color: #f0f7ff !important;
        opacity: 1 !important;
    }

    .stApp.stApp.stApp.stApp
    [data-testid="stHorizontalBlock"] button:hover {
        background: #233f53 !important;
        border-color: #70cbe0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    
    if 'miner_signal_view' not in st.session_state:
        st.session_state.miner_signal_view = '종합'
    view = st.session_state.miner_signal_view
    st.markdown('''<div class="miner-hero">
       <div class="miner-eyebrow">⛏ MINER'S TERMINAL · MARKET SIGNAL V3.1</div>
       <div class="miner-hero-title">지금 시장은 어디에 있는가?</div>
       <div class="miner-sub">검정색 시장 신호판 · 요약 카드를 눌러 상세 분석으로 이동</div>
    </div>''', unsafe_allow_html=True)
    if view == '종합':
        st.caption('KOSPI·KOSDAQ · Yahoo Finance 일봉(지연 가능) · 종가 확정 전 수치 변동 가능 · 캐시 15분')
    else:
        if st.button('←  시장 신호 종합으로 돌아가기', key='miner_signal_back'):
            st.session_state.miner_signal_view = '종합'
            st.rerun()
        st.caption('상세 분석 · Yahoo Finance 일봉 · 연구용 자체 계산')

    if st.button('🔄 시장 신호 데이터 새로 조회', key='miner_signal_refresh'):
        load_signal_data.clear()
        st.rerun()

    datasets, states, errors = {}, {}, {}
    with st.spinner('코스피·코스닥 가격 데이터를 불러오는 중...'):
        for name, ticker in SIGNAL_TICKERS.items():
            try:
                datasets[name] = load_signal_data(ticker)
                states[name] = signal_snapshot(datasets[name])
            except Exception as exc:
                errors[name] = str(exc)
    for name, msg in errors.items():
        st.warning(f'{name}: 조회 실패 — {msg}')

    if view == '종합':
        # 1) 스탁이지 참고: 지수 상태 2개 → 게이지 → 6개 클릭 가능한 요약 카드
        st.markdown('#### 🚦 코스피·코스닥 신호')
        cols = st.columns(2, gap='small')
        for name, col in zip(SIGNAL_TICKERS, cols):
            with col:
                s = states.get(name)
                if s is None:
                    st.markdown(f'<div class="miner-index"><b>{name}</b><p>데이터 조회 대기</p></div>', unsafe_allow_html=True)
                    continue
                move = '#6ce4b2' if s['pct'] >= 0 else '#ff8e92'
                short, long = s['short'], s['long']
                st.markdown(
                    '<div class="miner-index">'
                    f'<div class="miner-index-title">{name} &nbsp; <span style="float:right">{s["date"]:%Y-%m-%d}</span></div>'
                    f'<div class="miner-index-price">{s["close"]:,.2f} <span style="font-size:15px;color:{move}">{s["pct"]:+.2f}%</span></div>'
                    f'<div style="font-size:14px">단기 <b style="color:{short[1]}">{short[0]}</b>'
                    f' &nbsp; | &nbsp; 장기 <b style="color:{long[1]}">{long[0]}</b></div>'
                    f'<div class="miner-sub" style="margin-top:10px">MA20 {s["ma20"]:,.0f} · MA200 {s["ma200"]:,.0f}</div>'
                    '</div>', unsafe_allow_html=True)

        st.markdown('#### 🌡️ 지금 여긴 · 시장 추세 게이지')
        if len(states) == 2:
            fulfilled = sum(sum(bool(x) for x in s['flags']) for s in states.values())
            score = round(100 * fulfilled / 8)
            zone = ('위험' if score <= 20 else '방어' if score <= 40 else
                    '중립' if score <= 60 else '양호' if score <= 80 else '강세')
            bars = [('위험','#b9484c'),('방어','#db9a55'),('중립','#e4c669'),('양호','#78b68f'),('강세','#279768')]
            segments = ''.join(f'<span style="background:{c}"></span>' for _,c in bars)
            pct = min(max(float(score), 1.5), 98.5)
            st.markdown(f'''<div class="miner-gauge">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:14px">
                  <div><div class="miner-sub">지수 이동평균 추세 조건 8개 종합</div>
                  <div style="font-size:25px;font-weight:900">{zone} 구간</div></div>
                  <div style="font-size:32px;font-weight:900">{score}<span style="font-size:14px;color:#a1b6c7"> / 100</span></div>
                </div>
                <div style="position:relative;padding-top:19px">
                  <div style="position:absolute;top:0;left:{pct}%;transform:translateX(-50%);font-size:16px">▼</div>
                  <div class="miner-segments">{segments}</div>
                  <div class="miner-zones">{''.join(f'<span>{k}</span>' for k,_ in bars)}</div>
                </div><div class="miner-sub" style="margin-top:10px">가격 추세 참고 점수 · 주식 권장 비중이 아닙니다</div>
            </div>''', unsafe_allow_html=True)
            if len({s['date'] for s in states.values()}) != 1:
                st.warning('두 지수의 데이터 기준일이 서로 달라 종합 점수 해석에 주의가 필요합니다.')
        else:
            st.info('두 지수의 가격 자료가 모두 확보될 때만 시장 점수를 표시합니다.')

        def dd_summary(name):
            if name not in datasets:
                return '조회 대기'
            days = dd_days(datasets[name])
            return f'{len(days)}일' if days is not None else '거래량 자료 부족'

        def ftd_summary(name):
            if name not in datasets:
                return '조회 대기'
            if not signal_volume_ok(datasets[name]):
                return '거래량 자료 부족'
            date = ftd_candidate(datasets[name])
            return f'{date:%m/%d} 후보' if date is not None else '최근 후보 미발견'

        st.markdown('#### 🧭 핵심 근거 요약 · 카드를 누르면 상세 화면')
        kp = states.get('KOSPI'); kq = states.get('KOSDAQ')
        cards = [
            ('시장 체력','📊 시장 체력',
             f'20일 수익률  코스피 {kp["return20"]:+.1f}% / 코스닥 {kq["return20"]:+.1f}%' if kp and kq else '지수 모멘텀 자료 조회 대기'),
            ('매도 압력','🔻 매도 압력 · DD',
             f'최근 25거래일  코스피 {dd_summary("KOSPI")} / 코스닥 {dd_summary("KOSDAQ")}'),
            ('반등 확인','🔺 반등 확인 · FTD',
             f'코스피 {ftd_summary("KOSPI")} / 코스닥 {ftd_summary("KOSDAQ")}'),
            ('증시 자금','💰 증시 자금',
             '예탁금 · 신용잔고 · 오실레이터  |  원자료 연동 대기'),
            ('외국인·기관 수급','🏦 외국인·기관 수급',
             '일별 순매수 금액은 기존 「자금 흐름」에 연결됨'),
            ('추세 차트','📈 시장 추세 변화',
             '코스피·코스닥 가격 / MA20·MA50·MA200 차트'),
        ]
        for i in range(0, len(cards), 2):
            left, right = st.columns(2, gap='small')
            for col, (id_, title, description) in zip((left, right), cards[i:i+2]):
                with col:
                    if st.button(f'{title}\n{description}\n↗ 상세 분석 보기',
                                 key=f'miner_card_{i}_{id_}', use_container_width=True):
                        st.session_state.miner_signal_view = id_
                        st.rerun()
        st.markdown('<div class="miner-detail-note">● 신호는 지수 가격·거래량으로 계산한 참고 지표입니다. 전 종목 ADR, 신용잔고·예탁금은 아직 연결되지 않아 표시하지 않습니다.</div>', unsafe_allow_html=True)
        return

    # 2) 위의 카드에서 진입하는 상세 화면: 기본 페이지에는 펼치지 않음
    st.markdown(f'### {view} · 상세 분석')
    if view == '시장 체력':
        st.caption('현재 연결된 값은 지수 가격 기반입니다. 시장 전체 종목 폭 지표와 다릅니다.')
        fields = [('return20','최근 20거래일','%'),('return60','최근 60거래일','%'),
                  ('drawdown52','52주 최고 종가 대비','%'),('rsi','RSI (14일)','')]
        for name in SIGNAL_TICKERS:
            if name not in states:
                st.info(f'{name} · 지수 자료 대기')
                continue
            s = states[name]
            st.markdown(f'**{name}** · 기준일 {s["date"]:%Y-%m-%d}')
            cols = st.columns(4)
            for col, (key, title, unit) in zip(cols, fields):
                value = s[key]
                col.metric(title, '자료 부족' if pd.isna(value) else
                           f'{value:.1f}' if key == 'rsi' else f'{value:+.1f}{unit}')
            st.divider()
        st.info('전 종목 20일·200일선 상회 비율, ADR, 52주 신고가·신저가 종목 수는 과거 전 종목 가격 확보 후 추가합니다.')

    elif view == '매도 압력':
        st.caption('Distribution Day: 지수 -0.2% 이하 하락과 거래량 증가가 겹친 날 (간이 정의).')
        for name, df in datasets.items():
            days = dd_days(df)
            if days is None:
                st.warning(f'{name}: 거래량 누락으로 판정 보류')
            else:
                st.metric(f'{name} · 최근 25거래일 간이 DD', f'{len(days)}일')
                st.write('발생일: ' + (', '.join(d.strftime('%Y-%m-%d') for d in days) if days else '없음'))
        st.info('지수 거래량 기반 간이 지표이며 실제 기관 순매도 금액이나 공식 IBD Distribution Day 계산과 다릅니다.')

    elif view == '반등 확인':
        st.caption('Follow-Through Day: 반등 과정에서 강한 상승과 거래량 증가를 확인하는 간이 후보.')
        for name, df in datasets.items():
            if not signal_volume_ok(df):
                st.warning(f'{name}: 거래량 누락으로 판정 보류')
            else:
                day = ftd_candidate(df)
                if day is None:
                    st.info(f'{name}: 최근 25거래일 간이 FTD 후보 없음')
                else:
                    st.success(f'{name}: 간이 FTD 후보 발생일 {day:%Y-%m-%d}')
        st.info('공식 William O’Neil / IBD 신호가 아니며 추세 반전이나 투자 수익을 보장하지 않습니다.')

    elif view == '추세 차트':
        name = st.radio('지수 선택', list(SIGNAL_TICKERS), horizontal=True, key='miner_v31_chart_name')
        if name not in datasets:
            st.info('지수 자료 조회 대기')
        else:
            df = datasets[name]
            fig = go.Figure()
            for key, label, color in [('Close','지수','#dceffb'),('MA20','MA20','#4ad0e2'),
                                      ('MA50','MA50','#e5a75d'),('MA200','MA200','#d68ca9')]:
                fig.add_trace(go.Scatter(x=df.index[-180:], y=df[key].iloc[-180:],
                                         name=label, line=dict(color=color,width=2 if key=='Close' else 1.5)))
            fig.update_layout(height=440, margin=dict(l=5,r=5,t=15,b=15),
                              hovermode='x unified', legend=dict(orientation='h',y=-.15),
                              paper_bgcolor='#101a28',plot_bgcolor='#101a28',
                              font=dict(color='#dae8f5'))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f'{name} · 기준 {df.index[-1]:%Y-%m-%d} · Yahoo Finance')

    elif view == '증시 자금':
        st.info('투자자예탁금, 신용잔고, 신용잔고/예탁금, 신용 오실레이터는 공급처 원자료 확인 후 연결합니다.')
        st.caption('현재 유효한 시계열이 없어 임의의 숫자나 점수를 표시하지 않습니다.')

    elif view == '외국인·기관 수급':
        st.success('외국인·기관·개인의 종목별 일별 순매수 금액은 왼쪽 「자금 흐름」 메뉴에서 조회할 수 있습니다.')
        st.info('장중 잠정 수급은 보류 중입니다. 일별 확정/게시 데이터와 장중 추정치를 섞지 않습니다.')

    with st.expander('🔎 신호 계산 근거 · 한계'):
        st.markdown('''**단기 신호**: 종가 > MA20, MA20 > MA50 (2개 중 0/1/2 충족 = 경계/중립/양호).  
**장기 신호**: 종가 > MA200, MA50 > MA200 (동일 방식).  
**시장 게이지**: 코스피·코스닥 각각 4개, 총 8개 추세 조건을 동일 가중치로 합산. 추천 주식 비중 아님.  
**DD**: 최근 25거래일, 지수 -0.2% 이하 하락 + 거래량 증가의 단순 집계. 기관 순매도액이 아님.  
**FTD**: 조정 후 랠리 Day 1을 기록하고 기준 저점을 유지한 상태에서 4거래일차 이후 지수 1% 이상 상승과 전일 대비 거래량 증가를 확인합니다. 조정 진입·상승 압박·추세 실패는 자체 판정이며 IBD 공식 시장 상태와 다릅니다.


# ==================================================
# MINER TERMINAL | GLOBAL DARK DESIGN
# 모든 8개 메뉴에서 사용하는 공통 스타일
# 기존 기능과 계산식은 변경하지 않음
# ==================================================

import plotly.io as pio
pio.templates.default = "plotly_dark"

st.markdown("""
<style>

/* 1. 전체 화면과 사이드바 */
.stApp {
    background: #080e16 !important;
    color: #eaf1fa !important;
}

.stApp [data-testid="stSidebar"] {
    background: #0d1521 !important;
    border-right: 1px solid #253346 !important;
}

.stApp [data-testid="stSidebar"] a,
.stApp [data-testid="stSidebar"] span,
.stApp [data-testid="stSidebar"] p {
    color: #e4edf7 !important;
}

.stApp [data-testid="stHeader"] {
    background: rgba(8,14,22,0.96) !important;
}

/* 2. 제목과 설명 */
.stApp h1,
.stApp h2,
.stApp h3 {
    color: #f0f7ff !important;
}

.stApp h1 {
    background: linear-gradient(
        115deg, #102b40, #101b2a
    );
    border: 1px solid #305068;
    border-radius: 16px;
    padding: 18px 22px;
}

.stApp [data-testid="stCaptionContainer"] {
    color: #a7b9ca !important;
}

/* 3. 모든 일반 버튼과 다운로드 버튼 */
.stApp .stButton > button,
.stApp .stDownloadButton > button,
.stApp .stFormSubmitButton > button {
    background: #15293a !important;
    border: 1px solid #35536a !important;
    border-radius: 12px !important;
    color: #f0f7ff !important;
    -webkit-text-fill-color: #f0f7ff !important;
    font-weight: 650 !important;
    transition: background 0.15s, border-color 0.15s;
}

.stApp .stButton > button *,
.stApp .stDownloadButton > button *,
.stApp .stFormSubmitButton > button * {
    color: #f0f7ff !important;
    -webkit-text-fill-color: #f0f7ff !important;
    opacity: 1 !important;
}

/* 4. 마우스 올림 효과 */
.stApp .stButton > button:hover,
.stApp .stDownloadButton > button:hover,
.stApp .stFormSubmitButton > button:hover {
    background: #233f53 !important;
    border-color: #70cbe0 !important;
}

.stApp .stButton > button:disabled {
    opacity: 0.5 !important;
}

/* 5. 지표 숫자 카드 */
.stApp [data-testid="stMetric"] {
    background: #122131 !important;
    border: 1px solid #30495e !important;
    border-radius: 14px !important;
    padding: 14px !important;
}

.stApp [data-testid="stMetricLabel"],
.stApp [data-testid="stMetricValue"] {
    color: #eef6ff !important;
}

/* 6. 입력창 */
.stApp input:not([type="checkbox"]),
.stApp textarea {
    background: #111f2e !important;
    border-color: #355067 !important;
    color: #f0f7ff !important;
    -webkit-text-fill-color: #f0f7ff !important;
}

.stApp [data-baseweb="select"] > div {
    background: #111f2e !important;
    border-color: #355067 !important;
    color: #f0f7ff !important;
}

/* 7. 데이터 표 */
.stApp [data-testid="stDataFrame"] {
    border: 1px solid #30495e !important;
    border-radius: 12px !important;
    overflow: hidden;
}

/* 8. 탭 */
.stApp .stTabs [data-baseweb="tab"] {
    color: #b1c5d6 !important;
}

.stApp .stTabs [aria-selected="true"] {
    color: #70cbe0 !important;
    border-bottom-color: #70cbe0 !important;
}

/* 9. 접기/펼치기 상세 분석 */
.stApp [data-testid="stExpander"] {
    background: #101c2a !important;
    border: 1px solid #30495e !important;
    border-radius: 12px !important;
}

/* 10. 구분선 */
.stApp hr {
    border-color: #2c4053 !important;
}

</style>
""", unsafe_allow_html=True)

# ============================================================
# WILLIAM O'NEIL / IBD - 공개 정량 규칙 기반 DD / FTD 엔진
# KOSPI·KOSDAQ 적용용. IBD 공식 제공 판정값은 아님.
# ============================================================

ONEIL_FTD_MIN_GAIN = 0.0125

# 조정 국면을 자동 식별하기 위한 보조 가정
# -8%는 IBD의 유일한 공식 조정 기준이 아님
ONEIL_CORRECTION = 0.08


def _oneil_prepare(df):
    c = pd.to_numeric(df['Close'], errors='coerce')
    v = pd.to_numeric(df['Volume'], errors='coerce')
    l = pd.to_numeric(df['Low'], errors='coerce')

    if (
        len(df) < 125
        or c.tail(27).isna().any()
        or v.tail(27).isna().any()
        or l.tail(27).isna().any()
        or (v.tail(27) <= 0).any()
    ):
        return None

    return c, v, l


def dd_days(df):
    """
    Distribution Day:
    1. 지수 전일 대비 -0.2% 이상 하락
    2. 거래량 전일보다 증가
    3. 최근 25거래일 내 발생
    4. 이후 DD 종가 대비 5% 상승 시 집계 제외
    """
    ready = _oneil_prepare(df)

    if ready is None:
        return None

    close, volume, low = ready
    active = []

    for i in range(max(1, len(df) - 25), len(df)):

        decline = (
            close.iloc[i] / close.iloc[i - 1] - 1
        )

        is_distribution = (
            decline <= -0.002
            and volume.iloc[i] > volume.iloc[i - 1]
        )

        if not is_distribution:
            continue

        # 이후 5% 상승을 달성한 DD는 더 이상 집계하지 않음
        recovered = (
            close.iloc[i + 1:]
            >= close.iloc[i] * 1.05
        ).any()

        if not recovered:
            active.append(df.index[i])

    return active


def ftd_candidate(df):
    """
    Follow-Through Day:
    1. 조정 국면에서 반등 시도 1일차 확인
    2. 반등 시도 저점 유지
    3. 랠리 시도 4거래일차 이후
    4. 지수 +1.25% 이상 상승
    5. 거래량 전일보다 증가
    6. 이후 랠리 기준 저점 이탈 시 무효

    참고:
    조정 국면 -8% 및 최근 10일 저점 탐색은
    한국 지수 적용을 위한 자동 판정 보조 규칙.
    """
    ready = _oneil_prepare(df)

    if ready is None:
        return None

    close, volume, low = ready
    n = len(df)
    found = []

    for day1 in range(max(121, n - 120), n - 3):

        # 랠리 시도 1일차: 전일보다 높은 종가
        if close.iloc[day1] <= close.iloc[day1 - 1]:
            continue

        # 직전 저점이 최근 10거래일 저점인지 확인
        if (
            pd.isna(low.iloc[day1 - 1])
            or pd.isna(low.iloc[day1])
            or low.iloc[day1 - 1]
            > low.iloc[day1 - 11:day1].min()
        ):
            continue

        # 선행 조정 국면 확인
        prior_peak = close.iloc[
            day1 - 121:day1
        ].max()

        if not (
            prior_peak > 0
            and low.iloc[day1 - 1]
            <= prior_peak * (1 - ONEIL_CORRECTION)
        ):
            continue

        # 랠리 시도가 지켜야 할 기준 저점
        rally_low = min(
            float(low.iloc[day1 - 1]),
            float(low.iloc[day1])
        )

        if not pd.notna(rally_low):
            continue

        # day1+3 = 랠리 시도 4일차
        for day in range(day1 + 1, n):

            # 저점 이탈: 해당 랠리 시도 무효
            if (
                not pd.notna(low.iloc[day])
                or low.iloc[day] < rally_low
            ):
                break

            if day < day1 + 3:
                continue

            # 거래량 자료가 정상인지 확인
            if not (
                pd.notna(volume.iloc[day])
                and pd.notna(volume.iloc[day - 1])
                and volume.iloc[day] > 0
                and volume.iloc[day - 1] > 0
            ):
                continue

            gain = (
                close.iloc[day]
                / close.iloc[day - 1]
                - 1
            )

            is_ftd = (
                gain >= ONEIL_FTD_MIN_GAIN
                and volume.iloc[day] > volume.iloc[day - 1]
                and close.iloc[day] > close.iloc[day1]
            )

            if is_ftd:

                # FTD 이후 랠리 저점을 이탈했는지 확인
                invalidated = (
                    low.iloc[day + 1:].dropna()
                    < rally_low
                ).any()

                if invalidated:
                    break

                # 기존 대시보드의 최근 25거래일 표시 유지
                if n - 1 - day <= 25:
                    found.append(df.index[day])

                break

    return max(found) if found else None
# ============================================================
# 광부 투자터미널 | IBD 공개 규칙 기반 시장 상태 엔진
# 붙여넣기 위치: app.py의 `from flow_pages import cashflow` 바로 위
# 기존 함수들은 새 정의로 덮어쓰며, 기존 8개 메뉴는 유지
# ============================================================

ONEIL_FTD_GAIN = 0.01  # 2026 IBD 공개 교육자료: 대체로 1% 이상 + 거래량 증가


def signal_volume_ok(df):
    """지수 거래량이 유효한지 검사. 0/NaN이면 FTD/DD 확정 금지."""
    needed = {'Close', 'Low', 'Volume'}
    if not needed.issubset(df.columns) or len(df) < 205:
        return False
    recent = df[['Close', 'Low', 'Volume']].tail(260).apply(
        pd.to_numeric, errors='coerce'
    )
    return bool(recent.notna().all().all() and
                (recent[['Close', 'Low', 'Volume']] > 0).all().all())


def _oneil_dd_asof(close, volume, i):
    """i일 현재 유효한 DD: -0.2%, 거래량 증가, 25일 경과/5% 회복 시 제외."""
    days = []
    for j in range(max(1, i - 24), i + 1):
        if (close[j] <= close[j - 1] * 0.998 and
                volume[j] > volume[j - 1]):
            if j == i or not (close[j + 1:i + 1] >= close[j] * 1.05).any():
                days.append(j)
    return days


def oneil_market_state(df):
    """
    공개 정량 규칙: Day1 상승마감, 저점 유지, Day4+ 1%+ 거래량 증가,
    DD -0.2%/거래량 증가, 25거래일/5% 상승 소멸.
    자체 규칙(IBD 공식 아님): 조정 진입/상승 압박/추세 실패 판정.
    """
    empty = dict(status='판정 보류', day1=None, rally_days=0, ftd=None,
                 dd=[], reason='지수 가격·거래량 데이터가 부족합니다.', events=[])
    if not signal_volume_ok(df):
        return empty

    df = df.sort_index()
    close = pd.to_numeric(df['Close']).to_numpy(dtype=float)
    low = pd.to_numeric(df['Low']).to_numpy(dtype=float)
    volume = pd.to_numeric(df['Volume']).to_numpy(dtype=float)
    ma50 = pd.Series(close).rolling(50).mean().to_numpy()
    dates = df.index
    start = max(50, len(df) - 260)
    state = '관찰'
    day1 = None
    rally_low = None
    ftd = None
    events = []
    reason = '조정 진입 조건을 감시 중입니다.'

    for i in range(start, len(df)):
        dd = _oneil_dd_asof(close, volume, i)
        below50_2 = (close[i] < ma50[i] and
                     close[i - 1] < ma50[i - 1])
        below50_3 = (below50_2 and
                     close[i - 2] < ma50[i - 2])

        if state == '관찰':
            # 자체 조정 진입 기준: 50일선 아래 이틀 연속 마감.
            if below50_2:
                state = '조정'
                reason = '50일선 아래 2거래일 마감(광부 자체 조정 기준)'
                events.append((dates[i], '조정 진입', reason))
            continue

        if state == '조정':
            # IBD 공개 원칙의 명확한 부분만 자동화: 첫 상승마감 = Day 1.
            # 하락했지만 고가 부근 마감한 예외는 판정하지 않음.
            if close[i] > close[i - 1]:
                day1 = i
                rally_low = low[i]
                ftd = None
                state = '랠리 시도'
                reason = '상승마감으로 랠리 시도 1일차 시작'
                events.append((dates[i], 'Day 1', reason))
            continue

        if state == '랠리 시도':
            if low[i] < rally_low:
                state = '조정'
                day1, rally_low, ftd = None, None, None
                reason = 'Day 1 기준 저점 이탈 → 랠리 시도 실패'
                events.append((dates[i], '랠리 실패', reason))
                continue

            day_number = i - day1 + 1
            gain = close[i] / close[i - 1] - 1
            if (day_number >= 4 and gain >= ONEIL_FTD_GAIN
                    and volume[i] > volume[i - 1]):
from flow_pages import cashflow as cashflow, top200 as top200
pages=[
    st.Page(market_signal,title='시장 신호',icon='🚦',default=True),
    st.Page('pages/1_광부_종합상황판.py',title='종합 상황판',icon='🌎'),
    st.Page(cashflow,title='자금 흐름',icon='💸'),
    st.Page(etfs,title='ETF 분석',icon='📦'),
    st.Page(top200,title='TOP 200',icon='📊'),
    st.Page(individual,title='개별 종목',icon='🔎'),
    st.Page('pages/2_계좌방어_리스크레이더.py' if os.path.exists('pages/2_계좌방어_리스크레이더.py') else lambda: placeholder('🛡️ 계좌 방어','계좌 방어 파일을 pages 폴더에 넣으면 활성화됩니다.',['포트폴리오 MDD·집중도·상관관계 분석']),title='계좌 방어',icon='🛡️'),
    st.Page(research,title='전략 연구실',icon='🧪'),
]
nav=st.navigation(pages,position='sidebar',expanded=True)
nav.run()


# 시장 신호판 흰색 버튼 글씨 가독성 수정
st.markdown("""
<style>
.stApp [class*="st-key-miner_signal_refresh"] button,
.stApp [class*="st-key-miner_signal_refresh"] button *,
.stApp [class*="st-key-miner_signal_back"] button,
.stApp [class*="st-key-miner_signal_back"] button * {
    color: #111827 !important;
    -webkit-text-fill-color: #111827 !important;
    opacity: 1 !important;
    font-weight: 700 !important;
}
</style>
""", unsafe_allow_html=True)
  

# 광부 시장신호판 버튼 디자인 통일
# 흰색 배경 + 검정색 글씨 + 하늘색 호버
st.markdown("""
<style>
/* 핵심 근거 요약의 6개 클릭 카드 */
.stApp div[data-testid="stHorizontalBlock"]
div[data-testid="column"]
[class*="st-key-miner_card_"] button {
    background: #f8fafc !important;
    border: 1px solid #cbd5e1 !important;
    color: #111827 !important;
    border-radius: 14px !important;
    font-weight: 700 !important;
}

/* 카드 안의 제목·설명·아이콘 */
.stApp [class*="st-key-miner_card_"] button,
.stApp [class*="st-key-miner_card_"] button *,
.stApp [class*="st-key-miner_signal_refresh"] button *,
.stApp [class*="st-key-miner_signal_back"] button * {
    color: #111827 !important;
    -webkit-text-fill-color: #111827 !important;
    opacity: 1 !important;
}

/* 마우스를 올렸을 때 */
.stApp div[data-testid="stHorizontalBlock"]
div[data-testid="column"]
[class*="st-key-miner_card_"] button:hover {
    background: #dbeafe !important;
    border-color: #60a5fa !important;
}
</style>
""", unsafe_allow_html=True)


# 광부 시장신호판 다크 버튼 디자인 통일
st.markdown("""
<style>
.stApp div[data-testid="stHorizontalBlock"]
div[data-testid="column"]
[class*="st-key-miner_card_"] button {
    background: #15293a !important;
    border: 1px solid #35536a !important;
    color: #f0f7ff !important;
    border-radius: 14px !important;
}

.stApp [class*="st-key-miner_card_"] button *,
.stApp [class*="st-key-miner_card_"] button p {
    color: #f0f7ff !important;
    -webkit-text-fill-color: #f0f7ff !important;
    opacity: 1 !important;
}

.stApp div[data-testid="stHorizontalBlock"]
div[data-testid="column"]
[class*="st-key-miner_card_"] button:hover {
    background: #233f53 !important;
    border-color: #70cbe0 !important;
}
</style>
""", unsafe_allow_html=True)
