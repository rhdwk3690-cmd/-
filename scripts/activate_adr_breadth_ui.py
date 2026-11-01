"""Idempotently remove per-page ~30 external ADR fetches from market breadth detail.

Exact anchors; abort without changing original when any unexpected source version.
"""
from __future__ import annotations
import ast
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'miner_breadth.py'
ADR=ROOT/'data/kr_market_adr20.json'
START="    st.markdown('##### 전체시장 ADR20 (20거래일 상승 종목 합계 ÷ 하락 종목 합계 × 100)')\n"
END='    from miner_ma_breadth import show_ma_breadth\n'
NEW="    from market_signal_adr_ui import show_adr_history\n    show_adr_history(compact=False)\n"
def activate(target=TARGET,adr=ADR):
    obj=json.loads(adr.read_text(encoding='utf-8'))
    if obj.get('status')!='verified' or len(obj.get('history',[]))<20:
        raise ValueError('ADR20 saved source not validated')
    src=target.read_text(encoding='utf-8')
    if src.count(NEW)==1:
        print('ADR saved detail already enabled')
        return False
    if src.count(START)!=1 or src.count(END)!=1:
        raise ValueError('Existing miner_breadth.py UI anchors changed; original preserved')
    i=src.index(START);j=src.index(END,i)
    next_src=src[:i]+NEW+src[j:]
    ast.parse(next_src)
    target.write_text(next_src,encoding='utf-8')
    print('Switched market breadth detail to cached ADR20 JSON; original chart/breadth preserved')
    return True
if __name__=='__main__':activate()
