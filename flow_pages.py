"""광부 투자터미널: 거래대금 TOP200 + 네이버 공개 화면의 종목별 외국인·기관 순매수 수량.

주의: 이것은 금융 데이터 재배포용 공식 API가 아니다. 수량(주)을 금액(원)으로 환산하지 않는다.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

FILE = Path(__file__).resolve().parent / 'data' / 'kr_flow.json'
SEOUL = ZoneInfo('Asia/Seoul')


def _read():
    if not FILE.exists():
        st.warning('거래대금 TOP 200 파일이 없습니다. GitHub Actions에서 Collect KR flows (EOD)를 실행하세요.')
        return None
    try:
        obj = json.loads(FILE.read_text(encoding='utf-8'))
        st.caption(f"거래대금 기준일: {obj.get('date') or '미확인'} | 수집 시각: {str(obj.get('collected_at_kst') or '미확인')[:16]} KST | 출처: {obj.get('source', '미확인')}")
        if not obj.get('date'):
            st.warning('거래대금 TOP 200의 거래 기준일이 검증되지 않았습니다. 당일 순위로 단정하지 마세요.')
        if obj.get('status') not in ('ok', 'partial'):
            st.error('거래대금 데이터 수집 실패')
        with st.expander('거래대금 수집 오류 및 진단'):
            for err in obj.get('errors', [])[-20:]:
                st.text(err)
        return obj
    except (OSError, ValueError, TypeError) as exc:
        st.error(f'거래대금 파일을 읽지 못했습니다: {exc}')
        return None


def _parse_shares(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip().replace(',', '').replace(' ', '').replace('＋', '+').replace('−', '-')
    if re.fullmatch(r'[+-]?\d+', s):
        return int(s)
    return None


def _date(value):
    s = str(value or '').strip()
    if re.fullmatch(r'\d{8}', s):
        try:
            return datetime.strptime(s, '%Y%m%d').date().isoformat()
        except ValueError:
            pass
    return None


def _parse_investor_payload(code, data):
    if not isinstance(data, dict) or not isinstance(data.get('dealTrendInfos'), list):
        raise ValueError('dealTrendInfos 목록을 찾지 못함 (API 응답 구조 확인 필요)')
    rows = []
    today = datetime.now(SEOUL).date()
    for entry in data['dealTrendInfos']:
        if not isinstance(entry, dict):
            continue
        date_str = _date(entry.get('bizdate'))
        if not date_str:
            continue
        date_value = datetime.strptime(date_str, '%Y-%m-%d').date()
        if date_value > today or (today - date_value).days > 21:
            continue
        f = _parse_shares(entry.get('foreignerPureBuyQuant'))
        i = _parse_shares(entry.get('organPureBuyQuant'))
        if f is None and i is None:
            continue
        rows.append({'ticker': code, 'date': date_str, 'foreign_net_shares': f,
                     'institution_net_shares': i, 'source': 'Naver Finance (unofficial JSON)'})
    if not rows:
        raise ValueError('유효한 거래일·순매수 수량 데이터 없음')
    rows.sort(key=lambda x: x['date'], reverse=True)
    return rows


def _fetch_one(code):
    if not re.fullmatch(r'\d{6}', code):
        raise ValueError('잘못된 종목코드')
    url = f'https://m.stock.naver.com/api/stock/{code}/integration'
    response = requests.get(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; MinerResearch/1.0)',
        'Accept': 'application/json', 'Referer': 'https://m.stock.naver.com/'}, timeout=7)
    response.raise_for_status()
    return _parse_investor_payload(code, response.json())


@st.cache_data(ttl=1800, show_spinner=False)
def _investors(codes):
    records, errors = {}, []
    codes = tuple(dict.fromkeys(str(code).zfill(6) for code in codes))[:50]
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(_fetch_one, code): code for code in codes}
        for job in as_completed(jobs):
            code = jobs[job]
            try:
                records[code] = job.result()
            except Exception as exc:
                errors.append(f'{code}: {type(exc).__name__} ({str(exc)[:90]})')
    return records, errors


def _attach(df, count, extra_codes=()):
    selected = df.head(count)
    codes = list(selected['ticker'].astype(str).str.zfill(6))
    for code in extra_codes:
        code = str(code).zfill(6)
        if code not in codes:
            codes.append(code)
    records, errors = _investors(tuple(codes))
    by_code = {code: history[0] for code, history in records.items() if history}
    enriched = df.copy()
    enriched['수급 기준일'] = enriched['ticker'].astype(str).str.zfill(6).map(
        lambda code: (by_code.get(code) or {}).get('date'))
    enriched['외국인 순매수(주)'] = enriched['ticker'].astype(str).str.zfill(6).map(
        lambda code: (by_code.get(code) or {}).get('foreign_net_shares'))
    enriched['기관 순매수(주)'] = enriched['ticker'].astype(str).str.zfill(6).map(
        lambda code: (by_code.get(code) or {}).get('institution_net_shares'))
    return enriched, records, errors


def _flow_message(records, errors, count):
    if records:
        dates = sorted({history[0]['date'] for history in records.values() if history}, reverse=True)
        st.success(f'수급 조회 {len(records)}/{count}종목 · 자료 날짜: {", ".join(dates[:4])} · 단위: 주식 수량(주)')
    else:
        st.error('네이버 종목별 순매수 자료를 가져오지 못했습니다. 기존 거래대금 목록은 그대로 유지됩니다.')
    if errors:
        with st.expander(f'종목별 조회 실패 {len(errors)}건'):
            for error in errors[:50]:
                st.text(error)
    st.caption('외국인·기관 순매수 수량은 거래대금이 아니며, 수량×종가를 실제 순매수 금액으로 간주하지 않습니다. '
               '네이버의 비공식 웹 응답으로, 공인된 KRX 확정 자료나 실시간 API로 보장되지 않습니다.')


def cashflow():
    st.title('💸 자금 흐름 | 외국인·기관 종목별 순매수')
    obj = _read()
    if obj is None:
        return
    raw = pd.DataFrame(obj.get('top200') or [])
    if raw.empty:
        st.warning('TOP 200 원자료가 없습니다.')
        return
    st.info('시장 전체의 순매수 금액은 아직 연결되지 않았습니다. 아래는 일부 상위 거래대금 종목의 순매수 수량(주)입니다.')
    count = st.select_slider('수급을 조회할 거래대금 상위 종목 수', options=[10, 20, 30, 50], value=20, key='cashflow_count')
    raw = raw.sort_values('traded_krw', ascending=False).reset_index(drop=True)
    with st.spinner('종목별 외국인·기관 수급 수량 조회 중…'):
        frame, histories, errors = _attach(raw, count)
    _flow_message(histories, errors, count)
    frame = frame.iloc[:count].dropna(subset=['외국인 순매수(주)', '기관 순매수(주)'], how='all').copy()
    if frame.empty:
        return
    frame['종목'] = frame['name']
    st.dataframe(frame[['종목', 'ticker', '수급 기준일', '외국인 순매수(주)', '기관 순매수(주)']],
                 hide_index=True, use_container_width=True)
    dates = frame['수급 기준일'].dropna().value_counts()
    if dates.empty:
        return
    dominant_date = dates.index[0]
    same = frame[frame['수급 기준일'] == dominant_date]
    st.subheader(f'외국인·기관 종목별 순매수 수량 비교 · {dominant_date}')
    chart = go.Figure()
    for key, label in [('외국인 순매수(주)', '외국인'), ('기관 순매수(주)', '기관')]:
        chart.add_trace(go.Bar(x=same['종목'], y=same[key], name=label))
    chart.update_layout(barmode='group', height=360, yaxis_title='순매수 (주)', margin=dict(l=10,r=10,t=35,b=60))
    st.plotly_chart(chart, use_container_width=True)
    st.caption('각 종목의 수급 날짜가 다르면 가장 많이 관측된 날짜만 차트에 포함합니다. 서로 다른 종목의 주식 수량을 합쳐 시장 총수급으로 표시하지 않습니다.')


def top200():
    st.title('📊 거래대금 TOP 200 | 국내 주식')
    obj = _read()
    if obj is None:
        return
    frame = pd.DataFrame(obj.get('top200') or [])
    if frame.empty:
        st.warning('TOP 200 거래대금 데이터가 없습니다.')
        return
    frame = frame.sort_values('traded_krw', ascending=False, kind='stable').reset_index(drop=True)
    frame.insert(0, '순위', range(1, len(frame) + 1))
    st.caption('아래 수급 컬럼은 비공식 네이버 자료의 순매수 수량(주)입니다. 실제 순매수 금액(원)은 아직 미연동입니다.')
    limit = st.select_slider('외국인·기관 수급 조회 범위 (전체 거래대금 순위 기준)',
                             options=[10,20,30,50], value=20, key='top_flow_count')
    market = st.selectbox('시장', ['전체','KOSPI','KOSDAQ'])
    term = st.text_input('종목명 / 종목코드 검색', '').strip()
    match = frame
    if market != '전체':
        match = match[match['market'] == market].copy()
    if term:
        match = match[match['name'].str.contains(term, case=False, regex=False, na=False) |
                      match['ticker'].astype(str).str.contains(term, regex=False, na=False)].copy()
    extras = tuple(match['ticker'].astype(str).tolist()[:10]) if term else ()
    with st.spinner('외국인·기관 수급 수량 조회 중…'):
        frame, histories, errors = _attach(frame, limit, extras)
    _flow_message(histories, errors, min(50, limit + len(extras)))
    if market != '전체':
        frame = frame[frame['market'] == market].copy()
    if term:
        frame = frame[frame['name'].str.contains(term, case=False, regex=False, na=False) |
                      frame['ticker'].astype(str).str.contains(term, regex=False, na=False)].copy()
    frame['거래대금(억)'] = (pd.to_numeric(frame['traded_krw'], errors='coerce') / 1e8).round(1)
    cols = ['순위', 'name', 'ticker', 'market', 'close', '거래대금(억)',
            '수급 기준일', '외국인 순매수(주)', '기관 순매수(주)']
    st.dataframe(frame[cols], use_container_width=True, hide_index=True,
                 column_config={'name':'종목명','ticker':'종목코드','market':'시장','close':'종가'})
    st.caption('검색해도 원래 전체 TOP 200 순위가 유지됩니다. 순매수 수량이 비어 있는 종목은 수급을 조회하지 못했거나 조회 범위 밖입니다.')
    st.download_button('TOP 200 CSV 저장', frame[cols].to_csv(index=False).encode('utf-8-sig'),
                       'kr_top200_with_investor_shares.csv', 'text/csv')
