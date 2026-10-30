"""Miner Terminal — read-only FTD/market-state audit, for app.py.

This module DOES NOT update the market-state engine. It independently replays
its *current explicit rules* on the same validated Yahoo/Naver input, showing
Day 1, failed attempts, FTD evidence and later state changes. It does not
reproduce IBD's proprietary/discretionary market classification.

Usage inside the existing '반등 확인' detail view:
    from miner_ftd_audit import show_ftd_audit
    show_ftd_audit(datasets, oneil_market_state)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

FTD_RISE = 0.01  # Match app.py ONEIL_FTD_GAIN; not a universal IBD threshold.
MIN_VALID_DAYS = 80
MAX_REPLAY_DAYS = 260

EVENT_COLUMNS = ['날짜', '사건', '시장 상태', 'Day 1', '기준 저점', '지수 등락(%)', '거래량 증감(%)', '설명']
CHECK_COLUMNS = ['날짜', '랠리 경과일', 'Day 1', '지수 등락(%)', '거래량 증감(%)', '기준 저점', '당일 저가', '4일차 이후', '1% 이상 상승', '거래량 증가', '저점 유지', '판정']


def _dd_asof(close: np.ndarray, volume: np.ndarray, i: int) -> list[int]:
    """Replicate current app.py's quantitative DD count, for transition checks."""
    return [j for j in range(max(1, i - 24), i + 1)
            if close[j] <= close[j - 1] * 0.998
            and volume[j] > volume[j - 1]
            and (j == i or not (close[j + 1:i + 1] >= close[j] * 1.05).any())]


