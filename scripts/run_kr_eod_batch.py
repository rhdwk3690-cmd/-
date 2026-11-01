"""One serial EOD pass over existing audited data collectors.

Runs each source once; no fake data; each collector validates its own source.
Official KOFIA joins the daily batch only *after* a separately validated first snapshot.
Sends a truthful per-source outcome to Actions step summary.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCES=[
    ('TOP200 거래대금', 'collect_kr_flow.py', 'kr_flow.json', True),
    ('TOP200 투자자별 수급 (최대 200회 공개조회)', 'collect_investor_flow.py', 'kr_investor_flow.json', True),
    ('코스피·코스닥 시장 전체 현물', 'collect_market_total_flow.py', 'kr_market_total_flow.json', True),
    ('외국인 선물 계약·명목금액', 'collect_futures_flow.py', 'kr_futures_flow.json', True),
    ('네이버 예탁금·신용융자 (비공식 비교용)', 'collect_market_liquidity.py', 'kr_market_liquidity.json', True),
]
KOFIA=('금투협 공식 예탁금·신용융자','collect_kofia_liquidity.py','kr_kofia_liquidity.json',True)

def has_official_seed():
    try:
        obj=json.loads((ROOT/'data'/'kr_kofia_liquidity.json').read_text(encoding='utf-8'))
        return (obj.get('status')=='official_source_validated' and
                obj.get('unit')=='KRW_million' and len(obj.get('history',[]))>=60)
    except (OSError,ValueError,TypeError,AttributeError):
        return False

def main():
    active=SOURCES + ([KOFIA] if has_official_seed() else [])
    outcomes=[]
    errors=0
    print('EOD BATCH: sequential collectors; market snapshot (intraday) stays separate.',flush=True)
    for title,script,file,required in active:
        print(f'\n=== START {title} ===',flush=True)
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/script)],cwd=ROOT,env=os.environ.copy(),check=False)
        path=ROOT/'data'/file
        file_exists=path.is_file()
        status='OK' if result.returncode==0 and file_exists else 'FAILED'
        print(f'=== END {title}: {status} / process={result.returncode} / file={file_exists} ===',flush=True)
        outcomes.append((title,status,script,file))
        if required and status!='OK':errors+=1
    if not has_official_seed():
        outcomes.append(('금투협 공식', 'SKIPPED — initial manual verification required','collect_kofia_liquidity.py','kr_kofia_liquidity.json'))
    md=['## 광부 장마감 통합수집','| 항목 | 결과 | 파일 |','|---|---|---|']
    for title,status,_,file in outcomes:
        md.append(f'| {title} | {status} | `{file}` |')
    md.extend(['','`OK`는 개별 수집기 종료 코드와 파일 존재만 의미하며, 실제 자료일·종목 수는 수집된 JSON의 메타데이터로 확인해야 합니다.',
      '장중 market snapshot은 별도 30분 간격 스케줄 유지. 금투협은 최초 수동 검증 전 미가동.'])
    summary=os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as f:f.write('\n'.join(md)+'\n')
    for line in md:print(line,flush=True)
    if errors:
        print(f'FAILURE: {errors} required stages failed, but independent successful files may still be committed.',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
