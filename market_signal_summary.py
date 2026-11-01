"""Read-only market signal evidence board: independent dates, no invented composite score."""
from __future__ import annotations
from datetime import date
from pathlib import Path

import streamlit as st

from market_signal_integrity import audit_npay_history, oscillator, load_dated_json

ROOT = Path(__file__).resolve().parent


def _valid_history(path, *, status, minimum=1):
    obj = load_dated_json(ROOT / path)
    if not isinstance(obj, dict) or obj.get('status') != status:
        return None
    h = obj.get('history')
    if not isinstance(h, list) or len(h) < minimum:
        return None
    dates = [x.get('date') if isinstance(x, dict) else None for x in h]
    if any(not isinstance(d, str) for d in dates) or dates != sorted(set(dates)):
        return None
    if obj.get('latest_date') != dates[-1]:
        return None
    return obj


def _show_liquidity():
    obj = _valid_history('data/kr_market_liquidity.json', status='source_validated', minimum=20)
    if obj is None:
        st.warning('예탁금·신용잔고: 검증된 일별 파일 없음. 자금 판단 보류')
        return
    history = obj['history']; last = history[-1]; audit = audit_npay_history(history)
    d_osc = oscillator(history, 'deposit_raw_100m')
    st.markdown('**💰 증시 대기자금**')
    st.caption(f"Npay 공개자료 {last['date']} 기준 · 5일/20일 이동평균(거래일) · 지수 날짜와 다를 수 있음")
    if d_osc is None:
        st.info('예탁금 오실레이터 자료 부족')
    else:
        st.metric('예탁금 모멘텀 5/20', f'{d_osc:+.2f}%')
    if audit['deposit_status'] == 'matched':
        st.caption('금투협 10/29 통계의 전일(10/28) 예탁금과 Npay 10/28 값 일치')
    else:
        st.caption('예탁금 공식 교차검증: 별도 확인 필요')
    if audit['credit_status'] == 'mismatched':
        diff = abs(audit['credit_difference_100m_krw'])
        st.error(f"신용잔고 공식 대조 불일치! {audit['baseline_date']} 금투협 {audit['credit_official_trillion']:.5f}조 / "
                 f"Npay {audit['credit_npay_trillion']:.5f}조 (차이 약 {diff:,.1f}억원). "
                 '신용/예탁 비율과 레버리지 신호는 종합판정에서 제외')
    else:
        st.warning('신용잔고 공식 단위·범위의 최신 일별 교차검증 불충분. 레버리지 신호는 종합판정 제외')
    st.caption('금투협 공식 기준: https://freesis.kofia.or.kr/stat/main.do (10/29 값과 증감액에서 10/28 역산)')


def _show_flows():
    obj = _valid_history('data/kr_market_total_flow.json', status='verified')
    st.markdown('**🏦 전체 현물·선물 외국인 수급**')
    if obj is None:
        st.info('시장 전체 현물 수급 파일 미검증')
        return
    spot = obj['history'][-1]
    try:
        foreign = sum(spot[market]['foreign_net_krw'] for market in ('KOSPI','KOSDAQ'))
        if type(foreign) is not int:
            raise ValueError('noninteger')
    except (KeyError, ValueError, TypeError):
        st.warning('현물 외국인 금액 형식 오류'); return
    st.metric('전체 현물 외국인 순매수', f'{foreign/1e8:+,.0f}억원')
    st.caption(f"현물 {spot['date']} 기준 · KOSPI+KOSDAQ · Npay 비공식 JSON")
    futures = _valid_history('data/kr_futures_flow.json', status='verified')
    if not futures:
        st.info('선물 자료 미검증'); return
    f = futures['history'][-1]
    if f['date'] != spot['date']:
        st.warning(f"현물 {spot['date']} / 선물 {f['date']}: 날짜가 달라 방향 비교 보류");return
    if futures.get('unit') != 'contracts' or futures.get('nominal_quality') != 'estimated_from_Npay_trade_prices_million_krw':
        st.warning('선물 계약/명목금액 검증 상태 불일치');return
    qty, nominal = f.get('foreign_net_contracts'), f.get('foreign_net_notional_krw')
    if type(qty) is not int or type(nominal) is not int:
        st.warning('선물 수급 원자료 형식 오류'); return
    st.metric('선물 외국인 순매수', f'{qty:+,}계약')
    st.caption(f'선물 추정 순매수 명목금액 {nominal/1e8:+,.0f}억원 · 현물 금액과 합산 금지 · API FUT 상품 구성 미확정')
    d1='매수' if foreign>0 else '매도' if foreign<0 else '중립'
    d2='매수' if qty>0 else '매도' if qty<0 else '중립'
    st.info(f'방향: 현물 {d1} / 선물 {d2} (당일 방향 비교만, 선물 포지션 잔고 아님)')


