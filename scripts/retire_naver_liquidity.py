"""Retire only the old Npay deposit/credit collector and comparison UI.

IMPORTANT: Npay full-market cash flows and Npay futures are unrelated,
and MUST remain active. This script will not edit them.
All source changes are validated before writes; old files are recoverable in Git history.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / 'market_signal_summary.py'
OFFICIAL_UI = ROOT / 'kofia_liquidity_ui.py'
BATCH = ROOT / 'scripts' / 'run_kr_eod_batch.py'
APP = ROOT / 'app.py'
OFFICIAL_DATA = ROOT / 'data' / 'kr_kofia_liquidity.json'


def only_one(source: str, anchor: str, label: str) -> int:
    n = source.count(anchor)
    if n != 1:
        raise ValueError(f'{label}: expected 1 exact anchor, got {n}; no changes made')
    return source.index(anchor)


def between(source: str, start: str, end: str, label: str) -> str:
    a = only_one(source, start, label + ' start')
    b = only_one(source, end, label + ' end')
    if b <= a:
        raise ValueError(f'{label}: anchors reversed; no changes made')
    return source[:a] + source[b:]


def main():
    # Safety guard: only retire Npay liquidity when the official replacement is present.
    official = json.loads(OFFICIAL_DATA.read_text(encoding='utf-8'))
    if (official.get('status') != 'official_source_validated'
            or official.get('unit') != 'KRW_million'
            or len(official.get('history', [])) < 60
            or official.get('latest_date') != official['history'][-1]['date']):
        raise ValueError('KOFIA validated official deposit/credit history missing — abort retirement')
    app = APP.read_text(encoding='utf-8')
    if 'from kofia_liquidity_ui import render_kofia_liquidity' not in app:
        raise ValueError('Official KOFIA market-signal panel not active — abort retirement')

    changes: dict[Path, str] = {}

    batch = BATCH.read_text(encoding='utf-8')
    target = "    ('네이버 예탁금·신용융자 (비공식 비교용)','collect_market_liquidity.py','kr_market_liquidity.json',True),\n"
    if target in batch:
        only_one(batch, target, 'batch Npay credit collector')
        batch = batch.replace(target, '')
    elif 'collect_market_liquidity.py' in batch or 'kr_market_liquidity.json' in batch:
        raise ValueError('Batch references Npay liquidity with unknown syntax')
    changes[BATCH] = batch

    summary = SUMMARY.read_text(encoding='utf-8')
    sum_start = "    n=read_dated('data/kr_market_liquidity.json','source_validated',minimum=20)\n"
    sum_end = 'def show_flows():\n'
    if sum_start in summary:
        summary = between(summary, sum_start, sum_end, 'summary comparison')
    elif 'kr_market_liquidity.json' in summary or '네이버와 금투협 신용융자 집계가 일치하지 않습니다' in summary:
        raise ValueError('Market-signal summary has an unknown Npay comparison block')
    changes[SUMMARY] = summary

    ui = OFFICIAL_UI.read_text(encoding='utf-8')
    if 'def naver_same_day(day,path=NAVER):\n' in ui:
        ui = between(ui, 'def naver_same_day(day,path=NAVER):\n', 'def make_frame(h):\n', 'official UI Npay helper')
    elif 'def naver_same_day' in ui:
        raise ValueError('Official UI has an unknown Npay helper')
    compare_start = '    naver=naver_same_day(day)\n'
    compare_end = '    view=df.tail(120)\n'
    if compare_start in ui:
        ui = between(ui, compare_start, compare_end, 'official UI Npay comparison')
    elif ('같은 날짜 네이버 자료와 교차 비교' in ui
          or '네이버 동일 날짜 자료가 없어' in ui):
        raise ValueError('Official UI has an unknown Npay comparison')
    nav_const = "NAVER=ROOT/'data'/'kr_market_liquidity.json'\n"
    if nav_const in ui:
        only_one(ui, nav_const, 'official UI Npay path')
        ui = ui.replace(nav_const, '')
    elif 'NAVER=' in ui:
        raise ValueError('Official UI has an unknown Npay path')
    old_doc = ('The previous Npay source is used strictly for same-date comparison, never for\n'
               'filling missing official credit observations. No unverified signal weights.')
    if old_doc in ui:
        ui = ui.replace(old_doc, 'Only official KOFIA data is used for displayed cash and credit balances.')
    elif 'same-date comparison' in ui:
        raise ValueError('Official UI documentation needs manual review')
    changes[OFFICIAL_UI] = ui

    for file, content in changes.items():
        ast.parse(content, filename=str(file))
        if file == BATCH and 'collect_market_liquidity.py' in content:
            raise ValueError('Npay collector still in EOD batch')
        if file in (SUMMARY, OFFICIAL_UI) and ('네이버와 금투협 신용융자 집계가 일치하지 않습니다' in content or
                                              '네이버 동일 날짜 자료가 없어' in content or
                                              '같은 날짜 네이버 자료와 교차 비교' in content):
            raise ValueError('Npay comparison message still in user-facing UI')

    # Atomic replacement one file at a time, only after ALL validation passes.
    for file, content in changes.items():
        current = file.read_text(encoding='utf-8')
        if current == content:
            print('UNCHANGED', file.relative_to(ROOT), flush=True)
            continue
        temporary = file.with_suffix(file.suffix + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        os.replace(temporary, file)
        print('UPDATED', file.relative_to(ROOT), flush=True)

    print('PASS: KOFIA is authoritative, Npay deposit/credit not scheduled, comparison UI removed.', flush=True)
    print('NOTE: Workflow removes only Npay DEPOSIT/CREDIT JSON and manual workflow.', flush=True)
    print('NOTE: Existing Npay spot and futures pipelines remain untouched.', flush=True)


if __name__ == '__main__':
    main()
