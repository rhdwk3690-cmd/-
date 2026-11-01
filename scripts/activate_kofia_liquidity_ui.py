"""Switch only the market-signal liquidity view to KOFIA, after verified data exists."""
from __future__ import annotations
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'app.py'
DATA=ROOT/'data'/'kr_kofia_liquidity.json'
OLD="    elif view == '증시 자금':\n        from market_liquidity_ui import render_market_liquidity\n        render_market_liquidity()\n"
NEW="    elif view == '증시 자금':\n        from kofia_liquidity_ui import render_kofia_liquidity\n        render_kofia_liquidity()\n"

def activate(app=APP,data=DATA):
    obj=json.loads(data.read_text(encoding='utf-8'))
    if obj.get('status')!='official_source_validated' or len(obj.get('history',[]))<60:
        raise ValueError('KOFIA official history not validated — UI activation aborted')
    src=app.read_text(encoding='utf-8')
    if NEW in src and OLD not in src:
        print('Official KOFIA UI already active; app.py unchanged')
        return False
    if src.count(OLD)!=1:
        raise ValueError('app.py market-signal insertion anchor changed; abort without edits')
    updated=src.replace(OLD,NEW,1)
    ast.parse(updated)
    app.write_text(updated,encoding='utf-8')
    print('Activated official KOFIA money/credit panel; other market signal features preserved')
    return True

if __name__=='__main__':
    activate()
