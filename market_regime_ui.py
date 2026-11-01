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


def render_market_environment_compact(states, datasets, oneil_market_state, quality_reports=None):
    """Compact, clickable environment headline. Detail opens only on request.

    Reuses the independent audits calculated by the market signal home;
    no new market score, no changed rule, no data interpolation.
    """
    from market_signal_qa import assess_market_signal
    if quality_reports is None:
        quality_reports = {}
        for name in ('KOSPI', 'KOSDAQ'):
            if name in datasets:
                try:
                    quality_reports[name] = assess_market_signal(datasets[name], oneil_market_state)
                except Exception as exc:
                    quality_reports[name] = {'status':'withheld', 'reason':type(exc).__name__}
    result = classify_environment(
        states, quality_reports, _json('data/kr_market_adr20.json'),
        today=datetime.now(KST).date())
    icon = {
        'defensive':'🛡️', 'watch':'👀', 'conditional':'🧪',
        'expansion':'📈', 'withheld':'⏸️'
    }.get(result['code'], '⏸️')
    label = result['status']
    st.markdown('### 🧭 현재 시장 관찰 환경')
    with st.expander(f'{icon} **{label}**  ·  눌러서 판정 근거 보기', expanded=False):
        if result['code'] == 'withheld':
            st.warning('독립 검증이 통과되지 않아 시장 환경 판정을 보류합니다.')
            for why in result.get('reasons', []):
                st.write('• ' + str(why))
            st.caption('검증되지 않은 거래량이나 다른 날짜의 ADR을 임의 보정하지 않습니다.')
        else:
            a, b, c = st.columns(3)
            a.metric('가격 추세', f'{result["price_flags"]}/8')
            b.metric('전체 시장 ADR20', f'{result["adr20"]["value"]:.2f}%')
            c.metric('유효 DD', f'코스피 {result["dd_counts"]["KOSPI"]} / 코스닥 {result["dd_counts"]["KOSDAQ"]}')
            st.caption(f'지수 종가 {result["date"]} · ADR {result["adr20"]["date"]} · 독립 검증 FTD {result["ftd_count"]}개 지수')
            st.markdown('**판정 근거**')
            for why in result.get('reasons', []):
                st.write('• ' + str(why))
            if result['code'] == 'defensive':
                st.warning('포지션 확대보다 위험 노출과 보유 종목의 추세 이탈을 우선 점검할 환경입니다. 전량 매도 신호는 아닙니다.')
            elif result['code'] in ('conditional', 'expansion'):
                st.info('시장의 진입 환경만 관찰한 결과입니다. 실제 매수에는 분기 이익 증가·상대강도·DI/ADX·ATR 등 종목별 검증이 필요합니다.')
        if st.toggle('판정 기준·출처 더 보기', value=False, key='miner_compact_env_rules'):
            st.markdown("""- **방어 우선:** 한 지수의 유효 DD가 4회 이상, 또는 추세≤3/8 & ADR20<80%, 또는 추세≤2/8 & ADR20<100%.
- **매수 확대 조건 검토:** 양 지수 검증된 FTD, 추세≥6/8, 지수별 DD≤2회, ADR20≥110%, 양 지수 시장 상태 상승 확인.
- **조건부 시험 진입:** 최소 한 지수의 유효 FTD, 추세≥4/8, DD≤2회, ADR20≥90%.
- **반등 관찰:** 위 세 환경에 들지 않는 검증 완료 구간.
- **판정 보류:** 데이터 누락, 독립검증 실패, 기준일 불일치 또는 지연.

기준값은 백테스트로 입증된 것이 아닌 **초기 가설**이며, 이 분류는 개별 종목 매수·매도 신호가 아닙니다.""")
            _sources_info()
            st.caption(f'판정 버전: {RULE_VERSION} · DD·FTD는 독립검증을 통과한 경우만 사용')
    stamp = result.get('date') or '확인 대기'
    st.caption(f'가격 기준일 {stamp} · 검증된 원자료만 사용 · 연구용 시장 환경 관찰, 매매 지시 아님')


def render_market_environment(states, datasets, oneil_market_state):
    """Keep research history below the market evidence panel, initially folded.

    The compact primary status now appears at the very top of market signal home.
    """
    from market_regime_journal_ui import render_journal_history
    with st.expander('📚 시장 환경 판정 이력 · 5·20·60거래일 사후성과', expanded=False):
        render_journal_history()
