"""One serial KR EOD pass, preserving verified legacy collectors.

No synthetic dates. ADR20 is a supplementary source: if it fails, mark its stage
FAILED but never invalidate existing spot/futures/official KOFIA snapshots.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCES=[
    ('TOP200 거래대금','collect_kr_flow.py','kr_flow.json',True),
    ('TOP200 투자자별 수급 (최대 200회 공개조회)','collect_investor_flow.py','kr_investor_flow.json',True),
    ('코스피·코스닥 시장 전체 현물','collect_market_total_flow.py','kr_market_total_flow.json',True),
    ('외국인 선물 계약·명목금액','collect_futures_flow.py','kr_futures_flow.json',True),
    ('네이버 예탁금·신용융자 (비공식 비교용)','collect_market_liquidity.py','kr_market_liquidity.json',True),
]
KOFIA=('금투협 공식 예탁금·신용융자','collect_kofia_liquidity.py','kr_kofia_liquidity.json',True)
ADR=('시장 폭 ADR20 (매동 비공식)','collect_adr_breadth.py','kr_market_adr20.json',False)

def has_official_seed():
    try:
        obj=json.loads((ROOT/'data'/'kr_kofia_liquidity.json').read_text(encoding='utf-8'))
        return (obj.get('status')=='official_source_validated' and obj.get('unit')=='KRW_million'
                and len(obj.get('history',[]))>=60)
    except (OSError,ValueError,TypeError,AttributeError):
        return False

def has_adr_seed():
    try:
        obj=json.loads((ROOT/'data'/'kr_market_adr20.json').read_text(encoding='utf-8'))
        return (obj.get('status')=='verified' and len(obj.get('history',[]))>=20)
    except (OSError,ValueError,TypeError,AttributeError):
        return False

def main():
    active=SOURCES+([KOFIA] if has_official_seed() else [])+[ADR]
    outcomes=[]
    errors=0
    print('EOD BATCH: serial verified collectors; independent intraday snapshot left unchanged.',flush=True)
    for title,script,file,required in active:
        print(f'\n=== START {title} ===',flush=True)
        if script=='collect_adr_breadth.py' and not has_adr_seed():
            # Prior TOP200 per-stock flow calls share the provider's 60/min/IP
            # budget with the daily market endpoint. Bootstrap only: let the
            # rolling window drain, without bypassing or retrying HTTP429.
            print('ADR INITIAL BOOTSTRAP: observe 65s public API rolling-window cooldown',flush=True)
            time.sleep(65)
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/script)],cwd=ROOT,
                              env=os.environ.copy(),check=False)
        path=ROOT/'data'/file
        status='OK' if result.returncode==0 and path.is_file() else 'FAILED'
        print(f'=== END {title}: {status} / process={result.returncode} / file={path.is_file()} ===',flush=True)
        outcomes.append((title,status,file))
        if required and status!='OK':errors+=1
        if script=='collect_adr_breadth.py' and status=='OK':
            result_ui=subprocess.run([sys.executable,str(ROOT/'scripts'/'activate_adr_breadth_ui.py')],
                                     cwd=ROOT,check=False)
            if result_ui.returncode!=0:
                outcomes.append(('ADR20 상세 화면 전환','FAILED','miner_breadth.py'))
                print('ADR detail UI activation failed; prior detail remains unchanged',flush=True)
            else:
                outcomes.append(('ADR20 상세 화면 전환','OK','miner_breadth.py'))
    if not has_official_seed():
        outcomes.append(('금투협 공식','SKIPPED — official seed needed','kr_kofia_liquidity.json'))
    md=['## 광부 장마감 통합수집 / 시장 폭 ADR20','| 항목 | 결과 | 파일 |','|---|---|---|']
    for title,status,file in outcomes:
        md.append(f'| {title} | {status} | `{file}` |')
    md.extend(['','ADR은 별도 비공식 시장 폭 자료. 최초 20거래일 이상 원자료 확보 후에만 게시.',
               'OK는 개별 수집기 종료 상태만 표시. 각 JSON의 기준일·검증상태를 별도로 확인하세요.',
               '금투협은 공식 공개 통계, TOP200과 현물/선물은 기존 원천. 장중 스냅샷은 그대로 유지.'])
    summary=os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as f:f.write('\n'.join(md)+'\n')
    for line in md:print(line,flush=True)
    if errors:
        print(f'FAILURE: {errors} required stages failed; successful sources may still be committed.',file=sys.stderr)
    return 1 if errors else 0

if __name__=='__main__':raise SystemExit(main())