def replay_ftd(frame: pd.DataFrame) -> dict:
    """Independently replay the currently deployed market-state decisions.

    Input audit requires *consecutive* valid index rows, not calendar dates.
    Never fabricates volume or carries previous days forward.
    """
    result = dict(status='판정 보류', day1=None, ftd=None, dd_count=None,
                  consecutive=0, reason='', events=pd.DataFrame(columns=EVENT_COLUMNS),
                  checks=pd.DataFrame(columns=CHECK_COLUMNS))
    cols = ['Close', 'Low', 'Volume']
    if frame is None or frame.empty or not set(cols).issubset(frame.columns):
        result['reason'] = '필수 지수 일봉(Close, Low, Volume)이 없습니다.'
        return result
    raw = frame.sort_index()
    valid = raw[cols].apply(pd.to_numeric, errors='coerce')
    good_row = valid.notna().all(axis=1) & valid.gt(0).all(axis=1)
    count = 0
    for ok in reversed(good_row.tolist()):
        if not ok:
            break
        count += 1
    result['consecutive'] = count
    if count < MIN_VALID_DAYS:
        result['reason'] = f'최근 연속 정상 가격·거래량 {count}일: 최소 {MIN_VALID_DAYS}일 필요'
        return result

    df = valid.tail(min(count, MAX_REPLAY_DAYS))
    n = len(df)
    dates = df.index
    close = df['Close'].to_numpy(dtype=float)
    low = df['Low'].to_numpy(dtype=float)
    volume = df['Volume'].to_numpy(dtype=float)
    ma50 = pd.Series(close).rolling(50).mean().to_numpy()

    state, day1, floor, ftd = '관찰', None, None, None
    events, checks = [], []

    def stamp(i):
        return pd.Timestamp(dates[i]).strftime('%Y-%m-%d')

    def pct(i):
        return round(100 * (close[i] / close[i - 1] - 1), 2)

    def vol_pct(i):
        return round(100 * (volume[i] / volume[i - 1] - 1), 2)

    def add_event(i, label, note):
        events.append({'날짜': stamp(i), '사건': label, '시장 상태': state,
                       'Day 1': stamp(day1) if day1 is not None else '',
                       '기준 저점': round(float(floor), 2) if floor is not None else None,
                       '지수 등락(%)': pct(i), '거래량 증감(%)': vol_pct(i), '설명': note})

    for i in range(max(50, n - MAX_REPLAY_DAYS), n):
        dd_count = len(_dd_asof(close, volume, i))
        below50_2 = close[i] < ma50[i] and close[i - 1] < ma50[i - 1]
        below50_3 = below50_2 and close[i - 2] < ma50[i - 2]

        if state == '관찰':
            if below50_2:
                state = '조정'
                add_event(i, '조정 진입', '50일선 아래 2거래일 마감 — 광부 자체 기준')
            continue

        if state == '조정':
            if close[i] > close[i - 1]:
                day1, floor, ftd = i, float(low[i]), None
                state = '랠리 시도'
                add_event(i, '랠리 Day 1', '조정 후 첫 상승 마감; 기준 저점은 Day 1 당일 저가')
            continue

        if state == '랠리 시도':
            age = i - day1 + 1
            floor_ok = bool(low[i] >= floor)
            age_ok = bool(age >= 4)
            gain_ok = bool(close[i] >= close[i - 1] * (1 + FTD_RISE))
            vol_ok = bool(volume[i] > volume[i - 1])
            found = floor_ok and age_ok and gain_ok and vol_ok
            checks.append({
                '날짜': stamp(i), '랠리 경과일': age, 'Day 1': stamp(day1),
                '지수 등락(%)': pct(i), '거래량 증감(%)': vol_pct(i),
                '기준 저점': round(float(floor), 2), '당일 저가': round(float(low[i]), 2),
                '4일차 이후': '✓' if age_ok else '—',
                '1% 이상 상승': '✓' if gain_ok else '—',
                '거래량 증가': '✓' if vol_ok else '—',
                '저점 유지': '✓' if floor_ok else '×',
                '판정': 'FTD 발생' if found else ('랠리 실패' if not floor_ok else '대기'),
            })
            if not floor_ok:
                state = '조정'
                add_event(i, '랠리 실패', f'Day 1 기준 저점 {floor:,.2f} 이탈')
                day1, floor, ftd = None, None, None
                continue
            if found:
                ftd, state = i, '상승 확인'
                add_event(i, 'FTD 발생', f'Day {age} · 지수 +{pct(i):.2f}% · 거래량 +{vol_pct(i):.2f}%')
            continue

        if state in ('상승 확인', '상승 압박'):
            # Keep the currently deployed app.py state transitions unchanged.
            if low[i] < floor and below50_2:
                state = '조정'
                add_event(i, '추세 실패', '랠리 저점 이탈 + 50일선 2일 하회 — 자체 기준')
                day1, floor, ftd = None, None, None
            elif state == '상승 압박' and below50_3 and dd_count >= 4:
                state = '조정'
                add_event(i, '조정 재진입', '50일선 3일 하회 + DD 4회 — 자체 기준')
                day1, floor, ftd = None, None, None
            elif dd_count >= 3 or below50_2:
                if state != '상승 압박':
                    state = '상승 압박'
                    add_event(i, '상승 압박', f'유효 DD {dd_count}회 또는 50일선 2일 하회')
                state = '상승 압박'
            elif close[i] > ma50[i] and dd_count <= 2:
                if state == '상승 압박':
                    state = '상승 확인'
                    add_event(i, '상승 회복', '50일선 회복·DD 감소 — 자체 기준')
                state = '상승 확인'

            # Important transparency warning: deployed engine does not invalidate
            # the post-FTD rally on a low undercut alone unless below50_2 is true.
            if floor is not None and low[i] < floor and state != '조정':
                add_event(i, '저점 이탈 주의', '랠리 저점 이탈했지만 현 엔진은 50일선 조건 미충족으로 상승 상태 유지')

    result.update({
        'status': state,
        'day1': pd.Timestamp(dates[day1]) if day1 is not None else None,
        'ftd': pd.Timestamp(dates[ftd]) if ftd is not None else None,
        'dd_count': len(_dd_asof(close, volume, n - 1)),
        'reason': '검증 가능한 연속 일봉을 동일 규칙으로 재계산함',
        'events': pd.DataFrame(events, columns=EVENT_COLUMNS),
        'checks': pd.DataFrame(checks, columns=CHECK_COLUMNS),
    })
    return result


