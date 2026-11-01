"""광부 투자터미널: 검증된 코스피/코스닥 전체 현물 수급과 독립된 선물 수급.

기존 자금 흐름·TOP200의 외부 함수 이름은 유지한다.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from futures_flow_ui import render_futures_flow

DATA = Path(__file__).resolve().parent / 'data' / 'kr_market_total_flow.json'
MARKETS = ('KOSPI', 'KOSDAQ')
COLUMNS = ('foreign_net_krw', 'institution_net_krw', 'individual_net_krw')
LABELS = {'foreign_net_krw':'외국인', 'institution_net_krw':'기관', 'individual_net_krw':'개인'}
VALID_SOURCES = ('KRX investor daily trading value via pykrx (KRX data website)',
                 'Naver Finance - market investor daily net trading')


def read_verified_market_total():
    if not DATA.is_file():
        return None, '시장 전체 수급 수집 파일이 없습니다. GitHub Actions의 시장 전체 현물 수급 수집을 실행하세요.'
    try:
        obj = json.loads(DATA.read_text(encoding='utf-8'))
        if obj.get('status') != 'verified' or obj.get('source') not in VALID_SOURCES:
            raise ValueError('수급 출처 또는 검증 상태가 맞지 않음')
        hist = obj.get('history')
        if not isinstance(hist, list) or not hist:
            raise ValueError('일별 수급 이력이 없습니다')
        valid = {}
        for r in hist:
            d = date.fromisoformat(r['date'])
            if d.weekday() >= 5:
                raise ValueError('거래일이 주말입니다')
            for m in MARKETS:
                for k in COLUMNS:
                    v = r[m][k]
                    if not isinstance(v, int) or isinstance(v, bool):
                        raise ValueError('시장/투자자 원 단위 수급이 정수가 아닙니다')
            if d.isoformat() in valid:
                raise ValueError('중복 거래일')
            valid[d.isoformat()] = r
        history = [valid[d] for d in sorted(valid)]
        if obj.get('latest_date') != history[-1]['date']:
            raise ValueError('최신 거래일과 저장 자료 불일치')
        return (obj, history), None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, OSError) as exc:
        return None, f'시장 전체 수급 파일 검증 실패: {exc}'


def _money_text(won):
    return f'{won/100_000_000:+,.0f}억'


def _total(rows, markets, fields):
    return sum(row[m][key] for row in rows for m in markets for key in fields)


def _recent_window(history, n):
    if len(history) < n:
        return None
    recent=history[-n:]
    days=(date.fromisoformat(recent[-1]['date'])-date.fromisoformat(recent[0]['date'])).days
    if days > (12 if n == 5 else 43):
        return None
    return recent


def render_market_totals():
    st.subheader('코스피 · 코스닥 전체 현물 수급')
    st.caption('시장별 투자자 순매수 금액(원) · TOP200 표본과 별개 · 선물 미포함')
    value, issue = read_verified_market_total()
    if issue:
        st.warning(issue)
        st.info('전체 시장 현물 자료가 검증되기 전까지 숫자를 임의로 채우지 않습니다.')
        render_futures_flow()
        return False
    obj, history = value
    st.caption(f"현물 자료 제공처: {obj.get('source', '미확인')} · {obj.get('source_page', '')}")
    if obj.get('includes_etf_etn_elw') is not False:
        st.warning('네이버 시장 통계는 KRX 공식 오픈 API가 아닙니다. ETF·ETN·ELW 포함 여부는 독립 검증되지 않았습니다.')
    today=datetime.now(ZoneInfo('Asia/Seoul')).date()
    day=history[-1]['date']
    age=(today-date.fromisoformat(day)).days
    st.caption(f"현물 기준일 **{day}** · 저장 {obj.get('collected_at_kst','미확인')} · 확보 {len(history)}거래일")
    if age>3:
        st.warning(f'마지막 현물 수급 자료는 {age}일 전 기준입니다.')
    latest=history[-1]
    summary=[]
    for title, markets in (('코스피',('KOSPI',)),('코스닥',('KOSDAQ',)),('합계',MARKETS)):
        f=_total([latest],markets,COLUMNS[:1])
        i=_total([latest],markets,COLUMNS[1:2])
        p=_total([latest],markets,COLUMNS[2:])
        summary.append({'시장':title,'외국인(억)':f/1e8,'기관(억)':i/1e8,
                        '개인(억)':p/1e8,'외국인+기관(억)':(f+i)/1e8})
    st.markdown('#### 기준일 투자자별 순매수')
    st.dataframe(pd.DataFrame(summary).round(1),hide_index=True,use_container_width=True)
    a,b,c=st.columns(3)
    a.metric('코스피 · 외국인+기관',_money_text(_total([latest],('KOSPI',),COLUMNS[:2])))
    b.metric('코스닥 · 외국인+기관',_money_text(_total([latest],('KOSDAQ',),COLUMNS[:2])))
    c.metric('양 시장 합계',_money_text(_total([latest],MARKETS,COLUMNS[:2])))
    fig=go.Figure()
    for key in COLUMNS:
        fig.add_bar(name=LABELS[key],x=['코스피','코스닥'],
                    y=[latest[m][key]/1e8 for m in MARKETS])
    fig.add_hline(y=0,line_width=1)
    fig.update_layout(barmode='relative',height=300,margin=dict(l=10,r=10,t=10,b=10),
                      yaxis_title='순매수(억원)')
    st.plotly_chart(fig,use_container_width=True)
    st.markdown('#### 현물 5·20거래일 누적 순매수')
    cum=[]
    for n in (5,20):
        chunk=_recent_window(history,n)
        if chunk is None:
            cum.append({'기간':f'최근 {n}일','외국인(억)':None,'기관(억)':None,
                        '합산(억)':None,'상태':'자료 축적 중 / 날짜 간격 점검'})
        else:
            f=_total(chunk,MARKETS,COLUMNS[:1]); i=_total(chunk,MARKETS,COLUMNS[1:2])
            cum.append({'기간':f'최근 {n}일','외국인(억)':round(f/1e8,1),
                        '기관(억)':round(i/1e8,1),'합산(억)':round((f+i)/1e8,1),
                        '상태':f'{chunk[0]["date"]} ~ {chunk[-1]["date"]}'})
    st.dataframe(pd.DataFrame(cum),hide_index=True,use_container_width=True)
    st.caption('실제 수집된 거래일만 누적하며 데이터가 부족하거나 날짜 간격이 크면 계산하지 않습니다.')
    details=[]
    for r in reversed(history[-60:]):
        for m in MARKETS:
            details.append({'거래일':r['date'],'시장':m,
                **{LABELS[k]+'(억)':round(r[m][k]/1e8,2) for k in COLUMNS},
                '외국인+기관(억)':round((r[m]['foreign_net_krw']+r[m]['institution_net_krw'])/1e8,2)})
    with st.expander('시장 전체 현물 수급 거래일별 내역 / CSV 다운로드'):
        df=pd.DataFrame(details)
        st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('📥 시장 전체 현물 수급 CSV',df.to_csv(index=False).encode('utf-8-sig'),
                           file_name='miner_full_market_flow.csv',mime='text/csv',key='miner_full_market_csv')
    st.caption('현물 합계는 KOSPI+KOSDAQ만 해당. KONEX·파생상품은 미포함.')
    render_futures_flow()
    return True
