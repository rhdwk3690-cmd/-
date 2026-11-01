"""Gate DD/FTD summary cards and detail views on the existing independent QA.

Changes only app.py's market_signal() presentation. No changes to the market
engine, Yahoo/Naver index source, KOFIA, ADR, TOP200, or scheduled collectors.
A missing/changed anchor aborts before any file is written.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app.py'
QA = ROOT / 'market_signal_qa.py'
MARKER = 'quality_reports = {}  # miner independent QA gate'


def apply(app: Path=APP, qa: Path=QA):
    if not qa.is_file():
        raise RuntimeError('market_signal_qa.py missing: install QA package first')
    ast.parse(qa.read_text(encoding='utf-8'))
    original = app.read_text(encoding='utf-8')
    if MARKER in original:
        # Idempotence; never patch an already-patched app further.
        ast.parse(original)
        if original.count(MARKER)!=1:
            raise RuntimeError('duplicate QA gate anchor')
        print('DD/FTD market-wide QA gate already installed; no changes')
        return False
    text = original
    patches = [
        (
"""    for name, msg in errors.items():
        st.warning(f'{name}: 조회 실패 — {msg}')

    if view == '종합':
""",
"""    for name, msg in errors.items():
        st.warning(f'{name}: 조회 실패 — {msg}')

    # Gate every user-facing DD/FTD signal on the same independent audit.
    from market_signal_qa import assess_market_signal
    quality_reports = {}  # miner independent QA gate
    for name, frame in datasets.items():
        try:
            quality_reports[name] = assess_market_signal(frame, oneil_market_state)
        except Exception as exc:
            quality_reports[name] = {'status': 'withheld', 'reason': f'독립검산 오류 ({type(exc).__name__})'}

    if view == '종합':
"""),
        (
"""                # 기존 지수 카드 안에 오닐식 시장 상태 통합
                o = oneil_market_state(datasets[name])
                o_status = escape(str(o['status']))

                if o['status'] == '판정 보류':
                    o_detail = '거래량 검증 필요 · DD/FTD 판정 보류'
                else:
                    ftd_date = (
                        o['ftd'].strftime('%m/%d')
                        if o['ftd'] is not None else '없음'
                    )
                    o_detail = (
                        f'유효 DD {len(o["dd"])}일 · '
                        f'FTD {ftd_date}'
                    )
""",
"""                # Same independent QA as the evidence panel; never show raw unverified DD/FTD.
                o = quality_reports.get(name, {})
                if o.get('status') != 'verified':
                    o_status = '판정 보류'
                    o_detail = 'DD·FTD 독립검산 보류: ' + str(o.get('reason', '자료 부족'))[:85]
                else:
                    o_status = escape(str(o['market_status']))
                    ftd_date = o['ftd'][5:].replace('-', '/') if o['ftd'] else '없음'
                    o_detail = f'검증된 유효 DD {o["dd_count"]}회 · FTD {ftd_date}'
"""),
        (
"""        def dd_summary(name):
            if name not in datasets:
                return '조회 대기'
            days = dd_days(datasets[name])
            return f'{len(days)}일' if days is not None else '거래량 자료 부족'

        def ftd_summary(name):
            if name not in datasets:
                return '조회 대기'
            if not signal_volume_ok(datasets[name]):
                return '거래량 자료 부족'
            date = ftd_candidate(datasets[name])
            return f'{date:%m/%d} 유효' if date is not None else '유효 FTD 없음'
""",
"""        def dd_summary(name):
            q = quality_reports.get(name)
            if q is None or q.get('status') != 'verified':
                return '독립검증 보류'
            return f'{q["dd_count"]}회'

        def ftd_summary(name):
            q = quality_reports.get(name)
            if q is None or q.get('status') != 'verified':
                return '독립검증 보류'
            return f'{q["ftd"][5:].replace("-", "/")} 유효' if q['ftd'] else '유효 FTD 없음'
"""),
        (
"""    elif view == '매도 압력':
        st.caption('유효 DD: 지수 -0.2% 이하 하락 + 거래량 증가. 최근 25거래일 내 발생하되 이후 종가 5% 회복 시 제외하는 자체 기준입니다.')
        for name, df in datasets.items():
            days = dd_days(df)
            if days is None:
                st.warning(f'{name}: 거래량 누락으로 판정 보류')
            else:
                st.metric(f'{name} · 유효 DD (25거래일)', f'{len(days)}회')
                st.write('발생일: ' + (', '.join(d.strftime('%Y-%m-%d') for d in days) if days else '없음'))
        st.info('지수 거래량 기반 간이 지표이며 실제 기관 순매도 금액이나 공식 IBD Distribution Day 계산과 다릅니다.')

        from miner_dd_audit import show_dd_audit
        show_dd_audit(datasets, dd_days)