def _show_price(datasets, states, oneil_market_state):
    st.markdown('**📉 시장 가격·매도압력·반등 확인**')
    if len(states) != 2:
        st.warning('코스피·코스닥 지수 자료가 모두 확보되지 않아 종합 추세 판정 보류')
        return
    days = {str(x.get('date').date()) for x in states.values() if x.get('date') is not None}
    if len(days) != 1:
        st.warning('코스피·코스닥 날짜가 서로 달라 동시 추세 판정 보류')
        return
    idx_date = next(iter(days))
    score = sum(sum(bool(z) for z in s['flags']) for s in states.values())
    st.metric('지수 추세 조건 충족', f'{score} / 8')
    st.caption(f'{idx_date} 기준 · 기존 시장신호 8개 이동평균 조건만 반영 · 주식 비중이나 매매 지시 아님')
    for name in ('KOSPI', 'KOSDAQ'):
        if name not in datasets: continue
        try:
            o = oneil_market_state(datasets[name])
            status = str(o.get('status', '판정 보류'))
            dd = o.get('dd')
            dd_text = f'{len(dd)}건' if isinstance(dd, (list,tuple)) else '미확인'
            ftd = o.get('ftd')
            ftd_text = str(ftd.date()) if hasattr(ftd, 'date') else '없음'
            st.caption(f'{name}: DD {dd_text} / 간이 FTD {ftd_text} / 상태 {status} · 자체 지수 거래량 규칙')
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            st.caption(f'{name}: DD·FTD 판정 보류 ({type(exc).__name__})')


def _show_breadth_opt_in():
    st.markdown('**🌐 시장 확산도 ADR20**')
    st.caption('20거래일 상승 종목 합계 ÷ 하락 종목 합계 × 100. 조회 시 외부 날짜별 응답이 필요하므로 자동 호출하지 않습니다.')
    if st.button('ADR20 20거래일 실제 자료 확인', key='miner_integrity_adr_button'):
        try:
            from miner_breadth import load_adr20
            with st.spinner('전체시장 20거래일 상승·하락 자료 확인 중...'):
                h, adr = load_adr20()
            st.metric('전체시장 ADR20', f'{adr:.1f}%')
            st.caption(f"매동 전체시장 자료 {h['날짜'].iloc[-1]:%Y-%m-%d} 기준 · 별도 날짜·범위")
        except Exception as exc:
            st.warning(f'ADR20 검증 보류: {type(exc).__name__} ({str(exc)[:150]})')
    else:
        st.caption('ADR20은 이번 요약에서 미계산. 상세 시장 체력 화면에서 계산하거나 위 버튼을 누르세요.')


def render_market_signal_integrity(states, datasets, oneil_market_state):
    """Call only in the existing market_signal view == '종합' branch."""
    st.divider()
    st.markdown('### 🔎 시장신호 검증판 | 근거·범위·기준일')
    st.caption('예탁금/신용잔고, 가격·거래량, 외국인 현물/선물, ADR은 서로 다른 원자료입니다. 자료 부족·불일치 시 임의 보간 또는 가중 합산하지 않습니다.')
    price, money = st.columns(2)
    with price:
        _show_price(datasets,states,oneil_market_state)
        _show_breadth_opt_in()
    with money:
        _show_liquidity()
        _show_flows()
    st.warning('종합 매수·매도 점수는 확정 보류: 공식 신용잔고 교차검증 불일치 및 ADR 미확정. 기존 8개 추세 조건 점수는 가격 추세 참고값으로만 사용합니다.')
