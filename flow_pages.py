"""광부 투자터미널 | 매동 수급 금액: 계좌·인증키 불필요, 실제 게시 금액만."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent
SNAP = ROOT / 'data' / 'kr_flow.json'
KST = ZoneInfo('Asia/Seoul')
API = 'https://maedong.kr/api/v1/stock/{}/flow'


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_flow(code):
    r = requests.get(
        API.format(code),
        params={'from': (datetime.now(KST).date() - timedelta(days=10)).isoformat()},
        headers={'User-Agent': 'MinerDashboard/1.0 (personal research)'},
        timeout=12
    )
    r.raise_for_status()
    data = r.json()
    if (not isinstance(data, dict)
        or str(data.get('code', '')).zfill(6) != code
        or not isinstance(data.get('rows'), list)):
        raise ValueError('예상과 다른 응답 형식/종목코드')
    rows = []
    for record in data['rows']:
        if not isinstance(record, dict):
            continue
        day = str(record.get('date', ''))
        if not (len(day) == 10 and day[4] == '-' and day[7] == '-'):
            continue
        foreign = pd.to_numeric(record.get('foreign_net_krw'), errors='coerce')
        inst = pd.to_numeric(record.get('institution_net_krw'), errors='coerce')
        personal = pd.to_numeric(record.get('individual_net_krw'), errors='coerce')
        if pd.isna(foreign) and pd.isna(inst):
            continue
        rows.append({
            'date': day, 'foreign': foreign,
            'institution': inst, 'personal': personal
        })
    if not rows:
        return None
    return max(rows, key=lambda x: x['date'])


@st.cache_data(ttl=120, show_spinner=False)
def load_top():
    raw = json.loads(SNAP.read_text(encoding='utf-8'))
    df = pd.DataFrame(raw.get('top200') or [])
    if df.empty:
        raise ValueError('TOP 200 데이터가 비어 있습니다.')
    required = {'ticker', 'name', 'market', 'traded_krw', 'close'}
    if not required.issubset(df.columns):
        raise ValueError('TOP 200 필수 필드 누락')
    df = df.sort_values(
        'traded_krw', ascending=False, kind='stable'
    ).reset_index(drop=True)
    df.insert(0, '순위', range(1, len(df) + 1))
    return df, raw


def fetch_many(codes):
    found, errors = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_flow, c): c for c in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                found[code] = future.result()
            except Exception as exc:
                errors.append(f'{code}: {str(exc)[:110]}')
    return found, errors


def prepare():
    try:
        frame, meta = load_top()
    except Exception as exc:
        st.error(f'TOP 200 파일 오류: {exc}')
        return None
    st.caption(
        f"거래대금 수집처: {meta.get('source', '미확인')} · "
        f"거래 기준일: {meta.get('date') or '미검증'}"
    )
    if not meta.get('date'):
        st.warning(
            '거래대금 TOP 200 거래일은 미검증입니다. '
            '수급일과 같다고 가정하지 않습니다.'
        )

    n = st.select_slider(
        '매동 수급 조회 종목 수 (거래대금 상위)',
        options=[10, 20, 50, 100, 200],
        value=20
    )
    st.caption(
        '매동 API: 인증 없음, 분당 60회·일 400회 제한. '
        '200종목 첫 조회는 지연/429가 발생할 수 있습니다. '
        '이후 1시간 캐시 사용.'
    )
    if n >= 100:
        st.warning(
            '100~200종목은 호출 한도에 주의하세요. '
            '최초에는 20종목으로 검증을 권장합니다.'
        )

    start = st.button('🔄 선택 종목 수급 금액 조회', type='primary')
    if not start and 'flow_results' not in st.session_state:
        st.info(
            '조회 버튼을 누르면 외국인·기관 순매수 금액(원)을 가져옵니다.'
        )
        return None

    if start:
        codes = (
            frame.head(n)['ticker'].astype(str).str.zfill(6).tolist()
        )
        with st.spinner(f'수급 {len(codes)}종목 조회 중…'):
            found, errors = fetch_many(codes)
        st.session_state.flow_results = (found, errors, n)

    found, errors, checked = st.session_state.flow_results
    code = frame['ticker'].astype(str).str.zfill(6)

    for field, label in [
        ('date', '수급 기준일'),
        ('foreign', '외국인 순매수(억)'),
        ('institution', '기관 순매수(억)'),
        ('personal', '개인 순매수(억)')
    ]:
        frame[label] = code.map(
            lambda c: (found.get(c) or {}).get(field)
        )
        if field != 'date':
            frame[label] = (
                pd.to_numeric(frame[label], errors='coerce') / 1e8
            ).round(2)

    frame['수급 합계(억)'] = frame[
        ['외국인 순매수(억)', '기관 순매수(억)']
    ].sum(axis=1, min_count=2).round(2)
    frame['거래대금(억)'] = (
        pd.to_numeric(frame['traded_krw'], errors='coerce') / 1e8
    ).round(1)

    same = (
        frame['수급 기준일'].notna()
        & (frame['수급 기준일'] == meta.get('date'))
    )
    frame['수급강도(%)'] = (
        frame['수급 합계(억)']
        / frame['거래대금(억)'] * 100
    ).where(same).round(2)

    count = sum(1 for x in found.values() if x is not None)
    if count:
        st.success(
            f'조회 결과: {count}/{checked}종목에 금액 수급 확인 '
            '· 원자료: maedong.kr'
        )
    else:
        st.error('금액 수급을 조회하지 못했습니다.')

    dates = frame['수급 기준일'].dropna().value_counts()
    if not dates.empty:
        st.caption(
            '수급 기준일 분포: '
            + ', '.join(f'{d} ({c}종목)' for d, c in dates.items())
        )
    if errors:
        with st.expander(f'조회 실패 {len(errors)}건'):
            for err in errors[:60]:
                st.text(err)

    st.caption(
        '순매수 금액은 매동의 _net_krw 필드(원)를 1억원으로 '
        '나눈 값입니다. 0과 미수집(null)은 구별합니다. '
        '수급 원천의 독립 검증은 별도 필요합니다.'
    )
    return frame


def cashflow():
    st.title('💸 자금 흐름 | 외국인·기관 순매수 금액')
    frame = prepare()
    if frame is None:
        return

    market = st.selectbox(
        '시장', ['전체', 'KOSPI', 'KOSDAQ'], key='cashmarket'
    )
    if market != '전체':
        frame = frame[frame['market'] == market]

    columns = [
        '순위', 'name', '수급 기준일',
        '외국인 순매수(억)', '기관 순매수(억)',
        '개인 순매수(억)', '수급 합계(억)'
    ]
    st.dataframe(
        frame[columns], use_container_width=True,
        hide_index=True, column_config={'name': '종목명'}
    )

    paired = frame.dropna(
        subset=['외국인 순매수(억)', '기관 순매수(억)']
    )
    if not paired.empty:
        sample = paired.head(20)
        fig = go.Figure()
        fig.add_bar(
            x=sample['name'],
            y=sample['외국인 순매수(억)'],
            name='외국인'
        )
        fig.add_bar(
            x=sample['name'],
            y=sample['기관 순매수(억)'],
            name='기관'
        )
        fig.update_layout(
            barmode='relative', yaxis_title='억원', height=360
        )
        st.plotly_chart(fig, use_container_width=True)


def top200():
    st.title('📊 TOP 200 | 거래대금·실제 게시 순매수 금액')
    frame = prepare()
    if frame is None:
        return

    market = st.selectbox(
        '시장', ['전체', 'KOSPI', 'KOSDAQ'], key='topmarket'
    )
    if market != '전체':
        frame = frame[frame['market'] == market]

    term = st.text_input('종목명 또는 종목코드 검색').strip()
    if term:
        frame = frame[
            frame['name'].str.contains(
                term, case=False, regex=False, na=False
            )
            | frame['ticker'].astype(str).str.contains(
                term, regex=False, na=False
            )
        ]

    columns = [
        '순위', 'name', 'ticker', 'market', 'close',
        '거래대금(억)', '수급 기준일',
        '외국인 순매수(억)', '기관 순매수(억)',
        '개인 순매수(억)', '수급 합계(억)', '수급강도(%)'
    ]
    st.dataframe(
        frame[columns],
        use_container_width=True,
        hide_index=True,
        column_config={
            'name': '종목명', 'ticker': '코드',
            'market': '시장', 'close': '종가'
        }
    )
    st.caption(
        '거래대금 원래 순위 유지. 수급 데이터가 없는 종목은 '
        '빈칸으로 표시하며 0으로 추정하지 않습니다.'
    )
    st.download_button(
        'TOP 200 수급 CSV',
        frame[columns].to_csv(index=False).encode('utf-8-sig'),
        'miner_flow.csv', 'text/csv'
    )
