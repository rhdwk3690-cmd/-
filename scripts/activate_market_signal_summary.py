"""Fail-closed, repeatable insertion of the market integrity panel into existing app.py.
Also add a credit integrity note to market_liquidity_ui.py without altering its metrics.
"""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'app.py'
UI=ROOT/'market_liquidity_ui.py'

def patch_exact(src, find, replacement, done):
    if done in src:
        return src, False
    if src.count(find) != 1:
        raise RuntimeError(f'Expected exactly one insertion anchor, found {src.count(find)}. Original preserved.')
    return src.replace(find, replacement), True

def main():
    app=APP.read_text(encoding='utf-8')
    ui=UI.read_text(encoding='utf-8')
    app_anchor=("        st.markdown('<div class=\"miner-detail-note\">● 신호는 지수 가격·거래량으로 계산한 참고 지표입니다. "
                "시장 폭 지표는 별도 원자료를 사용합니다. 예탁금·신용잔고는 게시일 기준으로 지연될 수 있습니다.</div>', unsafe_allow_html=True)\n"
                "        return\n")
    app_insert=("        st.markdown('<div class=\"miner-detail-note\">● 신호는 지수 가격·거래량으로 계산한 참고 지표입니다. "
                "시장 폭 지표는 별도 원자료를 사용합니다. 예탁금·신용잔고는 게시일 기준으로 지연될 수 있습니다.</div>', unsafe_allow_html=True)\n"
                "        from market_signal_summary import render_market_signal_integrity\n"
                "        render_market_signal_integrity(states, datasets, oneil_market_state)\n"
                "        return\n")
    app, did_app=patch_exact(app,app_anchor,app_insert,'render_market_signal_integrity(states, datasets, oneil_market_state)')
    ui_anchor=("    st.warning('단위 주의: API 원문에는 단위 표기가 없습니다. 아래 조원 금액은 **원자료 1단위=1억원으로 해석한 참고값**이며 금융투자협회 공식 수치와 독립 대조가 아직 필요합니다. 비율·오실레이터는 동일 단위가 약분됩니다.')\n")
    ui_insert=ui_anchor + (
        "    from market_signal_integrity import audit_npay_history\n"
        "    audit = audit_npay_history(h)\n"
        "    if audit['credit_status'] == 'mismatched':\n"
        "        st.error(f\"공식 대조 불일치: {audit['baseline_date']} 신용융자 금투협 {audit['credit_official_trillion']:.5f}조 vs Npay {audit['credit_npay_trillion']:.5f}조. \"\n"
        "                 '아래 신용잔고/예탁금 비율은 비공식 원천 기준이므로 공식 위험 점수로 사용하지 않습니다.')\n"
        "    else:\n"
        "        st.warning('신용융자 공식 교차검증 최신 자료 미확인. 아래 레버리지 비율은 참고용이며 종합 신호에 합산하지 않습니다.')\n"
    )
    ui, did_ui=patch_exact(ui,ui_anchor,ui_insert,'audit = audit_npay_history(h)')
    # Validate both patched sources before any writes: preserves originals on syntax/insertion errors.
    compile(app,str(APP),'exec')
    compile(ui,str(UI),'exec')
    if did_app: APP.write_text(app,encoding='utf-8')
    if did_ui: UI.write_text(ui,encoding='utf-8')
    print('Market signal integrity panel activation OK:', 'app changed' if did_app else 'app already active',
          'liquidity UI changed' if did_ui else 'liquidity UI already active')

if __name__=='__main__':
    main()
