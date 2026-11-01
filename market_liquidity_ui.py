"""광부 시장신호: 게시된 투자자예탁금 및 신용융자잔고 시계열.

Npay 공개 JSON은 금액 단위를 직접 명시하지 않는다. 공식 KOFIA와 교차검증 전
'억원 가정'으로만 표기하며, 상대 비율/오실레이터는 동일 단위가 상쇄된다.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA=Path(__file__).resolve().parent/'data'/'kr_market_liquidity.json'
SOURCE='Npay Stock public investor deposit and credit loan JSON'


def read_liquidity():
    if not DATA.exists():
        return None, '아직 예탁금·신용잔고 데이터 파일이 없습니다. GitHub Actions의 「Collect KR market liquidity & activate UI」를 실행하세요.'
    try:
        obj=json.loads(DATA.read_text(encoding='utf-8'))
        if (obj.get('status')!='source_validated' or obj.get('source')!=SOURCE
            or obj.get('unit_assumption')!='100M_KRW_per_raw_integer'):
            raise ValueError('출처·단위 가정·검증 상태 불일치')
        h=obj.get('history')
        if not isinstance(h,list) or len(h)<20:
            raise ValueError('일별 이력 20거래일 미만')
        prev=None
        for r in h:
            d=date.fromisoformat(r['date'])
            if prev is not None and d<=prev:
                raise ValueError('날짜 중복 또는 역순')
            prev=d
            for k in ('deposit_raw_100m','credit_raw_100m','deposit_diff_raw_100m','credit_diff_raw_100m'):
                if type(r.get(k)) is not int:
                    raise ValueError(f'{r["date"]}: {k} 값이 정수가 아님')
            if r['deposit_raw_100m']<=0 or r['credit_raw_100m']<=0:
                raise ValueError('양의 예탁금/신용잔고 필요')
        if obj.get('latest_date')!=h[-1]['date']:
            raise ValueError('최신 거래일 불일치')
        return (obj,h),None
    except (ValueError,TypeError,KeyError,OSError,json.JSONDecodeError) as e:
        return None, f'증시 자금 파일 검증 오류: {e}'


def valid_window(frame,n):
    if len(frame)<n:
        return None
    chunk=frame.iloc[-n:]
    span=(chunk.index[-1]-chunk.index[0]).days
    limits={5:10,20:40,60:120}
    if span>limits.get(n,n*2):
        return None
    return chunk


def osc(frame,col):
    a=valid_window(frame,5)
    b=valid_window(frame,20)
    if a is None or b is None or b[col].mean()<=0:
        return None
    return (a[col].mean()/b[col].mean()-1)*100


def leverage_position_60(frame):
    chunk=valid_window(frame,60)
    if chunk is None:
        return None
    values=chunk['credit_ratio_pct']
    if values.max()==values.min():
        return None
    return (values.iloc[-1]-values.min())/(values.max()-values.min())*100


def make_frame(h):
    df=pd.DataFrame(h)
    df.index=pd.to_datetime(df.pop('date'))
    df.index.name='날짜'
    df['deposit_trillion']=df['deposit_raw_100m']/10000
    df['credit_trillion']=df['credit_raw_100m']/10000
    df['credit_ratio_pct']=100*df['credit_raw_100m']/df['deposit_raw_100m']
    df['deposit_osc_pct']=100*(df['deposit_raw_100m'].rolling(5).mean()/df['deposit_raw_100m'].rolling(20).mean()-1)
    df['credit_osc_pct']=100*(df['credit_raw_100m'].rolling(5).mean()/df['credit_raw_100m'].rolling(20).mean()-1)
    return df


def pretty(x,suffix):
    return '자료 부족' if x is None else f'{x:+.2f}{suffix}'


def render_market_liquidity():
    st.subheader('💰 증시 자금 | 예탁금·신용융자·오실레이터')
    st.caption('게시된 증시 주변자금의 일별 잔고 · 별도 수집 기준일 · TOP 200/주식 수급과 무관한 계정 단위 지표')
    result,issue=read_liquidity()
    if issue:
        st.warning(issue)
        st.caption('원자료가 없으면 추정 숫자나 신호를 표시하지 않습니다.')
        return
    obj,h=result
    df=make_frame(h)
    last=df.iloc[-1]
    source_age=(datetime.now(ZoneInfo('Asia/Seoul')).date()-df.index[-1].date()).days
    st.caption(f"자료 기준일 **{obj['latest_date']}** · {len(df)}개 게시 거래일 · 출처: Npay 증권 비공식 공개 JSON · 수집시각 {obj.get('collected_at_kst','-')}")
    st.warning('단위 주의: API 원문에는 단위 표기가 없습니다. 아래 조원 금액은 **원자료 1단위=1억원으로 해석한 참고값**이며 금융투자협회 공식 수치와 독립 대조가 아직 필요합니다. 비율·오실레이터는 동일 단위가 약분됩니다.')
    from market_signal_integrity import audit_npay_history
    audit = audit_npay_history(h)
    if audit['credit_status'] == 'mismatched':
        st.error(f"공식 대조 불일치: {audit['baseline_date']} 신용융자 금투협 {audit['credit_official_trillion']:.5f}조 vs Npay {audit['credit_npay_trillion']:.5f}조. "
                 '아래 신용잔고/예탁금 비율은 비공식 원천 기준이므로 공식 위험 점수로 사용하지 않습니다.')
    else:
        st.warning('신용융자 공식 교차검증 최신 자료 미확인. 아래 레버리지 비율은 참고용이며 종합 신호에 합산하지 않습니다.')
    if source_age>5:
        st.warning(f'마지막 게시 기준일은 {source_age}일 전입니다. 당일 지수 신호와 동일 날짜로 비교하지 마세요.')

    c1,c2,c3=st.columns(3)
    c1.metric('투자자예탁금 · 조원(단위 가정)',f'{last["deposit_trillion"]:,.2f}',
              f'{last["deposit_diff_raw_100m"]/10000:+.2f}조 (게시 전일 대비)')
    c2.metric('신용융자잔고 · 조원(단위 가정)',f'{last["credit_trillion"]:,.2f}',
              f'{last["credit_diff_raw_100m"]/10000:+.2f}조 (게시 전일 대비)')
    c3.metric('신용잔고 / 예탁금',f'{last["credit_ratio_pct"]:.2f}%')

    st.markdown('#### 5·20일 자금 모멘텀 오실레이터')
    d_osc=osc(df,'deposit_raw_100m')
    c_osc=osc(df,'credit_raw_100m')
    p_60=leverage_position_60(df)
    a,b,c=st.columns(3)
    a.metric('예탁금 5일 / 20일 평균 괴리',pretty(d_osc,'%'))
    b.metric('신용잔고 5일 / 20일 평균 괴리',pretty(c_osc,'%'))
    c.metric('신용/예탁 비율 60일 범위 위치','자료 부족' if p_60 is None else f'{p_60:.1f}/100')
    st.caption('오실레이터 = (최근 5거래일 평균 ÷ 최근 20거래일 평균 − 1) × 100. 비율 위치 = 최근 60거래일 최저 0 / 최고 100. 20·60거래일이 축적되지 않으면 표시하지 않습니다.')

    view=df.tail(120)
    chart=go.Figure()
    chart.add_scatter(x=view.index,y=view['deposit_trillion'],mode='lines',name='예탁금 (조원, 가정)')
    chart.add_scatter(x=view.index,y=view['credit_trillion'],mode='lines',name='신용융자 (조원, 가정)')
    chart.update_layout(height=300,legend=dict(orientation='h'),margin=dict(l=10,r=10,t=15,b=15),yaxis_title='조원 (단위 가정)',hovermode='x unified')
    st.plotly_chart(chart,use_container_width=True)

    oschart=go.Figure()
    oschart.add_scatter(x=view.index,y=view['deposit_osc_pct'],mode='lines',name='예탁금 5/20 (%)')
    oschart.add_scatter(x=view.index,y=view['credit_osc_pct'],mode='lines',name='신용융자 5/20 (%)')
    oschart.add_hline(y=0,line_width=1)
    oschart.update_layout(height=260,legend=dict(orientation='h'),margin=dict(l=10,r=10,t=12,b=12),yaxis_title='5/20 평균 괴리 (%)',hovermode='x unified')
    st.plotly_chart(oschart,use_container_width=True)

    # Interpretation based on explicit indicators, never a direct trading order.
    if d_osc is not None and c_osc is not None:
        if d_osc<0 and c_osc>0:
            st.info('관찰: 예탁금 단기 평균은 장기 평균보다 낮고 신용융자는 높습니다. 레버리지 부담과 현금 여력 간 괴리를 함께 점검하세요.')
        elif d_osc>0 and c_osc<0:
            st.info('관찰: 예탁금 단기 평균이 높고 신용융자는 낮습니다. 현금 여력과 레버리지 축소가 함께 나타나는지 추가 확인하세요.')
        else:
            st.caption('예탁금·신용융자 오실레이터는 각각 참고 지표이며 단독 매수·매도 신호가 아닙니다.')
    with st.expander('원자료 날짜·금액·신용비율 및 CSV 다운로드'):
        cols=['deposit_raw_100m','credit_raw_100m','deposit_diff_raw_100m','credit_diff_raw_100m','credit_ratio_pct','deposit_osc_pct','credit_osc_pct']
        out=df[cols].rename(columns={'deposit_raw_100m':'예탁금 (억원 가정)','credit_raw_100m':'신용융자 (억원 가정)',
                          'deposit_diff_raw_100m':'예탁금 증감 (억원 가정)','credit_diff_raw_100m':'신용융자 증감 (억원 가정)',
                          'credit_ratio_pct':'신용/예탁 비율 (%)','deposit_osc_pct':'예탁금 오실레이터 (%)','credit_osc_pct':'신용융자 오실레이터 (%)'})
        st.dataframe(out.sort_index(ascending=False).round(3),use_container_width=True)
        st.download_button('📥 증시 자금 CSV',out.to_csv().encode('utf-8-sig'),file_name='miner_market_liquidity.csv',mime='text/csv',key='miner_liquidity_csv')
    st.caption('공식 KOFIA와 범위·단위를 교차검증하기 전 임의 점수화나 매매 신호로 사용하지 않습니다. 신규 입력 데이터가 아닌 일별 게시 자료이므로 시차가 있습니다.')
