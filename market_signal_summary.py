"""Market signal evidence summary (official KOFIA + saved ADR20).

Designed for existing `app.py` market_signal() entrypoint:
  render_market_signal_integrity(states, datasets, oneil_market_state)
No unvalidated composite risk score and no UI network loops.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import streamlit as st

ROOT=Path(__file__).resolve().parent
KST=ZoneInfo('Asia/Seoul')

def read_dated(path,status,minimum=1):
    try:
        j=json.loads((ROOT/path).read_text(encoding='utf-8'))
        h=j.get('history')
        if j.get('status')!=status or not isinstance(h,list) or len(h)<minimum:
            return None
        dates=[r['date'] for r in h]
        if dates!=sorted(set(dates)) or dates[-1]!=j.get('latest_date'):
            return None
        for d in dates:date.fromisoformat(d)
        return j
    except (KeyError,TypeError,ValueError,OSError,json.JSONDecodeError):
        return None

def show_price(datasets,states,oneil_market_state):
    st.markdown('**📉 지수 추세 · DD · FTD**')
    if set(states)!= {'KOSPI','KOSDAQ'}:
        st.info('두 지수의 가격 자료가 모두 확보되지 않아 동시 추세 비교를 보류합니다.')
        return
    days={s['date'].date().isoformat() for s in states.values()}
    if len(days)!=1:
        st.warning('코스피·코스닥의 자료 날짜가 서로 다릅니다.');return
    score=sum(sum(bool(flag) for flag in s['flags']) for s in states.values())
    st.metric('이동평균 기반 추세 조건',f'{score} / 8')
    st.caption(f'{next(iter(days))} 기준 · 기존 지수 추세 게이지. 예탁금·신용잔고·ADR 점수를 섞지 않음')
    from market_signal_qa import assess_market_signal
    for name in ('KOSPI','KOSDAQ'):
        if name not in datasets: continue
        audit=assess_market_signal(datasets[name],oneil_market_state)
        if audit['status']!='verified':
            st.warning(f'{name}: DD·FTD 검증 보류 — {audit["reason"]}')
            continue
        ftd_text=audit['ftd'] or '현재 유효 없음'
        st.caption(f'{name}: 검증된 유효 DD {audit["dd_count"]}회 · FTD {ftd_text} · 상태 {audit["market_status"]} · 거래량 연속 80일 검증')
    st.caption('DD·FTD는 광부 자체 지수 가격·거래량 규칙. 네이버 지수 거래량은 야후 종가와 날짜 대조했으나 KRX/IBD 공식 신호가 아닙니다.')

def show_official_liquidity():
    st.markdown('**💰 공식 증시 자금 · 예탁금·신용융자**')
    obj=read_dated('data/kr_kofia_liquidity.json','official_source_validated',minimum=60)
    if obj is None or obj.get('unit')!='KRW_million':
        st.warning('금융투자협회 공식 검증 자료 미확보. 비공식 자료로 공식 잔고를 대신 표시하지 않습니다.')
        return
    h=obj['history'];last=h[-1]
    if any(type(last.get(k)) is not int or last[k]<=0 for k in ('deposit_million_krw','credit_million_krw')):
        st.warning('금투협 공식 금액 형식 검증 실패');return
    d=last['deposit_million_krw']/1_000_000
    c=last['credit_million_krw']/1_000_000
    a,b,z=st.columns(3)
    a.metric('예탁금',f'{d:.2f}조')
    b.metric('신용융자',f'{c:.2f}조')
    z.metric('신용/예탁',f'{100*c/d:.2f}%')
    st.caption(f"금투협 FreeSIS {obj['latest_date']} 기준 · 조원 단위 · 지수 가격 자료일과 다를 수 있음")
    def osc(k):
        if len(h)<20:return None
        x=sum(r[k] for r in h[-5:])/5
        y=sum(r[k] for r in h[-20:])/20
        return (x/y-1)*100 if y>0 else None
    ao=osc('deposit_million_krw');co=osc('credit_million_krw')
    if ao is not None and co is not None:
        st.caption(f'5/20일 평균 괴리: 예탁금 {ao:+.2f}% · 신용융자 {co:+.2f}%')
def show_flows():
    st.markdown('**🏦 전체 현물·선물 외국인 수급**')
    spot=read_dated('data/kr_market_total_flow.json','verified')
    if not spot:
        st.info('시장 전체 현물 자료를 검증할 수 없습니다.');return
    s=spot['history'][-1]
    try:
        f=sum(s[m]['foreign_net_krw'] for m in ('KOSPI','KOSDAQ'))
        if type(f) is not int:raise ValueError('invalid')
    except (KeyError,TypeError,ValueError):
        st.warning('현물 외국인 금액 형식 오류');return
    st.metric('전체 현물 외국인 순매수',f'{f/1e8:+,.0f}억원')
    st.caption(f'코스피+코스닥 {s["date"]} 기준 · 현물 거래대금')
    fut=read_dated('data/kr_futures_flow.json','verified')
    if fut is None or fut.get('unit')!='contracts':
        st.caption('선물 원자료 미확보');return
    v=fut['history'][-1]
    if v['date']!=s['date']:
        st.info(f'선물 {v["date"]} / 현물 {s["date"]}: 날짜가 달라 방향 비교 보류');return
    qty=v.get('foreign_net_contracts');notional=v.get('foreign_net_notional_krw')
    if type(qty) is not int or type(notional) is not int:
        st.warning('선물 계약·명목금액 형식 오류');return
    st.caption(f'선물 외국인 {qty:+,}계약 · 추정 순매수 명목금액 {notional/1e8:+,.0f}억원')
    side=lambda x:'매수' if x>0 else '매도' if x<0 else '중립'
    st.info(f'외국인 방향: 현물 {side(f)} / 선물 {side(qty)} · 선물 명목금액은 현물 금액에 합산 금지')

def render_market_signal_integrity(states,datasets,oneil_market_state):
    st.divider()
    st.markdown('### 🔎 시장신호 근거판 | 공식 자금·ADR·DD·FTD')
    st.caption('여러 날짜·범위의 공개 원자료를 별도 표시합니다. 확인되지 않은 종합 매수·매도 점수는 만들지 않습니다.')
    left,right=st.columns(2)
    with left:
        show_price(datasets,states,oneil_market_state)
        from market_signal_adr_ui import show_adr_history
        show_adr_history(compact=True)
    with right:
        show_official_liquidity()
        show_flows()
    from market_signal_qa import render_quality_detail
    render_quality_detail(datasets, oneil_market_state)
    st.caption('시장 추세 게이지는 기존 8개 가격 조건만 반영. ADR20·금투협 자금·DD·FTD·현물/선물 수급은 독립 근거이며 종합 점수화는 별도 백테스트 이후 검토합니다.')
