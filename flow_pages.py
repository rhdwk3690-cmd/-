"""Miner Terminal / TOP200 + foreign & institutional net trade VALUE (KRW).
KRX fields are KRW. Unofficial Naver fallback accepted ONLY if amount units explicit.
Never convert shares * price into net-buy value.
"""
import json
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

FILE = Path(__file__).resolve().parent / 'data' / 'kr_flow.json'
KST = ZoneInfo('Asia/Seoul')
UA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json, text/plain, */*'}


def _read():
    if not FILE.exists():
        st.error('data/kr_flow.json 파일이 없습니다. 거래대금 수집 작업부터 확인하세요.')
        return None
    try:
        data = json.loads(FILE.read_text(encoding='utf-8'))
        st.caption(f"TOP200 거래 기준일: {data.get('date') or '미검증'} | 수집: {str(data.get('collected_at_kst') or '?')[:16]} | {data.get('source')}")
        if not data.get('date'):
            st.warning('거래대금 TOP200의 거래 기준일이 아직 검증되지 않았습니다. 당일 순위로 해석하지 마세요.')
        return data
    except (OSError, ValueError) as exc:
        st.error(f'거래대금 파일 오류: {exc}')
        return None


def _integer(value):
    if isinstance(value, bool) or value is None:
        return None
    s = str(value).strip().replace(',', '').replace(' ', '').replace('−', '-')
    return int(s) if re.fullmatch(r'[+-]?\d+', s) else None


def _krx_rows(payload):
    if not isinstance(payload, dict):
        return {}
    raw = payload.get('output')
    if not isinstance(raw, list):
        raw = payload.get('OutBlock_1')
    if not isinstance(raw, list):
        return {}
    result = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        code = str(row.get('ISU_SRT_CD') or '').strip()
        value = _integer(row.get('NETBID_TRDVAL'))
        if re.fullmatch(r'\d{6}', code) and value is not None:
            result[code] = value
    return result


def _krx_for_day(day):
    """Read-only KRX public site request. May be blocked or require login."""
    out = {'외국인': {}, '기관': {}}
    errors = []
    uri = 'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
    headers = {**UA, 'Referer':'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd',
               'Origin':'https://data.krx.co.kr', 'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'}
    def fetch_one(label, investor, market):
        form = {'bld':'dbms/MDC/STAT/standard/MDCSTAT02401',
                'strtDd':day, 'endDd':day, 'mktId':market, 'invstTpCd':investor,
                'share':'1', 'money':'1'}
        resp = requests.post(uri, headers=headers, data=form, timeout=6)
        resp.raise_for_status()
        records = _krx_rows(resp.json())
        if not records:
            raise ValueError('종목 코드와 NETBID_TRDVAL 금액 행 없음 (로그인/차단 가능)')
        return records
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch_one, label, investor, market):(label, market)
                for label, investor in [('외국인','9000'),('기관','7050')]
                for market in ('STK','KSQ')}
        for future in as_completed(jobs):
            label, market = jobs[future]
            try:
                out[label].update(future.result())
            except Exception as exc:
                errors.append(f'KRX {label}/{market}: {type(exc).__name__}: {str(exc)[:90]}')
    return out, errors


def _won_text(value):
    """Parse Naver amount only if a KRW unit is unambiguously present."""
    if not isinstance(value, str):
        return None
    s = value.replace(',', '').replace(' ', '').replace('−', '-').replace('＋','+')
    match = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)(원|억원|억|백만원|백만|천만원|천만|조원|조)', s)
    if not match:
        return None
    number, unit = match.groups()
    factors = {'원':1, '억원':10**8, '억':10**8, '백만원':10**6, '백만':10**6,
               '천만원':10**7, '천만':10**7, '조원':10**12, '조':10**12}
    return int(round(float(number) * factors[unit]))


def _naver_rows(payload):
    """Accept only 6-digit ticker and an explicitly unit-tagged net trade amount.
    Do not guess whether plain numeric fields are in KRW/100M/1M/shares.
    """
    results = {}
    def walk(node, depth=0):
        if depth > 5:
            return
        if isinstance(node, list):
            for item in node[:600]:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            codes = ('itemCode', 'stockCode', 'symbolCode', 'ticker', 'code', 'shortCode')
            code = str(next((node[k] for k in codes if k in node and node[k]), '')).strip().removeprefix('A')
            if re.fullmatch(r'\d{6}', code):
                for name in ('netBuyTradeAmount','netBuyAmount','netBuyTradingValue',
                             'netBuyTradeValue','netBuyingAmount','pureBuyAmount',
                             'netPurchaseAmount','netBidTradeValue','순매수거래대금','순매수금액'):
                    if name in node:
                        won = _won_text(node[name])
                        if won is not None:
                            results[code] = won
                            break
            for value in node.values():
                if isinstance(value, (list, dict)):
                    walk(value, depth + 1)
    walk(payload)
    return results


def _naver_fallback():
    results, errors = {'외국인':{}, '기관':{}}, []
    urls = [
        ('legacy', 'https://m.stock.naver.com/front-api/market/tradingTrend/ranking'),
        ('current', 'https://m.stock.naver.com/front-api/api/domestic/market/trend/trendForeignOrg'),
    ]
    for group, inv_legacy, inv_current in [('외국인','foreigner','FOREIGNER'),('기관','institution','ORGANIZATION')]:
        for variant, url in urls:
            try:
                if variant == 'legacy':
                    params = {'periodType':'daily','stockExchangeType':'KRX', 'investorType':inv_legacy,
                              'tradingType':'trendBuy','page':1,'pageSize':200}
                else:
                    params = {'investorType':inv_current, 'tradeType':'KRX', 'marketType':'ALL',
                              'startIdx':0, 'pageSize':200, 'periodType':'DAY'}
                resp = requests.get(url, headers=dict(UA, Referer='https://m.stock.naver.com/'),
                                    params=params, timeout=6)
                resp.raise_for_status()
                amounts = _naver_rows(resp.json())
                if amounts:
                    results[group].update(amounts)
                    break
                errors.append(f'NAVER {group}/{variant}: 금액 단위가 명시된 행을 찾지 못함')
            except Exception as exc:
                errors.append(f'NAVER {group}/{variant}: {type(exc).__name__}: {str(exc)[:85]}')
    return results, errors


@st.cache_data(ttl=1800, show_spinner=False)
def _market_amounts():
    today = datetime.now(KST).date()
    problems = []
    for shift in range(4):
        day = (today - timedelta(days=shift))
        if day.weekday() >= 5:
            continue
        raw, errors = _krx_for_day(day.strftime('%Y%m%d'))
        problems.extend(errors)
        if not raw['외국인'] and not raw['기관']:
            break
        if len(raw['외국인']) >= 25 and len(raw['기관']) >= 25:
            return raw, day.isoformat(), 'KRX NETBID_TRDVAL (원)', problems
    raw, errors = _naver_fallback()
    problems.extend(errors)
    if raw['외국인'] or raw['기관']:
        return raw, None, 'NAVER 비공식 금액 순위 (단위 명시 행만)', problems
    return {'외국인':{}, '기관':{}}, None, '금액 원자료 없음', problems


def _ranked():
    obj = _read()
    if not obj:
        return None
    df = pd.DataFrame(obj.get('top200') or [])
    expected = {'ticker','name','market','close','traded_krw'}
    if df.empty or not expected.issubset(df.columns):
        st.error('TOP200 데이터 열이 누락되었습니다.')
        return None
    df = df.sort_values('traded_krw', ascending=False, kind='stable').reset_index(drop=True)
    df.insert(0, '순위', range(1, len(df)+1))
    return df


def _with_amounts(frame, amounts):
    df = frame.copy()
    codes = df['ticker'].astype(str).str.zfill(6)
    for investor, column in [('외국인','외국인 순매수(억)'),('기관','기관 순매수(억)')]:
        df[column] = pd.to_numeric(codes.map(amounts[investor]), errors='coerce') / 100_000_000
    df['수급 합계(억)'] = df[['외국인 순매수(억)','기관 순매수(억)']].sum(axis=1, min_count=2)
    df['거래대금(억)'] = pd.to_numeric(df['traded_krw'], errors='coerce') / 100_000_000
    df['수급 강도(%)'] = df['수급 합계(억)'] / df['거래대금(억)'].replace(0, float('nan')) * 100
    for c in ['거래대금(억)','외국인 순매수(억)','기관 순매수(억)','수급 합계(억)','수급 강도(%)']:
        df[c] = df[c].round(2)
    return df


def _present_source(source, date, amounts, errors):
    foreign, inst = len(amounts['외국인']), len(amounts['기관'])
    if foreign or inst:
        st.success(f'금액 원자료: {source} | 외국인 {foreign}종목 · 기관 {inst}종목 | 수급 기준일: {date or "응답 내 검증 불가"}')
    else:
        st.error('외국인·기관 순매수 **금액** 수집에 실패했습니다. 자료를 추정하지 않고 빈칸으로 유지합니다.')
    with st.expander(f'금액 수집 진단 로그 ({len(errors)}건)'):
        for x in errors[-28:]:
            st.text(x)
    st.caption('금액은 수량×종가로 추정하지 않습니다. TOP200과 수급의 기준일이 같지 않으면 수급강도(%)는 숨깁니다.')


def cashflow():
    st.title('💸 자금 흐름 | 외국인·기관 순매수 **금액**')
    frame = _ranked()
    if frame is None:
        return
    with st.spinner('외국인·기관 순매수 거래대금 원자료 확인…'):
        amounts, date, source, errors = _market_amounts()
    _present_source(source, date, amounts, errors)
    df = _with_amounts(frame, amounts)
    if not date or date != json.loads(FILE.read_text(encoding='utf-8')).get('date'):
        df['수급 강도(%)'] = float('nan')
    options = ['전체','KOSPI','KOSDAQ']
    market = st.selectbox('시장', options, key='flow_market')
    if market != '전체':
        df = df[df['market'] == market]
    count = st.select_slider('표시할 종목 수', options=[20,50,100,200], value=50, key='flow_money_count')
    df = df.head(count)
    columns = ['순위','name','ticker','외국인 순매수(억)','기관 순매수(억)','수급 합계(억)','수급 강도(%)']
    st.dataframe(df[columns], hide_index=True, use_container_width=True,
                 column_config={'name':'종목명','ticker':'코드'})
    paired = df.dropna(subset=['외국인 순매수(억)','기관 순매수(억)'])
    if not paired.empty:
        top = paired.assign(abs_sum=paired['수급 합계(억)'].abs()).nlargest(20,'abs_sum')
        fig = go.Figure()
        fig.add_bar(x=top['name'], y=top['외국인 순매수(억)'], name='외국인')
        fig.add_bar(x=top['name'], y=top['기관 순매수(억)'], name='기관')
        fig.update_layout(barmode='relative', yaxis_title='억원', height=380)
        st.plotly_chart(fig, use_container_width=True)


def top200():
    st.title('📊 거래대금 TOP 200 | 외국인·기관 순매수 금액')
    frame = _ranked()
    if frame is None:
        return
    with st.spinner('금액 원자료 확인…'):
        amounts, date, source, errors = _market_amounts()
    _present_source(source, date, amounts, errors)
    frame = _with_amounts(frame, amounts)
    if not date or date != json.loads(FILE.read_text(encoding='utf-8')).get('date'):
        frame['수급 강도(%)'] = float('nan')
    market = st.selectbox('시장', ['전체','KOSPI','KOSDAQ'])
    if market != '전체':
        frame = frame[frame['market'] == market]
    term = st.text_input('종목명/종목코드 검색', '').strip()
    if term:
        frame = frame[frame['name'].str.contains(term, case=False, regex=False, na=False) |
                      frame['ticker'].astype(str).str.contains(term, regex=False, na=False)]
    columns = ['순위','name','ticker','market','close','거래대금(억)',
               '외국인 순매수(억)','기관 순매수(억)','수급 합계(억)','수급 강도(%)']
    st.dataframe(frame[columns], use_container_width=True, hide_index=True,
                 column_config={'name':'종목명','ticker':'종목코드','market':'시장','close':'종가'})
    st.caption('순위는 원래 TOP200 전체 거래대금 순위입니다. 수급자료가 없으면 금액이 비어 있습니다.')
    st.download_button('TOP200 금액 수급 CSV 저장', frame[columns].to_csv(index=False).encode('utf-8-sig'),
                       'miner_flow_top200_krw.csv', 'text/csv')
