"""광부 터미널: DD 근거표(발생, 거래량 증가, 5% 반등 소멸, 25거래일 만료).

읽기 전용 UI. 시장 상태·DD·FTD 계산식을 변경하지 않습니다.
사용: from miner_dd_audit import show_dd_audit
      show_dd_audit(datasets, dd_days)
"""
from __future__ import annotations

import math
import pandas as pd
import streamlit as st

DD_FALL = -0.002
DD_LIFETIME = 25
DD_RECOVERY = 0.05


def calculate_dd_audit(frame: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """연속 유효 일봉으로 IBD 공개 DD 정량 기준을 독립 재계산.

    최근 lookback 거래일 내 발생 후보를 보여주되, 실제 유효 DD는
    오늘을 포함한 최근 25거래일 중 5% 종가 반등으로 소멸되지 않은 것만 센다.
    """
    columns = [
        '날짜', '지수 종가', '지수 등락률(%)', '당일 거래량', '전일 거래량',
        '거래량 증가율(%)', '경과 거래일', '5% 회복일', '판정',
    ]
    if frame is None or frame.empty or not {'Close', 'Volume'}.issubset(frame.columns):
        return pd.DataFrame(columns=columns)
    df = frame.sort_index().copy()
    close = pd.to_numeric(df['Close'], errors='coerce')
    volume = pd.to_numeric(df['Volume'], errors='coerce')
    n = len(df)
    records = []
    for i in range(max(1, n - lookback), n):
        today_close = close.iloc[i]
        prev_close = close.iloc[i - 1]
        today_vol = volume.iloc[i]
        prev_vol = volume.iloc[i - 1]
        if not all(math.isfinite(x) and x > 0 for x in
                   (today_close, prev_close, today_vol, prev_vol)):
            continue
        change = today_close / prev_close - 1
        if change > DD_FALL or today_vol <= prev_vol:
            continue
        # 처음 종가 기준 +5% 도달일 확인 (이후 최초 거래일)
        following = close.iloc[i + 1:]
        reached = following[following >= today_close * (1 + DD_RECOVERY)]
        recovery_date = reached.index[0].strftime('%Y-%m-%d') if len(reached) else ''
        age = n - i  # 당일=1, 전일=2 ... (당일 포함)
        if age > DD_LIFETIME:
            label = '25거래일 만료'
        elif recovery_date:
            label = '5% 반등 소멸'
        else:
            label = '유효 DD'
        records.append({
            '날짜': df.index[i].strftime('%Y-%m-%d'),
            '지수 종가': round(float(today_close), 2),
            '지수 등락률(%)': round(change * 100, 2),
            '당일 거래량': int(today_vol),
            '전일 거래량': int(prev_vol),
            '거래량 증가율(%)': round((today_vol / prev_vol - 1) * 100, 2),
            '경과 거래일': age,
            '5% 회복일': recovery_date,
            '판정': label,
        })
    return pd.DataFrame(records, columns=columns).sort_values(
        '날짜', ascending=False, ignore_index=True
    )


def show_dd_audit(datasets: dict, live_dd_days=None) -> None:
    """시장 신호 DD 상세 화면에 검증 가능한 날짜별 감사표 표시."""
    st.markdown('#### 🔎 DD 발생일·거래량·소멸 근거표')
    st.caption(
        '지수 -0.2% 이하 하락 및 전일보다 거래량 증가를 DD 후보로 표시. '
        '최근 25거래일에서 해당 DD 종가 대비 5% 상승한 건을 제외합니다. '
        '이 표는 현재 연결된 네이버 지수 거래량의 내부 계산 감사이며 '
        '한국거래소 원자료와 독립적으로 대조한 결과는 아닙니다.'
    )
    for name, frame in datasets.items():
        st.markdown(f'**{name} · 거래량 근거 검증**')
        recent = frame[['Close', 'Volume']].tail(25).apply(
            pd.to_numeric, errors='coerce'
        )
        valid = recent.notna().all().all() and (recent > 0).all().all()
        if not valid:
            st.warning(f'{name}: 최근 25거래일 중 결측 또는 0 거래량이 있어 DD 근거표를 확정하지 않습니다.')
            continue
        table = calculate_dd_audit(frame)
        count = int((table['판정'] == '유효 DD').sum()) if not table.empty else 0
        if live_dd_days is not None:
            expected = live_dd_days(frame)
            if expected is None:
                st.warning(f'{name}: 시장 엔진이 거래량 판정을 보류했습니다.')
            elif count != len(expected):
                st.error(
                    f'{name}: 엔진 {len(expected)}회 ≠ 근거표 {count}회. '
                    '신호를 확정하지 말고 날짜와 계산식을 점검하세요.'
                )
            else:
                st.success(f'{name}: 시장 엔진과 근거표의 유효 DD {count}회 일치')
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button(
            f'📥 {name} DD 발생·소멸 근거 CSV',
            data=table.to_csv(index=False).encode('utf-8-sig'),
            file_name=f'miner_dd_audit_{name.lower()}.csv',
            mime='text/csv',
            key=f'miner_dd_audit_export_{name}',
        )
        source = str(frame.attrs.get('index_volume_source', '출처 확인 필요'))
        match = frame.attrs.get('index_volume_matched', '미확인')
        st.caption(
            f'자료 기준일 {frame.index[-1]:%Y-%m-%d} · 거래량 출처: {source} '
            f'· 야후 종가와 매칭된 거래일: {match}개 · '
            '같은 날짜와 종가 일치만 확인한 자료입니다. '
            'KRX 독립 검증 전에는 IBD 공식 신호로 표현하지 않습니다.'
        )
