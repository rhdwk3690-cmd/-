"""Idempotent narrow patch for existing market_signal > 증시 자금 branch.

Refuse unknown app.py rather than replacing a user-customized app.
"""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
app=ROOT/'app.py'
text=app.read_text(encoding='utf-8')
old=("    elif view == '증시 자금':\n"
     "        st.info('투자자예탁금, 신용잔고, 신용잔고/예탁금, 신용 오실레이터는 공급처 원자료 확인 후 연결합니다.')\n"
     "        st.caption('현재 유효한 시계열이 없어 임의의 숫자나 점수를 표시하지 않습니다.')\n")
new=("    elif view == '증시 자금':\n"
     "        from market_liquidity_ui import render_market_liquidity\n"
     "        render_market_liquidity()\n")
if new in text:
    print('Market liquidity UI already enabled; no patch needed.')
    sys.exit(0)
if text.count(old)!=1:
    raise SystemExit('Refusing to change app.py: expected exact market liquidity placeholder not found once. Preserve current app.py and edit manually.')
text=text.replace(old,new)
old_title="'예탁금 · 신용잔고 · 오실레이터  |  원자료 연동 대기'"
new_title="'예탁금 · 신용잔고 · 5/20일 오실레이터  |  일별 게시 자료'"
if old_title in text:
    text=text.replace(old_title,new_title,1)
old_note='전 종목 ADR, 신용잔고·예탁금은 아직 연결되지 않아 표시하지 않습니다.'
new_note='시장 폭 지표는 별도 원자료를 사용합니다. 예탁금·신용잔고는 게시일 기준으로 지연될 수 있습니다.'
if old_note in text:
    text=text.replace(old_note,new_note,1)
compile(text,str(app),'exec')
app.write_text(text,encoding='utf-8')
print('Patched market_signal > 증시 자금 branch safely. Existing pages preserved.')