def show_ftd_audit(datasets: dict, live_state_fn) -> None:
    """Add explainable FTD audit to the existing detail page; no engine changes."""
    st.markdown('#### 🔎 랠리 시도·FTD 날짜별 근거 검증')
    st.caption(
        '현재 광부 엔진의 상태 전이 규칙을 같은 원자료로 별도 재계산합니다. '
        '랠리 Day 1 · 기준 저점 유지 · 4일차 이후 · 지수 +1% · 거래량 증가를 확인합니다. '
        'IBD 공식 시장 판정은 아니며, 과거 FTD 이력과 현재 유효 FTD를 구분합니다.'
    )
    for name, frame in datasets.items():
        st.markdown(f'##### {name}')
        report = replay_ftd(frame)
        live = live_state_fn(frame)
        if report['status'] == '판정 보류':
            st.warning(f'{name}: {report["reason"]}')
            continue

        last_day = frame.index[-1].strftime('%Y-%m-%d')
        st.caption(f'자료 기준 {last_day} · 연속 검증 구간 {report["consecutive"]}거래일 · '
                   f'거래량 제공처 {frame.attrs.get("index_volume_source", "확인 필요")}')
        st.info(f'현재 상태: **{live["status"]}** · 현재 유효 FTD: '
                f'**{live["ftd"].strftime("%Y-%m-%d") if live.get("ftd") is not None else "없음"}**')

        if (report['status'] != live.get('status')
                or report['day1'] != live.get('day1')
                or report['ftd'] != live.get('ftd')
                or report['dd_count'] != len(live.get('dd', []))):
            st.error('시장 상태 엔진과 FTD 근거 재계산이 일치하지 않습니다. 해당 신호는 검증 전 사용하지 마세요.')
            st.write('감사 상태:', report['status'], '| 엔진 상태:', live.get('status'))
        else:
            st.success('시장 상태 · Day 1 · 현재 유효 FTD · DD 수치가 기존 엔진과 일치합니다.')

        events = report['events'].sort_values('날짜', ascending=False).reset_index(drop=True)
        checks = report['checks'].sort_values('날짜', ascending=False).reset_index(drop=True)
        with st.expander(f'📅 {name} 랠리 시작·실패·FTD·상태 변경 이력 ({len(events)}건)', expanded=True):
            if events.empty:
                st.info('재생 구간 내 사건 기록 없음')
            else:
                st.dataframe(events, hide_index=True, use_container_width=True)
                st.download_button(
                    f'📥 {name} FTD 사건 이력 CSV',
                    events.to_csv(index=False).encode('utf-8-sig'),
                    file_name=f'miner_ftd_events_{name.lower()}.csv', mime='text/csv',
                    key=f'ftd_events_download_{name}',
                )
        with st.expander(f'✅ {name} 랠리 진행 중 일별 FTD 조건표 ({len(checks)}거래일)'):
            if checks.empty:
                st.info('재생 구간에서 확인된 랠리 후보가 없습니다.')
            else:
                st.dataframe(checks, hide_index=True, use_container_width=True)
                st.download_button(
                    f'📥 {name} FTD 조건표 CSV',
                    checks.to_csv(index=False).encode('utf-8-sig'),
                    file_name=f'miner_ftd_checks_{name.lower()}.csv', mime='text/csv',
                    key=f'ftd_checks_download_{name}',
                )
        st.caption('주의: 조정 진입(50일선 2일 하회)과 FTD 이후 상승 압박·추세 실패는 광부 자체 규칙입니다. '
                   '현재 엔진의 랠리 저점은 Day 1 당일 저가이며, +1% 기준은 IBD 공개 교육자료 중 하나입니다. '
                   '주도주·시장 폭·정성적 시장 판정은 미반영입니다.')
