"""광부 투자터미널: 한국 증시 시장 폭(Breadth) 1차 연결.

A. 코스피/코스닥 당일 상승·하락·보합: aikstockdata의 T+1 확정 전 종목 자료.
B. 전체시장 ADR20: maedong.kr 의 날짜별 전체시장 상승·하락 종목 수.

두 출처의 날짜와 범위가 다르므로 절대로 한 시계열로 섞지 않는다.
20/50/200일 이동평균선 상회 비율은 종목별 과거 이력이 준비되기 전까지 미제공.
국가 기관(KRX)의 공식 ADR 수치나 매매 신호로 표현하지 않는다.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from io import BytesIO

import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go

KST = ZoneInfo('Asia/Seoul')
AIK = 'https://aikstockdata.com/data/public'
MAEDONG = 'https://maedong.kr/api/v1/market'
HEADERS = {'User-Agent': 'MinerTerminal/1.0 (personal, noncommercial research)',
           'Accept': 'application/json, text/csv'}


def _num(series):
    return pd.to_numeric(series.astype(str).str.replace(',', '', regex=False), errors='coerce')


def parse_daily_breadth(csv_bytes: bytes, digest: dict) -> tuple[pd.DataFrame, str]:
    """두 파일의 전 종목 집계가 맞지 않으면 숫자를 숨긴다."""
    if not isinstance(digest, dict):
        raise ValueError('일별 다이제스트 형식 오류')
    date = str(digest.get('quote_as_of_iso') or digest.get('as_of_iso') or '').strip()
    date_obj = pd.to_datetime(date, errors='coerce')
    if pd.isna(date_obj):
        raise ValueError('종가 자료 기준일 없음')
    if (datetime.now(KST).date() - date_obj.date()).days > 7:
        raise ValueError(f'자료가 7일 이상 지연됨: {date}')

    frame = pd.read_csv(BytesIO(csv_bytes), dtype=str, encoding='utf-8-sig', low_memory=False)
    frame.columns = [str(x).strip() for x in frame.columns]
    cols = {x.lower(): x for x in frame.columns}

    def get_field(*names):
        return next((cols[n.lower()] for n in names if n.lower() in cols), None)

    market_col = get_field('market', 'mrktCtg', 'market_name')
    change_col = get_field('change', 'vs', 'change_krw', 'price_change', 'change_pct', 'fltRt')
    date_col = get_field('basDt', 'base_date_yyyymmdd', 'date', 'as_of')
    code_col = get_field('code', 'stock_code', 'short_code', '종목코드')
    if not market_col or not change_col:
        raise ValueError(f'시장 또는 등락 필드 불명확: {list(frame.columns)[:25]}')
    if date_col:
        expected = date.replace('-', '')
        dates = frame[date_col].dropna().astype(str).str.replace('-', '', regex=False)
        if dates.empty or not dates.eq(expected).all():
            raise ValueError('종가 CSV와 다이제스트의 기준일 불일치')
    if code_col and frame[code_col].duplicated().any():
        raise ValueError('종목코드 중복 — 전 종목 집계 보류')
    markets = frame[market_col].str.strip().str.upper()
    changes = _num(frame[change_col])
    if len(frame) < 1500 or changes.isna().sum() > 0:
        raise ValueError('전 종목 시세 누락 또는 숫자 변환 실패')

    # 같은 제공처의 당일 다이제스트(전체 3시장 포함)와 방향별 수를 검산.
    benchmark = digest.get('market_breadth') or {}
    actual = {'up': int(changes.gt(0).sum()),
              'down': int(changes.lt(0).sum()),
              'flat': int(changes.eq(0).sum())}
    expected = {k: benchmark.get(k) for k in ('up', 'down', 'flat')}
    if all(isinstance(v, (int, float)) for v in expected.values()):
        # 공급처가 소수점 반올림 등락률만 제공하면 소폭 차이가 날 수 있음.
        # 검산에 실패하면 숫자 대신 점검 메시지를 표시한다.
        if any(abs(actual[k] - int(expected[k])) > 3 for k in actual):
            raise ValueError(f'원자료 방향별 검산 불일치: CSV={actual}, 다이제스트={expected}')

    items = []
    for market in ('KOSPI', 'KOSDAQ'):
        direction = changes[markets.eq(market)]
        if len(direction) < 300:
            raise ValueError(f'{market}: 종목 수 부족 ({len(direction)}개)')
        up, down, flat = int(direction.gt(0).sum()), int(direction.lt(0).sum()), int(direction.eq(0).sum())
        items.append({'시장': market, '상승': up, '하락': down, '보합': flat,
                      '대상 종목': len(direction), '상승 비중(%)': round(100 * up / len(direction), 1),
                      '당일 상승/하락 배율(%)': round(100 * up / down, 1) if down else None})
    return pd.DataFrame(items), date


@st.cache_data(ttl=21600, show_spinner=False)
def load_daily_breadth():
    with requests.Session() as s:
        a = s.get(f'{AIK}/today.json', headers=HEADERS, timeout=12)
        a.raise_for_status()
        digest = a.json()
        b = s.get(f'{AIK}/quotes_en.csv', headers=HEADERS, timeout=20)
        b.raise_for_status()
        frame, date = parse_daily_breadth(b.content, digest)
        return frame, date


def _parse_market_payload(payload: dict, requested=None):
    """매동 API가 요청한 거래일을 실제로 제공했는지 엄격하게 검증."""
    if not isinstance(payload, dict):
        return None
    data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    meta = payload.get('meta') or data.get('meta') or {}
    date = str(data.get('date') or meta.get('data_date') or '')[:10]
    d = pd.to_datetime(date, format='%Y-%m-%d', errors='coerce')
    if pd.isna(d) or (requested and date != requested):
        return None
    b = data.get('breadth') or {}
    try:
        up, down = int(b['up']), int(b['down'])
        flat = int(b.get('unchanged', b.get('flat', 0)))
    except (KeyError, ValueError, TypeError):
        return None
    if min(up, down, flat) < 0 or up + down + flat < 1000:
        return None
    return {'날짜': d, '상승': up, '하락': down, '보합': flat}


@st.cache_data(ttl=21600, show_spinner=False)
def load_adr20():
    """매동 전체시장 기록 20일; 호출 한도 고려해 최대 31회만 사용."""
    with requests.Session() as s:
        r = s.get(MAEDONG, headers=HEADERS, timeout=10)
        r.raise_for_status()
        latest = _parse_market_payload(r.json())
        if latest is None:
            raise ValueError('매동 최신 전체시장 폭 데이터 형식이 예상과 다릅니다.')
        last_date = latest['날짜']
        if (datetime.now(KST).date() - last_date.date()).days > 7:
            raise ValueError('전체시장 폭 원자료가 7일 이상 지연됐습니다.')
        rows = [latest]
        # 주말은 건너뛰고, 공휴일은 실제 API 날짜와 대조해 자동 제외.
        dates = pd.bdate_range(end=last_date - pd.Timedelta(days=1), periods=30)[::-1]
        for d in dates:
            if len(rows) >= 20:
                break
            try:
                resp = s.get(MAEDONG, params={'date': d.strftime('%Y-%m-%d')},
                             headers=HEADERS, timeout=8)
                if resp.status_code in (404, 204):
                    continue
                if resp.status_code == 429:
                    raise ValueError('매동 API 분당 호출 제한. 10분 후 재시도하세요.')
                resp.raise_for_status()
                record = _parse_market_payload(resp.json(), d.strftime('%Y-%m-%d'))
                if record is not None:
                    rows.append(record)
            except (requests.RequestException, ValueError) as exc:
                if '호출 제한' in str(exc):
                    raise
                continue
        data = pd.DataFrame(rows).drop_duplicates('날짜').sort_values('날짜')
        if len(data) < 20:
            raise ValueError(f'ADR20 계산에 필요한 거래일 부족: {len(data)}/20일 (임의 보정하지 않음)')
        data = data.tail(20).copy()
        total_down = int(data['하락'].sum())
        if total_down == 0:
            raise ValueError('20거래일 하락 종목 수가 0이라 ADR 산출 불가')
        adr20 = round(100 * float(data['상승'].sum()) / total_down, 1)
        return data, adr20


def show_market_breadth():
    st.markdown('#### 🌐 전체 시장 폭 · 종목 수 기준')
    st.caption('지수의 등락률이 아니라 몇 개 종목이 상승했는지를 봅니다. 코스피·코스닥 당일 수치와 전체시장 ADR20은 공급처와 기준일이 다를 수 있습니다.')
    try:
        market, date = load_daily_breadth()
        st.markdown(f'**KOSPI·KOSDAQ 당일 상승·하락 종목 수** · 자료일 {date} (T+1 확정 종가)')
        cols = st.columns(2)
        for col, row in zip(cols, market.to_dict('records')):
            with col:
                st.markdown(f'**{row["시장"]}**')
                st.metric('상승 비중(보합 포함 전체 대비)', f'{row["상승 비중(%)"]:.1f}%')
                st.caption(f'상승 {row["상승"]:,} · 하락 {row["하락"]:,} · 보합 {row["보합"]:,} · 전체 {row["대상 종목"]:,}종목')
        chart = go.Figure()
        for key, color in [('상승', '#4ade80'), ('하락', '#f87171'), ('보합', '#a7b9ca')]:
            chart.add_bar(name=key, x=market['시장'], y=market[key], marker_color=color)
        chart.update_layout(barmode='stack', height=275, margin=dict(l=5,r=5,t=10,b=5),
                            paper_bgcolor='#101a28', plot_bgcolor='#101a28',
                            font=dict(color='#dae8f5'), legend=dict(orientation='h',y=1.14))
        st.plotly_chart(chart, use_container_width=True)
        st.caption('자료: aikstockdata (금융위원회 공공데이터 기반). 영리 재배포 불가 · 비상업적 개인 연구용.')
        st.download_button('📥 시장별 상승·하락 종목 수 CSV', market.to_csv(index=False).encode('utf-8-sig'),
                           'miner_breadth_daily.csv', mime='text/csv', key='miner_breadth_daily_csv')
    except (requests.RequestException, ValueError, KeyError, pd.errors.ParserError) as exc:
        st.warning(f'시장별 상승·하락 종목 수 판정 보류: {exc}')

    st.markdown('##### 전체시장 ADR20 (20거래일 상승 종목 합계 ÷ 하락 종목 합계 × 100)')
    if st.button('📈 ADR20 최신 데이터 계산 / 새로 확인', key='miner_breadth_adr_start'):
        st.session_state['miner_breadth_adr_open'] = True
    if st.session_state.get('miner_breadth_adr_open'):
        try:
            with st.spinner('전체 시장 20거래일 상승·하락 종목 수 검증 중...'):
                hist, ratio = load_adr20()
            st.metric('전체 시장 ADR20', f'{ratio:.1f}%')
            st.caption(f'자료일: {hist["날짜"].iloc[-1]:%Y-%m-%d} · 최근 20거래일 · KOSPI+KOSDAQ 통합 · 매동 시장 폭 공개 API · 당일 속보 포함 가능')
            st.dataframe(hist.assign(날짜=hist['날짜'].dt.strftime('%Y-%m-%d')).sort_values('날짜',ascending=False),
                         hide_index=True, use_container_width=True)
            st.download_button('📥 ADR20 근거 20거래일 CSV',
                               hist.assign(날짜=hist['날짜'].dt.strftime('%Y-%m-%d')).to_csv(index=False).encode('utf-8-sig'),
                               'miner_adr20_history.csv', mime='text/csv', key='miner_breadth_adr_csv')
        except (requests.RequestException, ValueError, KeyError) as exc:
            st.warning(f'전체시장 ADR20 계산 보류: {exc}')
        from miner_ma_breadth import show_ma_breadth
    show_ma_breadth()
    st.caption('ADR20은 현재 주가의 방향을 알려주는 종목 수 비율이며 투자 판단·추세 전환을 보장하지 않습니다. KRX 공식 ADR이 아닌 공개 자료 기반 자체 산출입니다.')