""",
"""    elif view == '매도 압력':
        st.caption('유효 DD: 지수 -0.2% 이하 하락 + 거래량 증가. 최근 25거래일 내 발생하되 이후 종가 5% 회복 시 제외하는 자체 기준입니다.')
        verified_datasets = {}
        for name, df in datasets.items():
            q = quality_reports.get(name, {})
            if q.get('status') != 'verified':
                st.warning(f'{name}: DD 확정 보류 — {q.get("reason", "자료 부족")}')
                continue
            verified_datasets[name] = df
            dates = q['dd_dates']
            st.metric(f'{name} · 검증된 유효 DD (25거래일)', f'{q["dd_count"]}회')
            st.write('발생일: ' + (', '.join(dates) if dates else '없음'))
        st.info('자체 지수 가격·거래량 규칙을 독립 검산한 결과입니다. 공식 IBD DD 및 기관 순매도 금액과 다릅니다.')

        from miner_dd_audit import show_dd_audit
        if verified_datasets:
            show_dd_audit(verified_datasets, dd_days)
        else:
            st.caption('독립검산에 통과한 지수만 발생·소멸 근거표를 표시합니다.')
"""),
        (
"""    elif view == '반등 확인':
        st.caption('FTD: 조정 후 Day 1부터 4거래일째 이후 지수 1% 이상 상승과 거래량 증가를 확인하는 광부 자체 유효 신호입니다.')
        for name, df in datasets.items():
            if not signal_volume_ok(df):
                st.warning(f'{name}: 거래량 누락으로 판정 보류')
            else:
                day = ftd_candidate(df)
                if day is None:
                    st.info(f'{name}: 현재 유효 FTD 없음 (독립감사 아래 참조)')
                else:
                    st.success(f'{name}: 현재 유효 FTD 발생일 {day:%Y-%m-%d} (독립감사 아래 참조)')
        st.info('공식 William O’Neil / IBD 신호가 아니며 추세 반전이나 투자 수익을 보장하지 않습니다.')

        from miner_ftd_audit import show_ftd_audit
        show_ftd_audit(datasets, oneil_market_state)
""",
"""    elif view == '반등 확인':
        st.caption('FTD: 조정 후 Day 1부터 4거래일째 이후 지수 1% 이상 상승과 거래량 증가를 확인하는 광부 자체 유효 신호입니다.')
        verified_datasets = {}
        for name, df in datasets.items():
            q = quality_reports.get(name, {})
            if q.get('status') != 'verified':
                st.warning(f'{name}: FTD 확정 보류 — {q.get("reason", "자료 부족")}')
                continue
            verified_datasets[name] = df
            if q['ftd'] is None:
                st.info(f'{name}: 현재 유효 FTD 없음 (독립검산 완료)')
            else:
                st.success(f'{name}: 검증된 현재 유효 FTD 발생일 {q["ftd"]}')
        st.info('공식 William O’Neil / IBD 신호가 아니며 추세 반전이나 투자 수익을 보장하지 않습니다.')

        from miner_ftd_audit import show_ftd_audit
        if verified_datasets:
            show_ftd_audit(verified_datasets, oneil_market_state)
        else:
            st.caption('독립검산에 통과한 지수만 FTD 근거표를 표시합니다.')
"""),
    ]
    for idx, (old, new) in enumerate(patches, 1):
        if text.count(old) != 1:
            raise RuntimeError(f'app.py changed: patch {idx} anchor count {text.count(old)}; original preserved')
        text = text.replace(old,new,1)
    # Also verify the central, official KOFIA/ADR panel and existing market navigation survived.
    required=['from kofia_liquidity_ui import render_kofia_liquidity',
              'render_market_signal_integrity(states, datasets, oneil_market_state)',
              'from miner_breadth import show_market_breadth',
              'from miner_volume import install as install_market_volume']
    if not all(p in text for p in required):
        raise RuntimeError('required existing dashboard feature missing: abort')
    ast.parse(text)
    temp=app.with_name('app.py.miner_qa_gate.tmp')
    temp.write_text(text,encoding='utf-8')
    os.replace(temp,app)
    print('DD/FTD guarded in hero cards, summary card, and detail views; other features unchanged')
    return True

if __name__ == '__main__':
    apply()
