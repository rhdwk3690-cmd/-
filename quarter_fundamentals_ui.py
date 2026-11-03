"""Read-only quarterly OpenDART YoY/QoQ comparison. No secret or API calls in the UI."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(__file__).resolve().parent / 'data' / 'kr_dart_quarters.json'


@st.cache_data(ttl=300, show_spinner=False)
def get_financials():
    try:
        payload=json.loads(DATA.read_text(encoding='utf-8'))
        if payload.get('source')!='OpenDART official periodic financial statements':
            return None
        if not isinstance(payload.get('rows'),dict):return None
        return payload
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        return None


def money(v):
    return f'{v/1e8:+,.1f}억 원' if type(v) is int else '미확인'


def pct(v, unit='%'):
    return f'{v:+,.2f}{unit}' if isinstance(v,(int,float)) and not isinstance(v,bool) else '미확인'


def op_value(row, field):
    v=row.get('op_'+field+'_pct')
    status=row.get('op_'+field+'_status')
    if status in ('흑자전환','적자전환','적자지속','기저 0'):return status
    return pct(v)


def classification(r):
    if r.get('status') not in ('ok','partial'):return '실적 미확보'
    sales=r.get('revenue_yoy_pct');near=r.get('revenue_qoq_pct')
    pp=r.get('margin_yoy_pp');qpp=r.get('margin_qoq_pp')
    # Description only, not a trade/buy/sell signal or backtest score.
    if any(x is None for x in (sales,near,pp,qpp)):return '일부 비교 미확인'
    if sales>0 and near>0 and pp>0 and qpp>0:return '매출·이익률 동반 개선'
    if sales>0 and pp>0:return '전년 동기 개선'
    if sales>0 and near<0:return '성장 유지·전분기 둔화'
    return '추가 분석 필요'


def enrich_comparison(frame):
    """Add YoY and QoQ columns while leaving RS/DMI ranking unchanged."""
    data=get_financials()
    if data is None:
        return frame, False
    rows=data['rows']; out=frame.copy()
    value_cols = [
        ('공시분기','period'),('공시일','filing_date'),
        ('매출 YoY(%)','revenue_yoy_pct'),('매출 QoQ(%)','revenue_qoq_pct'),
        ('영업이익 YoY','op_yoy'),('영업이익 QoQ','op_qoq'),
        ('이익률 YoY(%p)','margin_yoy_pp'),('이익률 QoQ(%p)','margin_qoq_pp')]
    for label,key in value_cols:
        if key in ('op_yoy','op_qoq'):
            out[label] = out['종목코드'].map(lambda c: op_value(rows.get(str(c),{}),key[3:]) if rows.get(str(c),{}).get('status') in ('ok','partial') else '미확인')
        else:
            out[label] = out['종목코드'].map(lambda c: rows.get(str(c),{}).get(key) if rows.get(str(c),{}).get('status') in ('ok','partial') else None)
    out['실적 상태'] = out['종목코드'].map(lambda c:classification(rows.get(str(c),{})))
    out['재무범위'] = out['종목코드'].map(lambda c:rows.get(str(c),{}).get('fs_div') or '미확인')
    return out, True


def render_stock_quarter(code):
    st.markdown('#### 📑 최신 공시 분기 실적 | YoY · QoQ')
    data=get_financials()
    if data is None:
        st.info('OpenDART 실적 자료를 아직 수집하지 않았습니다. GitHub Actions에서 Collect quarterly OpenDART YoY QoQ를 먼저 실행하세요.')
        return
    row=data['rows'].get(str(code),{})
    if row.get('status') not in ('ok','partial'):
        st.info('이 종목의 공시 실적은 아직 수집·검증되지 않았습니다. 다른 종목을 먼저 분석할 수 있습니다.')
        return
    st.caption(f"{row['period']} · 공시일 {row['filing_date']} · {'연결' if row['fs_div']=='CFS' else '별도'} 재무제표 · 출처 OpenDART")
    a,b,c=st.columns(3)
    a.metric('분기 매출',money(row.get('sales_krw')))
    b.metric('분기 영업이익',money(row.get('operating_income_krw')))
    c.metric('분기 영업이익률',f"{row['margin_pct']:.2f}%" if row.get('margin_pct') is not None else '미확인')
    st.markdown('**전년 동기 대비 / 직전 분기 대비**')
    comparison=pd.DataFrame([
        {'항목':'매출액','전년 동기 YoY':pct(row.get('revenue_yoy_pct')),'직전 분기 QoQ':pct(row.get('revenue_qoq_pct'))},
        {'항목':'영업이익','전년 동기 YoY':op_value(row,'yoy'),'직전 분기 QoQ':op_value(row,'qoq')},
        {'항목':'영업이익률','전년 동기 YoY':pct(row.get('margin_yoy_pp'),'%p'),'직전 분기 QoQ':pct(row.get('margin_qoq_pp'),'%p')},
    ])
    st.dataframe(comparison,hide_index=True,use_container_width=True)
    st.caption('실적 상태: '+classification(row)+' · 숫자는 해당 분기 3개월 실적 기준. 분기 수치는 공시 후 갱신됩니다.')
    if row.get('dart_link'):
        st.link_button('📄 DART 공시 원문 확인',row['dart_link'])
    st.caption('요약 숫자는 현재 OpenDART API 기준이라 과거 정정이 반영됐을 수 있습니다. 이는 백테스트 당시 정보(point-in-time)가 아닙니다. Q4는 연간−3분기 누적으로 계산하며, 조회 불가 값은 미확인 처리합니다. 계절성이 있는 기업은 QoQ만으로 성장성을 판정하지 않습니다.')
