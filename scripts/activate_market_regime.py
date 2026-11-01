"""Idempotently add a market environment evidence view to existing summary UI."""
from __future__ import annotations
import ast
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SUMMARY=ROOT/'market_signal_summary.py'
CORE=ROOT/'market_regime.py'
UI=ROOT/'market_regime_ui.py'
OLD=("    from market_signal_qa import render_quality_detail\n"
     "    render_quality_detail(datasets, oneil_market_state)\n"
     "    st.caption('시장 추세 게이지는 기존 8개 가격 조건만 반영. ADR20·금투협 자금·DD·FTD·현물/선물 수급은 독립 근거이며 종합 점수화는 별도 백테스트 이후 검토합니다.')")
NEW=("    from market_signal_qa import render_quality_detail\n"
     "    render_quality_detail(datasets, oneil_market_state)\n"
     "    from market_regime_ui import render_market_environment\n"
     "    render_market_environment(states, datasets, oneil_market_state)\n"
     "    st.caption('시장 추세 게이지는 기존 8개 가격 조건만 반영. ADR20·금투협 자금·DD·FTD·현물/선물 수급은 독립 근거이며 종합 점수화는 별도 백테스트 이후 검토합니다.')")

def activate(summary=SUMMARY,core=CORE,ui=UI):
    for p in (core,ui,summary):
        if not p.exists():
            raise ValueError(f'required file missing: {p.name}')
        ast.parse(p.read_text(encoding='utf-8'))
    before=summary.read_text(encoding='utf-8')
    if NEW in before and before.count(NEW)==1:
        print('Market environment panel is already installed')
        return False
    if before.count(OLD)!=1:
        raise RuntimeError('Market-signal summary insertion anchor changed: no edits made')
    after=before.replace(OLD,NEW,1)
    if not all(x in after for x in ('show_official_liquidity()', 'show_flows()', 'show_adr_history(compact=True)', 'render_quality_detail(datasets, oneil_market_state)')):
        raise RuntimeError('existing market signal panel missing, abort without edits')
    ast.parse(after)
    tmp=summary.with_name('market_signal_summary.py.market_regime.tmp')
    tmp.write_text(after,encoding='utf-8')
    os.replace(tmp,summary)
    print('Activated market environment rule panel; official KOFIA, ADR, DD/FTD and flows preserved')
    return True

if __name__=='__main__':activate()
