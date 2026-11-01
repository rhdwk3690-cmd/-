"""Evidence-based market environment view; never suggests portfolio weights."""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from market_regime import classify_environment, RULE_VERSION

ROOT=Path(__file__).resolve().parent
KST=ZoneInfo('Asia/Seoul')


def _json(path):
    try:
        return json.loads((ROOT/path).read_text(encoding='utf-8'))
    except (OSError,ValueError,TypeError):
        return None


def _sources_info():
    """Additional independent evidence; NONE changes entry-environment result."""
    k=_json('data/kr_kofia_liquidity.json')
    if k and k.get('status')=='official_source_validated' and k.get('unit')=='KRW_million' and len(k.get('history',[]))>=20:
        h=k['history'];x=h[-1]
        if isinstance(x.get('deposit_million_krw'),int) and isinstance(x.get('credit_million_krw'),int) and x['deposit_million_krw']>0:
            dep=x['deposit_million_krw']/1e6;cred=x['credit_million_krw']/1e6
            st.caption(f'금투협 공식 증시 자금 **{x["date"]}** · 예탁금 {dep:.2f}조 · 신용 {cred:.2f}조 · 신용/예탁 {cred/dep*100:.1f}%')
    spot=_json('data/kr_market_total_flow.json')
    if spot and spot.get('status')=='verified' and spot.get('history'):
        x=spot['history'][-1]
        try:
            f=x['KOSPI']['foreign_net_krw']+x['KOSDAQ']['foreign_net_krw']
            if type(f) is int:
                st.caption(f'현물 외국인 순매수 **{x["date"]}** · 코스피+코스닥 {f/1e8:+,.0f}억원 (별도 보조 근거)')
        except (KeyError,TypeError,ValueError):
            pass


def render_market_environment(states,datasets,oneil_market_state):
    st.divider()
    st.markdown('### 🧭 시장 환경 판단 · 실험 규칙 v1')
    st.caption('DD·FTD 독립검증, 지수 가격추세 8개 조건, 저장된 ADR20을 결합한 **매수 가능 환경 필터**입니다. 아직 백테스트로 검증되지 않은 가설이며 종목 매수·매도 지시나 추천 주식 비중이 아닙니다.')
    from market_signal_qa import assess_market_signal
    qa={}
    for name in ('KOSPI','KOSDAQ'):
        if name in datasets:
            try:
                qa[name]=assess_market_signal(datasets[name],oneil_market_state)
            except Exception as exc:
                qa[name]={'status':'withheld','reason':f'{type(exc).__name__} 오류'}
    result=classify_environment(states,qa,_json('data/kr_market_adr20.json'),today=datetime.now(KST).date())
    if result['code']=='withheld':
        st.warning('시장 환경 **판정 보류** · ' + '; '.join(result['reasons']))
        st.caption('누락된 지수 거래량을 임의 보정하거나 저장 ADR 대신 다른 날짜 자료를 사용하지 않습니다.')
    else:
        color='error' if result['code']=='defensive' else 'info'
        st.markdown(f'**현재 관찰 환경: {result["status"]}**')
        left,mid,right=st.columns(3)
        left.metric('가격 추세 조건',f'{result["price_flags"]}/8')
        mid.metric('전체시장 ADR20',f'{result["adr20"]["value"]:.2f}%')
        right.metric('유효 DD',f'코스피 {result["dd_counts"]["KOSPI"]} / 코스닥 {result["dd_counts"]["KOSDAQ"]}')
        st.caption(f'지수 가격 {result["date"]} · ADR {result["adr20"]["date"]} · 독립검증된 FTD {result["ftd_count"]}개 지수')
        for s in result['reasons']:
            st.write('• '+s)
        if result['code']=='defensive':
            st.warning('새로운 포지션 확대보다 위험 노출과 기존 보유종목의 추세 이탈 여부를 우선 확인할 환경입니다. 기계적 전량 매도 신호는 아닙니다.')
        elif result['code'] in {'conditional','expansion'}:
            st.info('시장의 진입 환경만 충족한 상태입니다. 실적 증가·시장 대비 RS·DI/ADX·ATR·손절/포지션 크기 조건을 종목별로 추가 검증해야 합니다.')
    from market_regime_journal_ui import render_journal_history
    render_journal_history()
    with st.expander('실험적 판정 규칙 · 기준값과 독립 보조근거',expanded=False):
        st.markdown('''- **방어 우선:** 어느 한 지수 DD≥4회, 또는 추세≤3/8 & ADR20<80%, 또는 추세≤2/8 & ADR20<100%.
- **매수 확대 조건 검토:** 양 지수 유효 FTD, 추세≥6/8, 각 DD≤2회, ADR20≥110%, 양 지수 시장 상태 `상승 확인`.
- **조건부 시험 진입:** 최소 한 지수 유효 FTD, 추세≥4/8, 각 DD≤2회, ADR20≥90%.
- **반등 관찰:** 위 세 조건 어디에도 속하지 않는 검증 완료 구간.
- **판정 보류:** DD·FTD 검증 실패, 지수 날짜 불일치·지연, ADR20 미검증 또는 지연.

ADR 경계값 80·90·110과 DD/추세 조건은 **검증되지 않은 초기 가설**입니다. 20거래일 이후 손익·MDD·매매 횟수 등의 백테스트를 거쳐 조정해야 합니다.''')
        _sources_info()
        st.caption(f'규칙 버전: {RULE_VERSION} · 동시 거래일 자료를 우선하며 금투협·외국인 수급은 규칙 점수에 임의 합산하지 않음')
