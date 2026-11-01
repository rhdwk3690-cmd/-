"""One-time fail-closed integration into existing 18:35 EOD schedule and regime UI.

Uses exact known anchors and checks syntax before writing; idempotent.
No change to any legacy collector's logic, timings or failure severity.
"""
from __future__ import annotations
import ast
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/'scripts/run_kr_eod_batch.py'
WORKFLOW=ROOT/'.github/workflows/collect_kr_eod_batch.yml'
UI=ROOT/'market_regime_ui.py'
SOURCE=ROOT/'market_regime_journal.py'
COLLECT=ROOT/'scripts/collect_market_regime_journal.py'
PANEL=ROOT/'market_regime_journal_ui.py'
STAGE="REGIME_JOURNAL=('시장 환경 매일 판정·5/20/60일 성과','collect_market_regime_journal.py','kr_market_regime_journal.json',False)"


def one(text,old,new):
    if new in text:
        if text.count(new)!=1:raise ValueError('duplicate patched marker')
        return text
    if text.count(old)!=1:
        raise ValueError(f'expected exactly one source anchor (found {text.count(old)}): {old[:80]!r}')
    return text.replace(old,new,1)


def activate(root=ROOT):
    runner=root/'scripts/run_kr_eod_batch.py'
    workflow=root/'.github/workflows/collect_kr_eod_batch.yml'
    ui=root/'market_regime_ui.py'
    for name in ('market_regime_journal.py','market_regime_journal_ui.py',
                 'scripts/collect_market_regime_journal.py'):
        file=root/name
        ast.parse(file.read_text(encoding='utf-8'))
    old_run=runner.read_text(encoding='utf-8')
    old_yml=workflow.read_text(encoding='utf-8')
    old_ui=ui.read_text(encoding='utf-8')
    new_run=one(old_run,
        "ADR=('시장 폭 ADR20 (매동 비공식)','collect_adr_breadth.py','kr_market_adr20.json',False)\n",
        "ADR=('시장 폭 ADR20 (매동 비공식)','collect_adr_breadth.py','kr_market_adr20.json',False)\n"+STAGE+'\n')
    new_run=one(new_run,
        "    active=SOURCES+([KOFIA] if has_official_seed() else [])+[ADR]\n",
        "    active=SOURCES+([KOFIA] if has_official_seed() else [])+[ADR,REGIME_JOURNAL]\n")
    # Separate optional dependencies so PyPI failure cannot block core EOD collectors.
    new_yml=one(old_yml,
        '      - name: Collect existing market sources and bounded dated ADR20 in sequence\n',
        "      - name: Install optional journal dependencies (do not block core EOD)\n"
        "        continue-on-error: true\n"
        "        run: python -m pip install --disable-pip-version-check yfinance streamlit\n"
        '      - name: Collect existing market sources and bounded dated ADR20 in sequence\n')
    new_yml=one(new_yml,
        'data/kr_market_adr20.json miner_breadth.py;',
        'data/kr_market_adr20.json data/kr_market_regime_journal.json miner_breadth.py;')
    new_ui=one(old_ui,
        "    with st.expander('실험적 판정 규칙 · 기준값과 독립 보조근거',expanded=False):\n",
        "    from market_regime_journal_ui import render_journal_history\n"
        "    render_journal_history()\n"
        "    with st.expander('실험적 판정 규칙 · 기준값과 독립 보조근거',expanded=False):\n")
    ast.parse(new_run)
    ast.parse(new_ui)
    required=["- cron: '35 9 * * 1-5'",'market_regime_journal.json',"if: always()",'continue-on-error: true', 'requests pandas numpy']
    if not all(s in new_yml for s in required):
        raise ValueError('integration would remove 18:35 schedule, journal commit or successful-file safety')
    if "'collect_market_liquidity.py'" in new_run:
        raise ValueError('old retired Npay deposits collector unexpectedly present')
    if "data/kr_market_regime_journal.json" not in new_yml:
        raise ValueError('journal commit missing')
    diffs=[(runner,old_run,new_run),(workflow,old_yml,new_yml),(ui,old_ui,new_ui)]
    for path,old,new in diffs:
        if old!=new:
            temp=path.with_name(path.name+'.miner_journal.tmp')
            temp.write_text(new,encoding='utf-8')
            os.replace(temp,path)
    print('Market-regime journal integrated: 18:35 schedule preserved; optional collector, CSV UI linked; changed='+str(sum(a!=b for _,a,b in diffs)))
    return sum(a!=b for _,a,b in diffs)


if __name__=='__main__':
    activate()
