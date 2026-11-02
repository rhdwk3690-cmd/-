"""KOSPI200 FUT-category investor contracts and estimated KRW traded notional.

Separate from cash equities and TOP200 individual-stock flows. No fake numbers.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'kr_futures_flow.json'
SPOT_DATA = ROOT / 'data' / 'kr_market_total_flow.json'
FIELDS = ('foreign', 'institution', 'individual')
LABELS = {'foreign': '외국인', 'institution': '기관', 'individual': '개인'}
SOURCE = 'Npay Stock - KRX FUT investor daily net trading'


def read_futures():
    if not DATA.is_file():
        return None, '선물 수급 자료가 아직 없습니다. GitHub Actions의 Collect KOSPI200 futures investor flow를 실행하세요.'
    try:
        v = json.loads(DATA.read_text(encoding='utf-8'))
        if (v.get('status') != 'verified' or v.get('source') != SOURCE or
                v.get('unit') != 'contracts' or v.get('nominal_unit') != 'KRW' or
                v.get('nominal_quality') != 'estimated_from_Npay_trade_prices_million_krw' or
                v.get('nominal_is_cash_flow') is not False):
            raise ValueError('검증 상태/원화 명목금액 기준이 일치하지 않음')
        h = v.get('history')
        if not isinstance(h, list) or not h:
            raise ValueError('일별 선물 수급 자료가 없습니다')
        unique = {}
        for x in h:
            day = date.fromisoformat(x['date'])
            if day.weekday() >= 5:
                raise ValueError('주말 날짜가 거래일로 저장됨')
            for k in FIELDS:
                for suffix in ('net_contracts', 'net_notional_krw'):
                    number = x[f'{k}_{suffix}']
                    if not isinstance(number, int) or isinstance(number, bool):
                        raise ValueError('계약 수 또는 원화 명목금액이 정수가 아님')
            if x['date'] in unique:
                raise ValueError('중복 거래일')
            unique[x['date']] = x
        rows = [unique[k] for k in sorted(unique)]
        if v.get('latest_date') != rows[-1]['date']:
            raise ValueError('최신 거래일 불일치')
        return (v, rows), None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        return None, f'선물 수급 파일 검증 실패: {e}'


def window(rows, n):
    if len(rows) < n:
        return None
    chunk = rows[-n:]
    span = (date.fromisoformat(chunk[-1]['date']) - date.fromisoformat(chunk[0]['date'])).days
    if span > (12 if n == 5 else 43):
        return None
    return chunk


def spot_same_day(day):
    if not SPOT_DATA.is_file():
        return None
    try:
        payload = json.loads(SPOT_DATA.read_text(encoding='utf-8'))
        if payload.get('status') != 'verified':
            return None
        for r in payload.get('history', []):
            if r.get('date') == day:
                value = r['KOSPI']['foreign_net_krw']
                return value if isinstance(value, int) and not isinstance(value, bool) else None
    except (OSError, TypeError, KeyError, ValueError, json.JSONDecodeError):
        return None
    return None


def money(v):
    return f'{v/100_000_000:+,.0f}억'


def render_futures_flow():
    st.markdown('---')
    st.subheader('📈 외국인·기관 선물 수급 | 계약 수 + 추정 명목금액')
    st.caption('Npay KRX FUT 시장 분류. 코스피200 선물로 제공되지만 API의 일별 응답에는 상품 코드가 없습니다. 주식 현물 원화 수급과 **절대 합산하지 않습니다.**')
    result, issue = read_futures()
    if issue:
        st.warning(issue)
        return False
    meta, rows = result
    latest = rows[-1]
    d = latest['date']
    st.caption(f'선물 거래일 {d} · 유효 관측 {len(rows)}일 · 수집 {meta.get("collected_at_kst", "미확인")}')
    age = (datetime.now(ZoneInfo('Asia/Seoul')).date() - date.fromisoformat(d)).days
    if age > 3:
        st.warning(f'마지막 선물 자료는 {age}일 전 데이터입니다. 최신 수급으로 간주하지 마세요.')

    m1,m2,m3 = st.columns(3)
    for col,who,label in ((m1,'foreign','외국인'),
                           (m2,'institution','기관'),
                           (m3,'individual','개인')):
        col.metric(f'{label} 추정 순매수 명목금액',
                   f'{latest[f"{who}_net_notional_krw"]/1e8:+,.0f}억 원',
                   delta=f'{latest[f"{who}_net_contracts"]:+,}계약',
                   delta_color='off')

    st.caption('명목금액은 Npay 매수금액 − 매도금액을 **백만원 단위로 해석해 원화 환산한 추정치**입니다. 수집기에서 계약당 암묵적 지수 포인트를 검산합니다. 실제 현금 투입액·증거금·포지션 잔고와 다릅니다.')
    details = []
    for k in FIELDS:
        details.append({'주체': LABELS[k], '순매수 계약 수': latest[f'{k}_net_contracts'],
                        '추정 순매수 명목금액(억원)': round(latest[f'{k}_net_notional_krw']/1e8,1)})
    st.dataframe(pd.DataFrame(details),hide_index=True,use_container_width=True)

    spot = spot_same_day(d)
    if spot is not None:
        st.markdown('#### 동일 거래일 외국인 현물·선물 방향')
        c1,c2 = st.columns(2)
        c1.metric('코스피 전체 현물 외국인 순매수', money(spot))
        c2.metric('선물 외국인 추정 명목금액', money(latest['foreign_net_notional_krw']))
        s_dir = '매수' if spot > 0 else '매도' if spot < 0 else '보합'
        f = latest['foreign_net_contracts']
        f_dir = '매수' if f > 0 else '매도' if f < 0 else '보합'
        st.info(f'현물 {s_dir} / 선물 {f_dir}. 현물 순매수는 실제 주식 거래금액이고, 선물은 계약·명목금액이므로 합계나 순유입액으로 해석하면 안 됩니다.')
    else:
        st.info('현물·선물 자료의 날짜가 일치하지 않아 방향 비교를 보류합니다.')

    st.markdown('#### 외국인 선물 최근 5·20거래일 누적')
    totals=[]
    for n in (5,20):
        x=window(rows,n)
        totals.append({'기간':f'{n}거래일',
                       '순매수 계약 수':sum(z['foreign_net_contracts'] for z in x) if x else None,
                       '추정 순매수 명목금액(억원)':round(sum(z['foreign_net_notional_krw'] for z in x)/1e8,1) if x else None,
                       '관측 구간':f'{x[0]["date"]} ~ {x[-1]["date"]}' if x else '자료 축적 중 / 누락일 확인 필요'})
    st.dataframe(pd.DataFrame(totals),hide_index=True,use_container_width=True)
    st.caption('5·20일 누적은 실제 확보한 거래일만 사용하며 누락이 크면 표시하지 않습니다. 선물 만기와 헤지·차익거래 영향에 주의하세요.')
    if len(rows)>=2:
        chart=go.Figure()
        segment=rows[-45:]
        chart.add_scatter(x=[x['date'] for x in segment],y=[x['foreign_net_notional_krw']/1e8 for x in segment],
                          mode='lines+markers',name='외국인 추정 명목금액')
        chart.add_hline(y=0,line_width=1,line_color='#9ba8b8')
        chart.update_layout(height=280,margin=dict(l=8,r=8,t=10,b=10),yaxis_title='억원 (추정 명목금액)')
        st.plotly_chart(chart,use_container_width=True)
    with st.expander('선물 일별 수급 내역 / CSV 다운로드'):
        history=[]
        for x in reversed(rows[-100:]):
            history.append({'거래일':x['date'], **{LABELS[k]+' 순매수(계약)':x[f'{k}_net_contracts'] for k in FIELDS},
                            **{LABELS[k]+' 명목금액(억원, 추정)':round(x[f'{k}_net_notional_krw']/1e8,2) for k in FIELDS}})
        df=pd.DataFrame(history)
        st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('📥 선물 수급 CSV',df.to_csv(index=False).encode('utf-8-sig'),
                           file_name='miner_futures_flow.csv',mime='text/csv',key='miner_futures_csv')
    st.caption('Npay 비공식 공개 JSON 기반 KRX FUT 분류. 확정 거래량, ETF 헤지, 미니선물 포함 범위는 공식 KRX 통계와 교차검증이 필요합니다. 매수우위는 기존 포지션 청산일 수도 있습니다.')
    return True
