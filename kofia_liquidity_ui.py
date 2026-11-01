"""Market signal liquidity panel: official KOFIA FreeSIS date-aligned balances.

The previous Npay source is used strictly for same-date comparison, never for
filling missing official credit observations. No unverified signal weights.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT=Path(__file__).resolve().parent
KOFIA=ROOT/'data'/'kr_kofia_liquidity.json'
NAVER=ROOT/'data'/'kr_market_liquidity.json'
SOURCE='KOFIA FreeSIS official statistics website (public read-only JSON)'


def read_official(path=KOFIA):
    if not path.is_file():
        return None,'금융투자협회 공식 통계 수집 파일이 아직 없습니다. GitHub Actions 수집을 확인하세요.'
    try:
        obj=json.loads(path.read_text(encoding='utf-8'))
        if (obj.get('status')!='official_source_validated' or obj.get('source')!=SOURCE or
            obj.get('unit')!='KRW_million'):
            raise ValueError('공식 통계 출처 또는 단위 검증 실패')
        h=obj['history']
        if not isinstance(h,list) or len(h)<60:
            raise ValueError('최소 60거래일 공식 기록 필요')
        prev=None
        for row in h:
            d=date.fromisoformat(row['date'])
            if prev and d<=prev:
                raise ValueError('일별 기록 중복/역순')
            prev=d
            for key in ('deposit_million_krw','credit_million_krw'):
                if type(row.get(key)) is not int or row[key]<=0:
                    raise ValueError(f'{key}: 양의 백만원 단위 정수 필요')
        if h[-1]['date']!=obj.get('latest_date'):
            raise ValueError('최신 기준일과 기록 불일치')
        return (obj,h),None
    except (ValueError,TypeError,KeyError,OSError,json.JSONDecodeError) as exc:
        return None,f'금융투자협회 데이터 검증 실패: {exc}'


def naver_same_day(day,path=NAVER):
    try:
        obj=json.loads(path.read_text(encoding='utf-8'))
        if obj.get('status')!='source_validated' or obj.get('unit_assumption')!='100M_KRW_per_raw_integer':
            return None
        for r in obj.get('history',[]):
            if r.get('date')==day:
                dep=r['deposit_raw_100m'];cred=r['credit_raw_100m']
                if type(dep) is int and type(cred) is int and min(dep,cred)>0:
                    return {'deposit_million_krw_assumed':dep*100,
                            'credit_million_krw_assumed':cred*100}
    except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError):
        pass
    return None


def make_frame(h):
    df=pd.DataFrame(h)
    df.index=pd.to_datetime(df.pop('date'))
    df.index.name='자료일'
    df['예탁금(조원)']=df['deposit_million_krw']/1_000_000
    df['신용융자(조원)']=df['credit_million_krw']/1_000_000
    df['신용/예탁(%)']=df['credit_million_krw']/df['deposit_million_krw']*100
    df['예탁금 오실레이터(%)']=(df['deposit_million_krw'].rolling(5).mean()/df['deposit_million_krw'].rolling(20).mean()-1)*100
    df['신용 오실레이터(%)']=(df['credit_million_krw'].rolling(5).mean()/df['credit_million_krw'].rolling(20).mean()-1)*100
    return df


def relative_position(series):
    if len(series)<60:
        return None
    last=series.iloc[-60:]
    if (last.index[-1]-last.index[0]).days>120 or last.max()==last.min():
        return None
    return (last.iloc[-1]-last.min())/(last.max()-last.min())*100


def render_kofia_liquidity():
    st.subheader('💰 증시 자금 | 금융투자협회 공식 예탁금·신용융자')
    val,issue=read_official()
    if issue:
        st.warning(issue)
        st.info('공식 신용융자잔고가 확보되지 않으면 네이버 수치로 대체하지 않습니다. 기존 네이버 수집 파일은 비교용으로 유지합니다.')
        return
    obj,h=val
    df=make_frame(h)
    day=obj['latest_date']
    latest=df.iloc[-1]
    lag=(datetime.now(ZoneInfo('Asia/Seoul')).date()-date.fromisoformat(day)).days
    st.caption(f'자료일 **{day}** · {len(df)}개 날짜 · 금투협 FreeSIS 통계화면(백만원 단위) · 수집 {obj.get("collected_at_kst", "-")}')
    st.caption('공식 통계사이트의 공개 읽기 전용 JSON을 수집했습니다. 인증키를 발급받는 별도 금투협 OpenAPI와 다릅니다. 투자자예탁금은 장내파생상품 거래예수금을 포함합니다.')
    if lag>5:
        st.warning(f'공식 증시 자금 자료가 {lag}일 전 기준입니다. 당일 코스피·코스닥 지수와 기준일이 다릅니다.')
    if len(df)>=2:
        ddep=(df['deposit_million_krw'].iloc[-1]-df['deposit_million_krw'].iloc[-2])/1_000_000
        dcred=(df['credit_million_krw'].iloc[-1]-df['credit_million_krw'].iloc[-2])/1_000_000
    else:
        ddep=dcred=0
    a,b,c=st.columns(3)
    a.metric('공식 투자자예탁금',f'{latest["예탁금(조원)"]:.2f}조원',f'{ddep:+.3f}조원 / 전 거래자료 대비')
    b.metric('공식 신용융자잔고',f'{latest["신용융자(조원)"]:.2f}조원',f'{dcred:+.3f}조원 / 전 거래자료 대비')
    c.metric('공식 신용융자 / 예탁금',f'{latest["신용/예탁(%)"]:.2f}%')

    st.markdown('#### 공식 시계열 기반 자금 오실레이터')
    dep_osc=latest['예탁금 오실레이터(%)']
    cred_osc=latest['신용 오실레이터(%)']
    pos=relative_position(df['신용/예탁(%)'])
    x,y,z=st.columns(3)
    x.metric('예탁금 5일/20일 평균 괴리','자료 부족' if pd.isna(dep_osc) else f'{dep_osc:+.2f}%')
    y.metric('신용융자 5일/20일 평균 괴리','자료 부족' if pd.isna(cred_osc) else f'{cred_osc:+.2f}%')
    z.metric('신용/예탁 비율 60일 위치','자료 부족' if pos is None else f'{pos:.1f}/100')
    st.caption('오실레이터=(최근 5거래일 평균/최근 20거래일 평균-1)×100. 60일 위치는 기간 내 최저 0, 최고 100. 매매 신호 또는 권장 주식비중이 아닙니다.')

    naver=naver_same_day(day)
    if naver:
        dep_diff=latest['deposit_million_krw']-naver['deposit_million_krw_assumed']
        cred_diff=latest['credit_million_krw']-naver['credit_million_krw_assumed']
        st.markdown('#### 같은 날짜 네이버 자료와 교차 비교')
        st.dataframe(pd.DataFrame([{'기준일':day,'지표':'투자자예탁금',
                         '금투협 공식(조원)':latest['예탁금(조원)'],
                         '네이버 단위가정(조원)':naver['deposit_million_krw_assumed']/1_000_000,
                         '차이(억원)':dep_diff/100},
                        {'기준일':day,'지표':'신용융자잔고',
                         '금투협 공식(조원)':latest['신용융자(조원)'],
                         '네이버 단위가정(조원)':naver['credit_million_krw_assumed']/1_000_000,
                         '차이(억원)':cred_diff/100}]).round(4),
                     hide_index=True,use_container_width=True)
        if abs(cred_diff)>100:
            st.warning('같은 날짜의 신용융자 금액에 출처 간 차이가 확인됩니다. 범위·집계 방법 확인 전 공식 FreeSIS 신용융자를 기준으로 표시하며 네이버 신용융자는 점수에 사용하지 않습니다.')
        else:
            st.success('같은 날짜의 신용융자 원자료가 금투협과 네이버에서 실질적으로 일치합니다.')
    else:
        st.caption('네이버 동일 날짜 자료가 없어 출처 간 직접 비교는 보류합니다. 다른 날짜를 동일 날짜처럼 대조하지 않습니다.')

    view=df.tail(120)
    fig=go.Figure()
    fig.add_scatter(x=view.index,y=view['예탁금(조원)'],name='공식 예탁금',mode='lines')
    fig.add_scatter(x=view.index,y=view['신용융자(조원)'],name='공식 신용융자',mode='lines')
    fig.update_layout(height=320,hovermode='x unified',margin=dict(l=5,r=5,t=15,b=10),yaxis_title='조원')
    st.plotly_chart(fig,use_container_width=True)
    fig2=go.Figure()
    for k in ('예탁금 오실레이터(%)','신용 오실레이터(%)'):
        fig2.add_scatter(x=view.index,y=view[k],name=k,mode='lines')
    fig2.add_hline(y=0,line_width=1)
    fig2.update_layout(height=270,hovermode='x unified',margin=dict(l=5,r=5,t=15,b=10),yaxis_title='5/20 오실레이터 (%)')
    st.plotly_chart(fig2,use_container_width=True)
    with st.expander('원자료·금융투자협회 공식 수치 CSV 다운로드'):
        data=df.sort_index(ascending=False)
        st.dataframe(data.round(4),use_container_width=True)
        st.download_button('📥 금융투자협회 증시자금 CSV',df.to_csv().encode('utf-8-sig'),
                           file_name='miner_kofia_liquidity.csv',mime='text/csv',key='miner_kofia_liquidity_csv')
    st.caption('출처: 금융투자협회 FreeSIS > 증시자금추이(060), 신용공여 잔고 추이(070). 공식 통계지만 투자 지표로서의 예측력은 별도 검증이 필요합니다.')
