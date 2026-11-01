"""Fail closed: patch labels and gate market-signal summary DD/FTD on independent audit.

No changes to signal math, EOD collectors, official KOFIA, TOP200 or ADR20.
"""
from __future__ import annotations
import ast
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'app.py'
SUMMARY=ROOT/'market_signal_summary.py'
MODULE=ROOT/'market_signal_qa.py'


def narrow_replace(src,old,new,label):
    if old==new:raise ValueError('bad replacement')
    if new in src:
        if src.count(new)!=1:
            raise ValueError(f'{label}: repeated new anchor; abort')
        return src,False
    if src.count(old)!=1:
        raise ValueError(f'{label}: expected exactly one old anchor, found {src.count(old)}; abort')
    return src.replace(old,new,1),True


def apply(app=APP,summary=SUMMARY,module=MODULE):
    if not module.is_file():
        raise ValueError('market_signal_qa.py missing')
    ast.parse(module.read_text(encoding='utf-8'))
    original_app=app.read_text(encoding='utf-8')
    original_summary=summary.read_text(encoding='utf-8')
    a=original_app
    pairs=[
      ("st.caption('Distribution Day: 지수 -0.2% 이하 하락과 거래량 증가가 겹친 날 (간이 정의).')",
       "st.caption('유효 DD: 지수 -0.2% 이하 하락 + 거래량 증가. 최근 25거래일 내 발생하되 이후 종가 5% 회복 시 제외하는 자체 기준입니다.')"),
      ("st.metric(f'{name} · 최근 25거래일 간이 DD', f'{len(days)}일')",
       "st.metric(f'{name} · 유효 DD (25거래일)', f'{len(days)}회')"),
      ("st.caption('Follow-Through Day: 반등 과정에서 강한 상승과 거래량 증가를 확인하는 간이 후보.')",
       "st.caption('FTD: 조정 후 Day 1부터 4거래일째 이후 지수 1% 이상 상승과 거래량 증가를 확인하는 광부 자체 유효 신호입니다.')"),
      ("st.info(f'{name}: 최근 25거래일 간이 FTD 후보 없음')",
       "st.info(f'{name}: 현재 유효 FTD 없음 (독립감사 아래 참조)')"),
      ("st.success(f'{name}: 간이 FTD 후보 발생일 {day:%Y-%m-%d}')",
       "st.success(f'{name}: 현재 유효 FTD 발생일 {day:%Y-%m-%d} (독립감사 아래 참조)')"),
      ("return f'{date:%m/%d} 후보' if date is not None else '최근 후보 미발견'",
       "return f'{date:%m/%d} 유효' if date is not None else '유효 FTD 없음'"),
      ("**DD**: 최근 25거래일, 지수 -0.2% 이하 하락 + 거래량 증가의 단순 집계. 기관 순매도액이 아님.",
       "**DD**: 지수 -0.2% 이하 하락 + 거래량 증가 후 최근 25거래일 내 유지되고 종가 5% 반등으로 소멸하지 않은 건수. 기관 순매도액이 아님."),
    ]
    n_app=0
    for old,new in pairs:
        a,changed=narrow_replace(a,old,new,'app.py label')
        n_app+=int(changed)
    # Summary contains the current official KOFIA values and independent ADR20; preserve those.
    begin="    for name in ('KOSPI','KOSDAQ'):\n"
    end="    st.caption('DD·FTD는 가격과 지수 거래량에 기반한 자체 구현으로 IBD 공식 판정이 아닙니다.')\n"
    s=original_summary
    replacement=("    from market_signal_qa import assess_market_signal\n"
    "    for name in ('KOSPI','KOSDAQ'):\n"
    "        if name not in datasets: continue\n"
    "        audit=assess_market_signal(datasets[name],oneil_market_state)\n"
    "        if audit['status']!='verified':\n"
    "            st.warning(f'{name}: DD·FTD 검증 보류 — {audit[\"reason\"]}')\n"
    "            continue\n"
    "        ftd_text=audit['ftd'] or '현재 유효 없음'\n"
    "        st.caption(f'{name}: 검증된 유효 DD {audit[\"dd_count\"]}회 · FTD {ftd_text} · 상태 {audit[\"market_status\"]} · 거래량 연속 80일 검증')\n"
    "    st.caption('DD·FTD는 광부 자체 지수 가격·거래량 규칙. 네이버 지수 거래량은 야후 종가와 날짜 대조했으나 KRX/IBD 공식 신호가 아닙니다.')\n")
    old_prefix="    for name in ('KOSPI','KOSDAQ'):\n"
    old_begin=s.find(old_prefix)
    old_end=s.find(end)
    if old_begin<0 or old_end<=old_begin:
        if 'audit=assess_market_signal(datasets[name],oneil_market_state)' not in s:
            raise ValueError('market_signal_summary.py audit insertion anchor changed')
        n_summary=0
    else:
        before=s[old_begin:old_end+len(end)]
        # Validate this is exactly the single price-summary branch, and only its old section.
        if s.count(old_prefix)!=1 or s.count(end)!=1 or "o=oneil_market_state(datasets[name])" not in before:
            if 'audit=assess_market_signal(datasets[name],oneil_market_state)' not in s:
                raise ValueError('market_signal_summary.py block structure changed; abort')
            n_summary=0
        else:
            s=s[:old_begin]+replacement+s[old_end+len(end):]
            n_summary=1
    # Add a single collapsible evidence panel after existing evidence render.
    old_call="    st.caption('시장 추세 게이지는 기존 8개 가격 조건만 반영. ADR20·금투협 자금·DD·FTD·현물/선물 수급은 독립 근거이며 종합 점수화는 별도 백테스트 이후 검토합니다.')"
    new_call=("    from market_signal_qa import render_quality_detail\n"
              "    render_quality_detail(datasets, oneil_market_state)\n"
              + old_call)
    s,did_call=narrow_replace(s,old_call,new_call,'summary quality expander')
    n_summary+=int(did_call)
    # Verify compiled outputs before writing either file.
    ast.parse(a)
    ast.parse(s)
    writes=[]
    if a!=original_app:writes.append((app,a))
    if s!=original_summary:writes.append((summary,s))
    for dest,data in writes:
        temp=dest.with_name(dest.name+'.miner_quality.tmp')
        temp.write_text(data,encoding='utf-8')
        os.replace(temp,dest)
    print(f'Market QA activated: labels={n_app}; summary_changes={n_summary}; files={len(writes)}')
    return len(writes)


if __name__=='__main__':
    apply()
