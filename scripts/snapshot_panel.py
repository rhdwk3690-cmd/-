"""Use this fragment in the integrated Streamlit market overview."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st

SNAPSHOT=Path(__file__).resolve().parents[1]/'data'/'market_snapshot.json'

def show_cloud_snapshot():
    st.subheader('클라우드 수집 현황 · 종가 스냅샷')
    if not SNAPSHOT.exists():
        st.info('스냅샷이 아직 없습니다. GitHub Actions에서 Collect market snapshot을 수동 실행해 주세요.')
        return
    try:
        obj=json.loads(SNAPSHOT.read_text(encoding='utf-8'))
        collected=pd.Timestamp(obj['collected_at_kst'])
        now=pd.Timestamp.now(tz='Asia/Seoul')
        age=(now-collected).total_seconds()/60
        if age>90: st.warning(f'수집 자체가 {age:.0f}분 전입니다. GitHub Actions 작업 로그를 확인하세요.')
        else: st.caption(f'마지막 클라우드 수집: {collected:%Y-%m-%d %H:%M} KST ({age:.0f}분 전)')
        rows=[]
        for name,v in obj.get('markets',{}).items():
            if v.get('status')=='daily_close':
                rows.append({'시장':name,'종가':v['price'],'등락률(%)':v['change_pct'],'시세 기준일':v['price_date'],'출처':v['source']})
            else: rows.append({'시장':name,'종가':None,'등락률(%)':None,'시세 기준일':'수집 실패','출처':v.get('error','')})
        if rows: st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        st.warning('이 화면은 실시간이 아닙니다. 「수집 시각」과 「시세 기준일」은 서로 다르며, 전일 데이터라면 그대로 전일이라고 표시합니다.')
    except Exception as ex:
        st.error(f'스냅샷 파일 오류: {ex}')
