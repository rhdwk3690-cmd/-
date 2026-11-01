"""Offline market-environment journal: show only observed labels and matured returns."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from market_regime_journal import SCHEMA, HORIZONS, MARKETS, validate_prices, evaluate

FILE = Path(__file__).resolve().parent/'data'/'kr_market_regime_journal.json'
LABELS = {'defensive':'방어 우선','watch':'반등 관찰','conditional':'조건부 시험 진입',
          'expansion':'매수 확대 검토','withheld':'판정 보류'}


def render_journal_history():
    st.divider()
    st.markdown('#### 📚 시장 환경 일별 판정·사후 성과 추적')
    st.caption('날짜별 시장 환경 판정은 실제 관측한 당시에만 고정합니다. 이후 5·20·60거래일이 지나야 해당 지수의 종가 수익률과 종가 기준 MDD가 확정됩니다.')
    if not FILE.exists():
        st.info('아직 시장 환경 일별 저장 기록이 없습니다. 18:35 통합수집 실행 후 기록이 생깁니다.')
        return
    try:
        j=json.loads(FILE.read_text(encoding='utf-8'))
        if j.get('schema')!=SCHEMA or not isinstance(j.get('records'),list):
            raise ValueError('저장 파일 스키마 불일치')
        prices=validate_prices(j['index_closes'],through=pd.Timestamp.now(tz='Asia/Seoul').date())
        records=j['records']
        if [x['date'] for x in records] != sorted(set(x['date'] for x in records)):
            raise ValueError('중복·역순 판정 기록')
        for x in records:
            if x.get('code') not in LABELS or x.get('forward') != evaluate(prices,signal_date=x['date']):
                raise ValueError('판정 상태 또는 미래 성과 검산 불일치')
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
        st.warning(f'시장 환경 저장 기록 검증 보류: {exc}')
        return
    if not records:
        st.info('수집기는 연결됐지만 아직 검증 가능한 시장 환경 날짜가 없습니다.')
        return
    valid=[r for r in records if r['code']!='withheld']
    st.caption(f'기록 {len(records)}개 날짜 · 유효 판정 {len(valid)}개 · 판정 보류 {len(records)-len(valid)}개 · 최종 업데이트 {j.get("updated_at_kst","-")}')
    summary=[]
    for r in reversed(records):
        item={'판정일':r['date'],'관측시각':r.get('observed_at_kst'),
              '환경':LABELS[r['code']],'이유':'; '.join(r.get('reasons',[]))[:170]}
        for h in HORIZONS:
            outcome=r['forward'][str(h)]
            for market in MARKETS:
                item[f'{market} {h}일 수익률(%)']=outcome[market]['return_pct'] if outcome['status']=='mature' else None
                item[f'{market} {h}일 MDD(%)']=outcome[market]['max_drawdown_pct'] if outcome['status']=='mature' else None
        summary.append(item)
    frame=pd.DataFrame(summary)
    st.dataframe(frame,hide_index=True,use_container_width=True)
    st.download_button('📥 시장 환경 판정 및 5·20·60일 결과 CSV',frame.to_csv(index=False).encode('utf-8-sig'),
                       file_name='miner_market_regime_forward.csv',mime='text/csv',key='market_regime_journal_csv')
    grouped=[]
    for label,rows in [(label,[x for x in valid if x['code']==code]) for code,label in LABELS.items() if code!='withheld']:
        for h in HORIZONS:
            for market in MARKETS:
                obs=[r['forward'][str(h)][market] for r in rows if r['forward'][str(h)]['status']=='mature']
                grouped.append({'시장 환경':label,'시장':market,'기간':f'{h}거래일','실현 표본':len(obs),
                                '평균 이후 수익률(%)':round(sum(x['return_pct'] for x in obs)/len(obs),3) if obs else None,
                                '평균 구간 MDD(%)':round(sum(x['max_drawdown_pct'] for x in obs)/len(obs),3) if obs else None})
    if grouped:
        st.markdown('**판정 환경별 성과 (성숙된 관측만)**')
        st.dataframe(pd.DataFrame(grouped),hide_index=True,use_container_width=True)
    st.caption('주: 시장 환경은 포지션이 아닌 관측 상태. 표본은 날짜가 겹쳐 독립적이지 않으며, 평균 성과는 전략 수익률·인과 검증이 아닙니다. MDD는 종가 기준이고 장중 손실·체결·비용·배당을 반영하지 않습니다. 표본 부족 시 수치가 비어 있는 것이 정상입니다.')
