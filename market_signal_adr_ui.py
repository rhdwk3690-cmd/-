"""Offline ADR20 UI shared by signal summary and market breadth detail page."""
from __future__ import annotations
import json
from datetime import date,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA=Path(__file__).resolve().parent/'data'/'kr_market_adr20.json'
SOURCE='maedong.kr public market breadth (KOSPI+KOSDAQ combined)'

def read_adr(path=DATA):
    try:
        d=json.loads(path.read_text(encoding='utf-8'))
        if d.get('status')!='verified' or d.get('source')!=SOURCE or d.get('unit')!='stocks':
            raise ValueError('출처/단위/검증 상태 불일치')
        h=d.get('history')
        if not isinstance(h,list) or len(h)<20:
            raise ValueError('20거래일 이상의 날짜별 집계 필요')
        prev=None
        for row in h:
            curr=date.fromisoformat(row['date'])
            if prev and curr<=prev:
                raise ValueError('날짜 중복/역순')
            if curr.weekday()>=5:
                raise ValueError('주말 시세 기록')
            prev=curr
            a=[row.get(k) for k in ('up','down','flat','universe_total')]
            if any(type(x)!=int for x in a) or any(x<0 for x in a) or sum(a[:3])!=a[3] or not 1400<=a[3]<=5000:
                raise ValueError('일자별 종목 수 불일치')
        if h[-1]['date']!=d.get('latest_date'):
            raise ValueError('최신 날짜 불일치')
        last=h[-20:]
        for x,y in zip(last[:-1],last[1:]):
            if (date.fromisoformat(y['date'])-date.fromisoformat(x['date'])).days>8:
                raise ValueError('최근 20거래일 간 기록 공백')
        up=sum(x['up'] for x in last); down=sum(x['down'] for x in last)
        if down==0:raise ValueError('하락 종목 분모 0')
        computed=round(100*up/down,2)
        m=d.get('adr20') or {}
        if m.get('value_pct')!=computed or m.get('up_sum')!=up or m.get('down_sum')!=down or m.get('end_date')!=h[-1]['date']:
            raise ValueError('저장 ADR20 및 원자료 재계산 값이 다름')
        age=(datetime.now(ZoneInfo('Asia/Seoul')).date()-date.fromisoformat(h[-1]['date'])).days
        if age>8 or age<0:
            raise ValueError(f'자료 기준일 지연 또는 미래: {h[-1]["date"]}')
        return d,None
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        return None,str(exc)

def show_adr_history(*,compact=False):
    d,issue=read_adr()
    if compact:
        st.markdown('**🌐 전체시장 ADR20 · 일별 저장값**')
    else:
        st.markdown('##### 🌐 KOSPI+KOSDAQ 전체시장 ADR20 (일별 자동 저장)')
    if issue:
        st.info('ADR20 저장된 최신 20거래일 검증 자료가 없습니다: '+issue[:145])
        st.caption('장마감 통합수집의 「시장 폭 ADR20」 수집 단계가 성공하면 자동 표시됩니다. 화면에서 30개 API를 재조회하지 않습니다.')
        return
    latest=d['adr20'];value=latest['value_pct']
    if value<80:
        label='시장 상승 종목 부족 (관행적 침체 구간)'
    elif value>120:
        label='상승 종목 우세 (관행적 과열 구간)'
    else:
        label='상승/하락 종목 수의 균형 부근'
    st.metric('전체시장 ADR20',f'{value:.1f}%',help='20거래일 상승 종목 수 합계 / 하락 종목 수 합계 × 100')
    st.caption(f"자료일 {d['latest_date']} · 저장일 {latest['start_date']}~{latest['end_date']} · 상승 누계 {latest['up_sum']:,} / 하락 누계 {latest['down_sum']:,} · {label}")
    st.caption('공개 매동 시장 폭 자료 기반 자체 계산. 비공식 KRX ADR이며 현재 거래일 속보는 제외. ADR 단독으로 매수·매도하지 않습니다.')
    if compact:return
    rows=d['history']
    dates=[];values=[]
    for i in range(19,len(rows)):
        win=rows[i-19:i+1]
        if any((date.fromisoformat(b['date'])-date.fromisoformat(a['date'])).days>8 for a,b in zip(win[:-1],win[1:])):
            continue
        down=sum(x['down'] for x in win)
        if down==0:continue
        dates.append(rows[i]['date']);values.append(100*sum(x['up'] for x in win)/down)
    if dates:
        fig=go.Figure()
        fig.add_scatter(x=dates,y=values,mode='lines+markers',name='전체시장 ADR20')
        for threshold in (80,100,120):fig.add_hline(y=threshold,line_dash='dot',line_width=1)
        fig.update_layout(height=270,margin=dict(l=5,r=5,t=10,b=10),hovermode='x unified',yaxis_title='ADR20 (%)')
        st.plotly_chart(fig,use_container_width=True)
    frame=pd.DataFrame(rows).iloc[::-1]
    st.dataframe(frame,hide_index=True,use_container_width=True)
    st.download_button('📥 ADR20 일별 상승·하락 종목 CSV',frame.to_csv(index=False).encode('utf-8-sig'),file_name='miner_adr20_stored.csv',mime='text/csv',key='miner_adr20_saved_csv')
