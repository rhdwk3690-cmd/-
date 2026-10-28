"""광부 투자터미널: TOP200와 외국인·기관 순매수 금액.
금액이 직접 게시된 자료만 사용하고, 수량에 주가를 곱해 추정하지 않습니다.
"""
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

DATA = Path(__file__).resolve().parent / 'data' / 'kr_flow.json'
KST = ZoneInfo('Asia/Seoul')
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/html,*/*'}


def _norm(text):
    return re.sub(r'\s+', '', str(text)).casefold()


def _date(text):
    s = str(text or '').strip().replace('-', '')
    if re.fullmatch(r'20\d{6}', s):
        try:
            return datetime.strptime(s, '%Y%m%d').date().isoformat()
        except ValueError:
            pass
    return None


def _amount(text):
    """Convert explicitly unit-tagged money amounts to 100 million KRW."""
    if not isinstance(text, str):
        return None
    s = re.sub(r'\s+', '', text).replace(',', '').replace('−', '-').replace('＋', '+')
    m = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)(조원|억원|백만원|천만원|조|억|원)', s)
    if not m:
        return None
    factors = {'조원': 10000, '조': 10000, '억원': 1, '억': 1,
               '천만원': .1, '백만원': .01, '원': .00000001}
    return round(float(m.group(1)) * factors[m.group(2)], 4)


def _read_ranked():
    if not DATA.exists():
        st.error('data/kr_flow.json 파일이 없습니다.')
        return None, None
    try:
        obj = json.loads(DATA.read_text(encoding='utf-8'))
        df = pd.DataFrame(obj.get('top200') or [])
        required = {'ticker', 'name', 'market', 'traded_krw', 'close'}
        if df.empty or not required.issubset(df.columns):
            st.error('TOP 200 데이터가 비어 있거나 컬럼이 부족합니다.')
            return None, obj
        df = df.sort_values('traded_krw', ascending=False, kind='stable').reset_index(drop=True)
        df.insert(0, '순위', range(1, len(df) + 1))
        st.caption(f"TOP200 거래 기준일: {obj.get('date') or '미검증'} | {obj.get('source', '')}")
        if not obj.get('date'):
            st.warning('TOP200 거래 기준일이 미검증입니다. 수급 기준일과 같다고 가정하지 않습니다.')
        return df, obj
    except Exception as exc:
        st.error(f'TOP200 읽기 실패: {exc}')
        return None, None


def _naver_amount_rows(payload):
    """Reject numerical values when currency unit or trade date is ambiguous."""
    result = {}
    dates = set()

    def walk(obj, depth=0):
        if depth > 6:
            return
        if isinstance(obj, list):
            for x in obj[:500]:
                walk(x, depth + 1)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k.casefold() in (
                    'bizdate', 'basedate', 'tradedate',
                    'rankingbaseat', 'baseat', 'date'
                ):
                    day = _date(str(v)[:10])
                    if day:
                        dates.add(day)

            rawcode = next(
                (obj.get(k) for k in (
                    'itemCode', 'stockCode', 'symbolCode',
                    'ticker', 'code', 'shortCode'
                ) if obj.get(k)),
                None
            )
            code = str(rawcode or '').lstrip('A')
            if re.fullmatch(r'\d{6}', code):
                for key in (
                    'netBuyAmount', 'netBuyTradeAmount',
                    'netBuyTradeValue', 'netPurchaseAmount',
                    'pureBuyAmount', 'netBuyingAmount',
                    'netBidTradeValue', 'foreignPureBuyAmount',
                    'organizationPureBuyAmount'
                ):
                    if key in obj:
                        value = _amount(obj[key])
                        if value is not None:
                            result[code] = value
                            break

            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)

    walk(payload)
    if len(dates) != 1:
        return {}, None, f'응답 날짜 미확정/복수({len(dates)}개)'
    return result, next(iter(dates)), None


class _TextCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignore += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.ignore:
            self.ignore -= 1

    def handle_data(self, data):
        if not self.ignore and data.strip():
            self.chunks.append(data.strip())


def _parse_public_ranking(html, names):
    """Only labeled 1-day positive net-buy rankings. Missing rows are NOT zeros."""
    parser = _TextCollector()
    parser.feed(html)
    text = ' '.join(parser.chunks)

    stamp = re.search(r'최근\s*거래일\s*(20\d{2}-\d{2}-\d{2})\s*기준', text)
    if not stamp:
        return {'외국인': {}, '기관': {}}, None, '수급 기준일이 없어 폐기'

    date = stamp.group(1)
    markers = list(re.finditer(r'\b1\s*영업일\s*누적', text))
    blocks = [
        text[m.end(): (
            markers[i + 1].start() if i + 1 < len(markers) else len(text)
        )]
        for i, m in enumerate(markers[:2])
    ]
    if not blocks:
        return {'외국인': {}, '기관': {}}, date, '1영업일 표를 찾지 못함'

    parsed = {'외국인': {}, '기관': {}}
    labels = {
        '외국인': (r'외국인\s*순매수\s*상위', r'기관\s*순매수\s*상위'),
        '기관': (r'기관\s*순매수\s*상위', r'개인\s*순매수\s*상위')
    }
    pattern = re.compile(
        r'(?<!\d)(?:[1-9]|10)\s+'
        r'([\w. &()가-힣·-]{1,45}?)\s+'
        r'([+\-−]?(?:\d[\d,]*)(?:\.\d+)?\s*(?:억|조)(?:원)?)'
    )

    for block in blocks:
        for investor, (start, end) in labels.items():
            first = re.search(start, block)
            if not first:
                continue
            tail = block[first.end():]
            last = re.search(end, tail)
            part = tail[:last.start()] if last else tail[:1500]
            for name, money in pattern.findall(part):
                code = names.get(_norm(name))
                value = _amount(money)
                if code and value is not None:
                    parsed[investor][code] = value

    return parsed, date, None


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_amounts(catalog_items):
    catalog = {_norm(name): code for name, code in catalog_items}
    logs = []
    result = {'외국인': {}, '기관': {}}
    dates = {}

    url = 'https://stock.naver.com/api/domestic/market/trend/trendForeignOrg'
    for kind, investor in [
        ('외국인', 'FOREIGNER'),
        ('기관', 'ORGANIZATION')
    ]:
        try:
            response = requests.get(
                url,
                params={
                    'investorType': investor,
                    'tradeType': 'KRX',
                    'marketType': 'ALL',
                    'startIdx': 0,
                    'pageSize': 200,
                    'periodType': 'DAY'
                },
                headers=dict(HEADERS, Referer='https://stock.naver.com/'),
                timeout=7
            )
            response.raise_for_status()
            body = response.json()
            rows, day, problem = _naver_amount_rows(body)
            keys = list(body)[:8] if isinstance(body, dict) else 'list'
            logs.append(
                f'NAVER {kind}: HTTP {response.status_code}; '
                f'금액 {len(rows)}개; 날짜 {day}; '
                f'{problem or "정상"}; 응답 키 {keys}'
            )
            if rows and day:
                result[kind] = rows
                dates[kind] = day
        except Exception as exc:
            logs.append(f'NAVER {kind}: {type(exc).__name__}: {str(exc)[:145]}')

    if (
        result['외국인'] and result['기관']
        and len(set(dates.values())) == 1
    ):
        return (
            result, next(iter(dates.values())),
            '네이버 비공식 금액 자료(단위 명시)', logs
        )

    # The fallback has explicitly published KRW units and trading date.
    # It contains only TOP net-buy entries, NOT the complete market.
    try:
        response = requests.get(
            'https://koscanner.com/flow/',
            headers=HEADERS,
            timeout=9
        )
        response.raise_for_status()
        amounts, day, problem = _parse_public_ranking(
            response.text, catalog
        )
        logs.append(
            f'공개 수급 순위: HTTP {response.status_code}; '
            f'외국인 {len(amounts["외국인"])}개 · '
            f'기관 {len(amounts["기관"])}개; {problem or "정상"}'
        )
        if amounts['외국인'] or amounts['기관']:
            return (
                amounts, day,
                '코스캐너 공개 상위 순매수(제3자 집계, KRX+NXT)',
                logs
            )
    except Exception as exc:
        logs.append(f'공개 수급 순위: {type(exc).__name__}: {str(exc)[:145]}')

    if result['외국인'] or result['기관']:
        if len(set(dates.values())) == 1:
            return (
                result, next(iter(dates.values())),
                '네이버 비공식 금액 자료(부분 조회)', logs
            )

    return (
        {'외국인': {}, '기관': {}}, None,
        '금액 조회 실패', logs
    )


def _data():
    df, rankinfo = _read_ranked()
    if df is None:
        return None

    catalog = tuple(
        (str(row['name']), str(row['ticker']).zfill(6))
        for _, row in df.iterrows()
    )
    with st.spinner('외국인·기관 순매수 금액 조회 중…'):
        amounts, date, source, logs = _fetch_amounts(catalog)

    st.caption(
        f'수급 출처: {source} | 기준일: {date or "미확인"} | '
        f'외국인 {len(amounts["외국인"])}종목 · '
        f'기관 {len(amounts["기관"])}종목'
    )
    if not amounts['외국인'] and not amounts['기관']:
        st.error('금액 원자료를 확보하지 못했습니다. 추정치로 대체하지 않습니다.')
    else:
        st.info(
            '공개 상위 순매수 목록은 일부 종목만 제공합니다. '
            '빈칸은 순매도나 0원이 아니라 미확보입니다. '
            '제3자 자료는 KRX 원본과 독립 대조 전입니다.'
        )

    with st.expander(f'수급 수집 진단 ({len(logs)}건)'):
        for msg in logs:
            st.text(msg)

    if source.startswith('코스캐너'):
        st.link_button(
            '원자료 페이지 열기',
            'https://koscanner.com/flow/'
        )

    codes = df['ticker'].astype(str).str.zfill(6)
    df['외국인 순매수(억)'] = codes.map(
        amounts['외국인']
    ).astype('Float64')
    df['기관 순매수(억)'] = codes.map(
        amounts['기관']
    ).astype('Float64')
    df['수급 합계(억)'] = (
        df['외국인 순매수(억)'] + df['기관 순매수(억)']
    )
    df['거래대금(억)'] = (
        pd.to_numeric(df['traded_krw'], errors='coerce') / 1e8
    ).round(1)
    df['수급 기준일'] = date

    if date and rankinfo.get('date') == date:
        df['수급 강도(%)'] = (
            df['수급 합계(억)']
            / df['거래대금(억)'].replace(0, float('nan'))
            * 100
        ).round(2)
    else:
        df['수급 강도(%)'] = pd.NA
    return df


def cashflow():
    st.title('💸 자금 흐름 | 외국인·기관 순매수 금액')
    df = _data()
    if df is None:
        return

    market = st.selectbox(
        '시장', ['전체', 'KOSPI', 'KOSDAQ'],
        key='cash_market'
    )
    if market != '전체':
        df = df[df['market'] == market]

    limit = st.select_slider(
        '표시 종목 수',
        options=[20, 50, 100, 200],
        value=50,
        key='cash_limit'
    )
    df = df.head(limit)
    columns = [
        '순위', 'name', '수급 기준일',
        '외국인 순매수(억)', '기관 순매수(억)',
        '수급 합계(억)'
    ]
    st.dataframe(
        df[columns],
        use_container_width=True,
        hide_index=True,
        column_config={'name': '종목명'}
    )

    paired = df.dropna(
        subset=['외국인 순매수(억)', '기관 순매수(억)']
    )
    if not paired.empty:
        graph = go.Figure()
        subset = paired.nlargest(15, '거래대금(억)')
        graph.add_bar(
            x=subset['name'],
            y=subset['외국인 순매수(억)'].astype(float),
            name='외국인'
        )
        graph.add_bar(
            x=subset['name'],
            y=subset['기관 순매수(억)'].astype(float),
            name='기관'
        )
        graph.update_layout(
            barmode='relative', height=350, yaxis_title='억원'
        )
        st.plotly_chart(graph, use_container_width=True)


def top200():
    st.title('📊 거래대금 TOP 200 | 외국인·기관 순매수 금액')
    df = _data()
    if df is None:
        return

    market = st.selectbox(
        '시장', ['전체', 'KOSPI', 'KOSDAQ'],
        key='top_market'
    )
    if market != '전체':
        df = df[df['market'] == market]

    query = st.text_input('종목명 / 종목코드 검색', '').strip()
    if query:
        df = df[
            df['name'].str.contains(
                query, regex=False, case=False, na=False
            )
            | df['ticker'].astype(str).str.contains(
                query, regex=False, na=False
            )
        ]

    columns = [
        '순위', 'name', 'ticker', 'market', 'close',
        '거래대금(억)', '수급 기준일',
        '외국인 순매수(억)', '기관 순매수(억)',
        '수급 합계(억)', '수급 강도(%)'
    ]
    st.dataframe(
        df[columns],
        hide_index=True,
        use_container_width=True,
        column_config={
            'name': '종목명',
            'ticker': '코드',
            'market': '시장',
            'close': '종가'
        }
    )
    st.caption(
        'TOP200 원래 순위는 유지됩니다. '
        '순매도 종목은 상위 순매수 목록에 없을 수 있습니다. '
        '따라서 금액 빈칸을 0으로 취급하지 마세요.'
    )
    st.download_button(
        'TOP200 CSV 저장',
        df[columns].to_csv(index=False).encode('utf-8-sig'),
        'miner_investor_amounts_partial.csv',
        'text/csv'
    )
