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

# ── MARKET SIGNAL V2: 독립 홈 화면 ─────────────────────────────────────────
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
    st.markdown('''<style>
      .miner-head{padding:24px 26px;border-radius:17px;background:linear-gradient(118deg,#102e38,#17283b 58%,#10202e);border:1px solid #294658;color:#f4f8fc;margin-bottom:14px}
      .miner-eyebrow{font-size:12px;letter-spacing:1.9px;color:#81bbc3;font-weight:800}
      .miner-headline{font-size:31px;font-weight:900;margin:6px 0}
      .miner-description{color:#acbfcd;font-size:14px}
      .miner-index-card{color:#f4f8fc;background:linear-gradient(145deg,#152938,#101c2b);padding:19px 22px;border-radius:15px;border:1px solid #2f485b;min-height:177px}
      .miner-label{font-size:14px;color:#9bb5c7;font-weight:750}
      .miner-number{font-weight:850;font-size:29px;margin:9px 0 3px}
      .miner-sub{font-size:12px;color:#a7b9c8;margin-top:4px}
      .miner-score{color:#f5f8fa;background:#132332;border:1px solid #315063;border-radius:15px;padding:19px 22px}
      .miner-score-top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
      .miner-strip{height:18px;display:flex;gap:3px;overflow:hidden;border-radius:10px;background:#0d1623}
      .miner-strip span{flex:1}
      .miner-range{display:flex;justify-content:space-between;font-size:12px;color:#afc2d1;margin-top:7px}
      .miner-note{border-left:3px solid #59b7bf;padding:9px 15px;background:#112431;border-radius:6px;color:#c7dae8;font-size:14px}
    </style>''', unsafe_allow_html=True)
    st.markdown('''<div class='miner-head'>
      <div class='miner-eyebrow'>⛏ MINER'S TERMINAL · MARKET SIGNAL V2</div>
      <div class='miner-headline'>지금 시장은 어디에 있는가?</div>
      <div class='miner-description'>3초 요약으로 시장의 방향을 보고, 아래에서 수급·추세·매도 압력의 근거를 확인합니다.</div>
    </div>''', unsafe_allow_html=True)

    header1, header2 = st.columns([3, 1])
    with header1:
        st.caption('Yahoo Finance 지수 일봉 · 장중 값 변동 가능 · 한국시간 기준 · 자동 갱신 15분')
    with header2:
        if st.button('🔄 데이터 다시 조회', key='signal_v2_reload', use_container_width=True):
            load_signal_data.clear()
            st.rerun()

    datasets, states, issues = {}, {}, {}
    with st.spinner('지수 가격과 추세를 조회하고 있습니다...'):
        for name, ticker in SIGNAL_TICKERS.items():
            try:
                datasets[name] = load_signal_data(ticker)
                states[name] = signal_snapshot(datasets[name])
            except Exception as exc:
                issues[name] = str(exc)
    for name, issue in issues.items():
        st.warning(f'{name} 조회 실패: {issue}')

    st.subheader('🚦 코스피·코스닥 시장 신호')
    a, b = st.columns(2)
    with a:
        st.markdown(signal_data_card('KOSPI', states.get('KOSPI')), unsafe_allow_html=True)
    with b:
        st.markdown(signal_data_card('KOSDAQ', states.get('KOSDAQ')), unsafe_allow_html=True)

    st.subheader('🌡️ 시장 추세 게이지')
    if len(states) == 2:
        score = int(round(100 * sum(sum(map(int, item['flags'])) for item in states.values()) / 8))
        buckets = [(20, '위험', '#ef7777'), (40, '방어', '#e2a05b'),
                   (60, '중립', '#f1cf73'), (80, '양호', '#82d8ad'),
                   (100, '강세', '#58e0ae')]
        zone = next(z for threshold, z, _ in buckets if score <= threshold)
        pointer = max(1.5, min(98.5, float(score)))
        bars = ''.join(
            f"<span style='background:{color}'></span>"
            for _, _, color in buckets
        )
        st.markdown(f"""<div class='miner-score'>
           <div class='miner-score-top'>
             <div><div style='font-size:13px;color:#adc5d2'>단순 가격 추세 조건 8개 종합</div>
                  <div style='font-size:24px;font-weight:900'>{zone} 구간</div></div>
             <div style='font-size:33px;font-weight:900'>{score}
               <span style='font-size:13px;color:#9db4c5'> / 100</span></div>
           </div>
           <div style='position:relative;padding-top:20px;margin-top:12px'>
             <div style='position:absolute;top:0;left:{pointer}%;transform:translateX(-50%);font-size:16px'>▼</div>
             <div class='miner-strip'>{bars}</div>
             <div class='miner-range'><span>위험</span><span>방어</span><span>중립</span><span>양호</span><span>강세</span></div>
           </div>
           <div class='miner-sub' style='margin-top:16px'>코스피·코스닥 이동평균 조건 각 4개를 동일 가중치로 산출한 연구용 지수. 위험 선호도 설문이나 추천 주식 비중이 아닙니다.</div>
         </div>""", unsafe_allow_html=True)
        last_dates = [item['date'] for item in states.values()]
        if len(set(last_dates)) > 1:
            st.warning('KOSPI와 KOSDAQ의 최종 데이터 기준일이 다릅니다. 비교에 주의하세요.')
        optimistic = sum(item['short'][0] == '양호' for item in states.values())
        if optimistic == 2:
            explanation = '두 지수의 단기 추세가 모두 양호합니다. 장기 신호와 거래량 신호를 함께 확인하세요.'
        elif optimistic == 0:
            explanation = '두 지수 모두 단기 추세가 확실히 양호한 상태는 아닙니다. 무리한 추세 추종에는 주의가 필요합니다.'
        else:
            explanation = '두 지수의 단기 추세가 엇갈립니다. 시장 전체 강세로 단정하기보다 지수별 차이를 확인하세요.'
        st.markdown(f"<div class='miner-note'><b>오늘의 추세 해석</b> · {escape(explanation)}</div>", unsafe_allow_html=True)
    else:
        st.info('두 지수 데이터가 모두 확보돼야 추세 점수를 표시합니다. 확인되지 않은 점수는 만들지 않습니다.')

    st.subheader('📊 시장 체력 · 지수 모멘텀')
    metric_names = [('return20', '최근 20거래일', '%'),
                    ('return60', '최근 60거래일', '%'),
                    ('drawdown52', '52주 최고치 대비', '%'),
                    ('rsi', 'RSI (14일)', '')]
    for name in SIGNAL_TICKERS:
        if name not in states:
            continue
        s = states[name]
        st.markdown(f'**{name}**')
        cols = st.columns(4)
        for col, (key, label, unit) in zip(cols, metric_names):
            val = s[key]
            if pd.isna(val):
                col.metric(label, '계산 불가')
            elif key == 'rsi':
                col.metric(label, f'{val:.1f}')
            else:
                col.metric(label, f'{val:+.1f}{unit}')
    st.caption('이 수치는 지수 가격 기반 지표입니다. 개별 종목의 20·200일선 상회 비율이나 ADR을 뜻하지 않습니다.')

    st.subheader('🔻 매도 압력 · 🔺 반등 확인')
    col_dd, col_ftd = st.columns(2)
    for market, df in datasets.items():
        with col_dd:
            dd = dd_days(df)
            if dd is None:
                st.info(f'{market} · DD: 지수 거래량 유효 자료 부족 → 판정 보류')
            else:
                st.metric(f'{market} · 최근 25거래일 간이 DD', f'{len(dd)}일')
                st.caption('최근 발생일: ' + (', '.join(day.strftime('%m/%d') for day in dd[-4:]) if dd else '없음'))
        with col_ftd:
            if not signal_volume_ok(df):
                st.info(f'{market} · FTD: 지수 거래량 유효 자료 부족 → 판정 보류')
            else:
                ftd = ftd_candidate(df)
                if ftd is None:
                    st.info(f'{market} · 최근 25거래일 간이 FTD 후보 없음')
                else:
                    st.success(f'{market} · 간이 FTD 후보: {ftd:%Y-%m-%d}')
    st.caption('DD: 지수 일봉 하락률 ≤ -0.2%이고 거래량이 전일보다 증가한 날의 단순 합계. FTD는 자체 간이 반등 후보로, 공식 IBD 지표 또는 실제 기관 순매매 자료가 아닙니다.')

    st.subheader('💹 시장 추세 · 이동평균선 상세')
    selected = st.radio('지수', list(SIGNAL_TICKERS), horizontal=True, key='signal_v2_selected')
    if selected in datasets:
        df = datasets[selected]
        fig = go.Figure()
        lines = [('Close', '지수', '#edf2f9', 2.6),
                 ('MA20', 'MA20', '#54c4d8', 1.8),
                 ('MA50', 'MA50', '#e2ad68', 1.8),
                 ('MA200', 'MA200', '#d891a8', 1.8)]
        for key, title, color, width in lines:
            fig.add_trace(go.Scatter(
                x=df.index[-180:], y=df[key].iloc[-180:], mode='lines',
                name=title, line=dict(color=color, width=width),
            ))
        fig.update_layout(
            height=390, margin=dict(t=12, l=6, r=6, b=15),
            hovermode='x unified', legend=dict(orientation='h', y=-.17),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f'{selected} · 기준일 {df.index[-1]:%Y-%m-%d} · Yahoo Finance (일봉)')
    else:
        st.info('차트를 표시할 수 있는 지수 데이터가 없습니다.')

    st.subheader('🧭 다음 확장 · 시장 내부 / 증시 자금')
    c1, c2, c3 = st.columns(3)
    with c1:
        st.info('**시장 내부 체력**\n\nADR · 전 종목 20/200일선 상회 비율 · 신고가/신저가\n\n**과거 전 종목 시세 확보 후 연결**')
    with c2:
        st.info('**증시 자금 여건**\n\n투자자예탁금 · 신용잔고/예탁금 · 신용 오실레이터\n\n**원자료 연동 및 기준일 검증 후 연결**')
    with c3:
        st.info('**실제 외국인·기관 수급**\n\n종목별 일별 순매수 금액은 기존 **자금 흐름** 메뉴에서 확인\n\n**장중 잠정 수급은 보류**')

    with st.expander('🔎 상세 근거 · 계산식 · 한계'):
        st.markdown('''**단기 추세 신호**: 종가 > MA20 및 MA20 > MA50. 각 조건 충족 개수 0/1/2 → 경계/중립/양호.  
**장기 추세 신호**: 종가 > MA200 및 MA50 > MA200. 같은 분류.  
**시장 추세 게이지**: KOSPI·KOSDAQ 각각 4개, 총 8개 조건 충족 비율 × 100. 이동평균 기반이며 검증된 투자 수익률·권장 보유 비중을 의미하지 않습니다.  
**최근 20·60일 성과**: 당일 종가 / N거래일 전 종가 − 1.  
**52주 고점 대비**: 최근 252거래일 최고 종가 대비 현재 종가의 비율.  
**RSI(14)**: 가격 상승폭/하락폭의 Wilder 방식 지수평활 평균 기반.  
**간이 DD**: 최근 25거래일에서 전일보다 지수가 0.2% 이상 하락하고 거래량이 증가한 날. 실제 기관 매도액을 확인하는 지표가 아닙니다.  
**간이 FTD 후보**: 최근 60거래일 최고가 대비 8% 이상 하락했던 국면의 국지적 저점을 찾고, 이후 반등 시도 4~10일차에 지수 +1.5% 이상 상승과 거래량 증가를 확인합니다. 공식 윌리엄 오닐·IBD 신호와 다르고, 신호 유효성을 검증하지 않았습니다.  
**원자료**: Yahoo Finance 지수 일봉. 거래량이 누락된 기간에는 거래량 기반 신호를 계산하지 않으며, 장중 데이터는 종가 확정 전 바뀔 수 있습니다.  
**예정 데이터**: ADR, 시장 전체 상회 비율, 신용잔고·예탁금 등은 원자료 확보 및 확인 전까지 숫자를 만들지 않습니다.''')

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
