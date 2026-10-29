"""광부 종합상황판 V2: 검정색 12개 시장 카드 및 클릭형 상세 분석."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from scripts.snapshot_panel import show_cloud_snapshot

MARKETS = [
    ('코스피', '^KS11'), ('코스닥', '^KQ11'),
    ('필라델피아 반도체', '^SOX'), ('대만 가권', '^TWII'),
    ('니케이225', '^N225'), ('나스닥100 선물', 'NQ=F'),
    ('S&P500 선물', 'ES=F'), ('다우 선물', 'YM=F'),
    ('원/달러', 'KRW=X'), ('미국 10년물', '^TNX'),
    ('VIX', '^VIX'), ('WTI 선물', 'CL=F'),
]

ETFS = {
    'KODEX 200': '069500.KS',
    'TIGER 200': '102110.KS',
    'KODEX 반도체': '091160.KS',
    'TIGER 반도체': '091230.KS',
    'KODEX 2차전지산업': '305720.KS',
    'KODEX 은행': '091170.KS',
}

st.markdown('''<style>
.stApp{
    background:#080e16!important;
    color:#eaf3ff!important
}
.stApp [data-testid="stSidebar"]{
    background:#0c1521!important;
    border-right:1px solid #283d51
}
.stApp [data-testid="stSidebar"] *{
    color:#e9f2fc!important
}
.stApp [data-testid="stHeader"]{
    background:#080e16!important
}
.stApp [data-testid="stMarkdownContainer"] h1,
.stApp [data-testid="stMarkdownContainer"] h2,
.stApp [data-testid="stMarkdownContainer"] h3{
    color:#edf5ff!important
}
.stApp [data-testid="stMetric"]{
    background:#122335;
    border:1px solid #314b62;
    border-radius:12px;
    padding:12px
}
.stApp [data-testid="stMetric"] *{
    color:#f0f7ff!important
}
.miner-hero{
    background:linear-gradient(115deg,#102b40,#0b1827);
    border:1px solid #31546b;
    border-radius:17px;
    padding:23px 26px;
    margin-bottom:15px;
    color:#f1f7fc
}
.miner-tag{
    color:#86d4e6;
    letter-spacing:2px;
    font-size:11px;
    font-weight:800
}
.miner-title{
    font-size:30px;
    font-weight:900;
    margin:7px 0
}
.miner-sub{
    color:#b0c5d7;
    font-size:13px
}
.stApp [class*="st-key-overview_tile_"] button{
    background:linear-gradient(145deg,#152a3c,#101c2b)!important;
    border:1px solid #35536a!important;
    border-radius:14px!important;
    color:#f0f7ff!important;
    width:100%;
    min-height:127px;
    padding:13px!important;
    white-space:pre-line!important;
    text-align:left!important;
    justify-content:flex-start!important;
    line-height:1.65!important
}
.stApp [class*="st-key-overview_feature_"] button{
    background:#132538!important;
    border:1px solid #355269!important;
    border-radius:13px!important;
    color:#f0f7ff!important;
    width:100%;
    min-height:90px;
    padding:14px!important;
    white-space:pre-line!important;
    justify-content:flex-start!important;
    text-align:left!important
}
.stApp [class*="st-key-overview_tile_"] button p,
.stApp [class*="st-key-overview_feature_"] button p{
    color:#f0f7ff!important;
    white-space:pre-line!important
}
.stApp [class*="st-key-overview_tile_"] button:hover,
.stApp [class*="st-key-overview_feature_"] button:hover{
    background:#223e51!important;
    border-color:#7bd3eb!important
}
</style>''', unsafe_allow_html=True)


@st.cache_data(ttl=900, show_spinner=False)
def load(ticker, period='10d'):
    df = yf.download(
        ticker,
        period=period,
        interval='1d',
        auto_adjust=False,
        progress=False,
        threads=False,
        timeout=15
    )

    if df is None or df.empty:
        raise ValueError('Yahoo Finance 가격 데이터가 없습니다')

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if 'Close' not in df:
        raise ValueError('종가 데이터가 없습니다')

    df = df.sort_index().copy()
    df['Close'] = pd.to_numeric(
        df['Close'], errors='coerce'
    )
    df = df.dropna(subset=['Close'])

    if len(df) < 2:
        raise ValueError(
            '등락률 계산에 필요한 2거래일 자료가 없습니다'
        )

    return df


def chart(lines, title, zero=False):
    palette = [
        '#f0f6ff',
        '#5dd0e6',
        '#efb96e',
        '#d990ad'
    ]

    fig = go.Figure()

    for i, (label, series) in enumerate(lines):
        s = series.dropna()

        fig.add_trace(
            go.Scatter(
                x=s.index,
                y=s,
                name=label,
                line=dict(
                    color=palette[i % 4],
                    width=2
                )
            )
        )

    if zero:
        fig.add_hline(
            y=0,
            line_dash='dot',
            line_color='#d0bc74'
        )

    fig.update_layout(
        title=title,
        height=375,
        hovermode='x unified',
        paper_bgcolor='#101b29',
        plot_bgcolor='#101b29',
        font=dict(color='#e6f0fa'),
        margin=dict(l=8, r=8, t=45, b=15),
        legend=dict(
            orientation='h',
            y=-.16
        )
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )


def oscillator(df):
    close = df['Close']

    vol = pd.to_numeric(
        df.get(
            'Volume',
            pd.Series(
                index=df.index,
                dtype=float
            )
        ),
        errors='coerce'
    ).reindex(close.index)

    traded = close * vol

    base = traded.rolling(
        20,
        min_periods=20
    ).mean().replace(0, np.nan)

    relative = 100 * (
        traded / base - 1
    )

    return (
        relative.ewm(
            span=5,
            adjust=False
        ).mean()
        -
        relative.ewm(
            span=20,
            adjust=False
        ).mean()
    )


@st.cache_data(ttl=86400, show_spinner=False)
def stock_directory():
    items = {
        '삼성전자': ('005930', 'KOSPI'),
        'SK하이닉스': ('000660', 'KOSPI'),
        '삼성전기': ('009150', 'KOSPI'),
        '삼성전자우': ('005935', 'KOSPI'),
        '현대차': ('005380', 'KOSPI'),
        'NAVER': ('035420', 'KOSPI'),
        '카카오': ('035720', 'KOSPI'),
        'LG에너지솔루션': ('373220', 'KOSPI'),
    }

    file = (
        Path(__file__).resolve().parents[1]
        / 'data'
        / 'kr_flow.json'
    )

    if file.exists():
        try:
            data = json.loads(
                file.read_text(encoding='utf-8')
            )

            for row in data.get('top200', []):
                code = str(
                    row.get('ticker', '')
                ).zfill(6)

                name = str(
                    row.get('name', '')
                ).strip()

                market = str(
                    row.get('market', '')
                ).upper()

                if (
                    name
                    and re.fullmatch(r'\d{6}', code)
                    and market in ('KOSPI', 'KOSDAQ')
                ):
                    items[name] = (code, market)

        except (OSError, ValueError, TypeError):
            pass

    source = '기본 종목 + 저장된 TOP200'

    try:
        import FinanceDataReader as fdr

        listing = fdr.StockListing('KRX')

        if (
            listing is not None
            and {'Code', 'Name'}.issubset(
                listing.columns
            )
        ):
            added = 0

            for _, row in listing.iterrows():
                code = str(
                    row['Code']
                ).zfill(6)

                name = str(
                    row['Name']
                ).strip()

                market = str(
                    row.get(
                        'Market',
                        row.get('MarketId', '')
                    )
                ).upper()

                market = (
                    'KOSPI'
                    if market in (
                        'KOSPI', 'STK', 'KS'
                    )
                    else 'KOSDAQ'
                    if market in (
                        'KOSDAQ', 'KSQ', 'KQ'
                    )
                    else ''
                )

                if (
                    name
                    and market
                    and re.fullmatch(r'\d{6}', code)
                ):
                    items[name] = (code, market)
                    added += 1

            if added > 100:
                source = (
                    'FinanceDataReader KRX 목록'
                )

    except Exception:
        pass

    return items, source


def navigate(target):
    st.session_state[
        'miner_overview_page'
    ] = target

    st.rerun()


if 'miner_overview_page' not in st.session_state:
    st.session_state[
        'miner_overview_page'
    ] = 'home'

page = st.session_state[
    'miner_overview_page'
]

st.markdown('''
<div class="miner-hero">
  <div class="miner-tag">
    ⛏ MINER'S TERMINAL · GLOBAL OVERVIEW V2
  </div>
  <div class="miner-title">
    글로벌 시장을 한눈에
  </div>
  <div class="miner-sub">
    12개 시장 카드 · 클릭형 상세 분석 · 다크 투자 터미널
  </div>
</div>
''', unsafe_allow_html=True)


# =====================================
# 메인 화면
# =====================================

if page == 'home':

    if st.button(
        '🔄 Yahoo 데이터 새로 조회',
        key='overview_reload'
    ):
        load.clear()
        st.rerun()

    st.caption(
        'Yahoo Finance 지연·일봉 데이터 · '
        '각 시장의 기준일이 다를 수 있으며 '
        '실시간 확정 시세가 아닙니다'
    )

    st.subheader(
        '🌐 글로벌 주요 시장 12'
    )

    # 4열 × 3행
    for start in (0, 4, 8):
        columns = st.columns(
            4,
            gap='small'
        )

        for j, col in enumerate(columns):
            i = start + j

            name, ticker = MARKETS[i]

            with col:
                try:
                    p = load(ticker)['Close']

                    change = 100 * (
                        float(p.iloc[-1])
                        /
                        float(p.iloc[-2])
                        - 1
                    )

                    marker = (
                        '🟢'
                        if change >= 0
                        else '🔴'
                    )

                    label = (
                        f'{name}\n'
                        f'{p.iloc[-1]:,.2f}  '
                        f'{marker} {change:+.2f}%\n'
                        f'{p.index[-1]:%Y-%m-%d} · 상세 ↗'
                    )

                    ok = True

                except Exception:
                    label = (
                        f'{name}\n'
                        '가격 조회 대기 · 새로 조회'
                    )
                    ok = False

                if st.button(
                    label,
                    key=f'overview_tile_{i}',
                    disabled=not ok,
                    use_container_width=True
                ):
                    navigate(
                        f'market:{i}'
                    )

    st.caption(
        '미국 10년물(^TNX)은 Yahoo 원표기값입니다. '
        '선물 연속 시세는 만기 교체에 따른 '
        '불연속이 생길 수 있습니다.'
    )

    st.subheader(
        '🧭 빠른 상세 분석'
    )

    features = [
        (
            'oil',
            '🛢️ 유가 분석',
            'WTI · Brent · 가격 추세'
        ),
        (
            'etf',
            '📦 ETF 거래활동',
            'ETF 가격 · 거래활동 오실레이터'
        ),
        (
            'stock',
            '🔎 개별 종목',
            '종목명 검색 · 이동평균 · 오실레이터'
        ),
        (
            'cloud',
            '📡 클라우드 수집',
            '저장 시세와 데이터 수집 현황'
        ),
    ]

    for start in (0, 2):
        cols = st.columns(
            2,
            gap='small'
        )

        for j, col in enumerate(cols):
            target, title, subtitle = (
                features[start + j]
            )

            with col:
                if st.button(
                    f'{title}\n'
                    f'{subtitle}\n'
                    '↗ 상세 보기',
                    key=f'overview_feature_{target}',
                    use_container_width=True
                ):
                    navigate(target)

    st.caption(
        '시장 신호·자금 흐름·TOP200은 '
        '왼쪽의 독립 메뉴에서 확인합니다.'
    )


# =====================================
# 클릭한 상세 화면
# =====================================

else:

    if st.button(
        '← 종합 상황판으로 돌아가기',
        key='overview_back'
    ):
        navigate('home')

    # 시장 지표 상세
    if page.startswith('market:'):
        i = int(
            page.split(':', 1)[1]
        )

        name, ticker = MARKETS[i]

        st.subheader(
            f'📈 {name} · 상세 차트'
        )

        try:
            p = load(
                ticker,
                '2y'
            )['Close']

            change = 100 * (
                float(p.iloc[-1])
                /
                float(p.iloc[-2])
                - 1
            )

            a, b, c = st.columns(3)

            a.metric(
                '최근 표시값',
                f'{p.iloc[-1]:,.2f}',
                f'{change:+.2f}%'
            )

            b.metric(
                'MA20',
                f'{p.rolling(20).mean().iloc[-1]:,.2f}'
            )

            c.metric(
                'MA60',
                f'{p.rolling(60).mean().iloc[-1]:,.2f}'
            )

            days = st.select_slider(
                '차트 기간',
                options=[65, 130, 260, 520],
                value=260,
                format_func=lambda n: {
                    65: '3개월',
                    130: '6개월',
                    260: '1년',
                    520: '2년'
                }[n]
            )

            chart(
                [
                    (
                        '가격',
                        p.tail(days)
                    ),
                    (
                        'MA20',
                        p.rolling(20).mean().tail(days)
                    ),
                    (
                        'MA60',
                        p.rolling(60).mean().tail(days)
                    ),
                    (
                        'MA200',
                        p.rolling(200).mean().tail(days)
                    )
                ],
                name
            )

            st.caption(
                f'{ticker} · 데이터 기준일 '
                f'{p.index[-1]:%Y-%m-%d} · '
                'Yahoo Finance · 실시간 아님'
            )

        except Exception as exc:
            st.error(
                f'{name} 조회 실패: {exc}'
            )

    # 유가 상세
    elif page == 'oil':

        st.subheader(
            '🛢️ 유가 분석 · WTI / Brent'
        )

        for col, name, ticker in zip(
            st.columns(2),
            ['WTI', 'Brent'],
            ['CL=F', 'BZ=F']
        ):

            with col:
                try:
                    p = load(
                        ticker,
                        '2y'
                    )['Close']

                    st.metric(
                        f'{name} 선물',
                        f'${p.iloc[-1]:,.2f}'
                    )

                    chart(
                        [
                            (
                                '가격',
                                p.tail(252)
                            ),
                            (
                                'MA20',
                                p.rolling(20).mean().tail(252)
                            ),
                            (
                                'MA60',
                                p.rolling(60).mean().tail(252)
                            )
                        ],
                        name
                    )

                    st.caption(
                        f'{p.index[-1]:%Y-%m-%d} · '
                        '선물 가격이며 현물 유가와 다름'
                    )

                except Exception as exc:
                    st.warning(
                        f'{name} 조회 실패: {exc}'
                    )

    # ETF 상세
    elif page == 'etf':

        st.subheader(
            '📦 ETF 거래활동'
        )

        st.warning(
            '가격×거래량으로 계산한 거래활동 '
            '오실레이터는 ETF 설정·환매를 통한 '
            '실제 순유입액이 아닙니다.'
        )

        name = st.selectbox(
            'ETF 선택',
            list(ETFS),
            key='overview_etf'
        )

        try:
            df = load(
                ETFS[name],
                '2y'
            )

            p = df['Close']
            o = oscillator(df).dropna()

            a, b = st.columns(2)

            with a:
                chart(
                    [
                        (
                            'ETF 가격',
                            p.tail(252)
                        )
                    ],
                    'ETF 가격'
                )

            with b:
                chart(
                    [
                        (
                            '거래활동 OSC',
                            o.tail(252)
                        )
                    ],
                    '거래활동 오실레이터',
                    zero=True
                )

            st.caption(
                f'기준일 {p.index[-1]:%Y-%m-%d} · '
                '상대 거래대금의 EMA5−EMA20'
            )

        except Exception as exc:
            st.error(
                f'ETF 조회 실패: {exc}'
            )

        st.info(
            'ETF 실제 순유입은 설정·환매 '
            '또는 상장좌수 원자료 확보 후 연결합니다.'
        )

    # 개별 종목 상세
    elif page == 'stock':

        st.subheader(
            '🔎 개별 종목 검색'
        )

        names, source = stock_directory()

        query = st.text_input(
            '종목명 또는 티커',
            value='삼성전자',
            placeholder=(
                '삼성전자, SK하이닉스, '
                '005930, NVDA'
            ),
            key='overview_stock_query'
        ).strip()

        ticker = None

        if re.fullmatch(r'\d{6}', query):

            market = st.selectbox(
                '거래 시장',
                ['KOSPI', 'KOSDAQ'],
                key='overview_stock_exchange'
            )

            ticker = query + (
                '.KS'
                if market == 'KOSPI'
                else '.KQ'
            )

        elif query:

            matches = [
                (n, c, m)
                for n, (c, m) in names.items()
                if query.casefold() in n.casefold()
            ]

            matches.sort(
                key=lambda x: (
                    x[0].casefold()
                    != query.casefold(),
                    len(x[0]),
                    x[0]
                )
            )

            if matches:

                options = matches[:60]

                selected = st.selectbox(
                    '검색 결과',
                    range(len(options)),
                    format_func=lambda i: (
                        f'{options[i][0]} · '
                        f'{options[i][1]} · '
                        f'{options[i][2]}'
                    ),
                    key='overview_stock_result'
                )

                _, code, market = (
                    options[selected]
                )

                ticker = code + (
                    '.KS'
                    if market == 'KOSPI'
                    else '.KQ'
                )

            elif re.fullmatch(
                r'[A-Za-z][A-Za-z0-9.\-^=]{0,24}',
                query
            ):
                ticker = query.upper()

            else:
                st.warning(
                    '종목을 찾지 못했습니다. '
                    '6자리 종목코드나 '
                    'Yahoo 티커를 입력하세요.'
                )

        st.caption(
            f'종목 목록: {source} · '
            f'선택 티커: {ticker or "없음"}'
        )

        if ticker:

            try:
                df = load(
                    ticker,
                    '2y'
                )

                p = df['Close']

                change = 100 * (
                    float(p.iloc[-1])
                    /
                    float(p.iloc[-2])
                    - 1
                )

                st.metric(
                    '최근 종가',
                    f'{p.iloc[-1]:,.2f}',
                    f'{change:+.2f}%'
                )

                a, b = st.columns(2)

                with a:
                    chart(
                        [
                            (
                                '종가',
                                p.tail(252)
                            ),
                            (
                                'MA20',
                                p.rolling(20).mean().tail(252)
                            ),
                            (
                                'MA60',
                                p.rolling(60).mean().tail(252)
                            ),
                            (
                                'MA200',
                                p.rolling(200).mean().tail(252)
                            )
                        ],
                        '종목 가격'
                    )

                with b:
                    chart(
                        [
                            (
                                '거래활동 OSC',
                                oscillator(df).dropna().tail(252)
                            )
                        ],
                        '거래활동 오실레이터',
                        zero=True
                    )

                st.caption(
                    f'가격 기준일 '
                    f'{p.index[-1]:%Y-%m-%d} · '
                    'Yahoo Finance · 순매수 추정치 아님'
                )

            except Exception as exc:
                st.error(
                    f'종목 조회 실패: {exc}'
                )

    # 클라우드 수집 현황
    elif page == 'cloud':

        st.subheader(
            '📡 클라우드 데이터 수집 현황'
        )

        show_cloud_snapshot()


st.caption(
    '⛏️ 광부 종합상황판 V2 · '
    '지연 시세 및 자료 오류 가능 · 투자 참고용'
)

# 새로 조회 / 돌아가기 버튼 글씨 가독성 수정
st.markdown("""
<style>
.stApp [class*="st-key-overview_reload"] button,
.stApp [class*="st-key-overview_reload"] button *,
.stApp [class*="st-key-overview_back"] button,
.stApp [class*="st-key-overview_back"] button * {
    color: #111827 !important;
    -webkit-text-fill-color: #111827 !important;
    opacity: 1 !important;
    font-weight: 700 !important;
}
</style>
""", unsafe_allow_html=True)
