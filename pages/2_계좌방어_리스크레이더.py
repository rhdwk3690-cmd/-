"""광부 투자터미널 | 계좌 방어 레이더 V8 — 종목명/코드 입력 지원."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.title('🛡️ 광부 투자터미널 | 계좌 방어 레이더')
st.markdown('''<style>.block-container{max-width:1500px;padding-top:1.35rem}[data-testid="stMetric"]{border:1px solid rgba(128,140,160,.25);background:rgba(128,140,160,.05);border-radius:12px;padding:12px}</style>''', unsafe_allow_html=True)
st.caption('실제 계좌 연동 없는 비중 기반 가상 위험 분석 · 한국 종목명/종목코드와 미국 티커 입력 가능')

# 자주 사용하는 종목은 온라인 목록 장애 시에도 이름으로 입력할 수 있게 제공합니다.
COMMON = {
    '삼성전자':'005930.KS', '삼성전자우':'005935.KS', 'SK하이닉스':'000660.KS',
    '하이닉스':'000660.KS', '삼성전기':'009150.KS', '두산':'000150.KS',
    '현대차':'005380.KS', '기아':'000270.KS', 'NAVER':'035420.KS',
    '네이버':'035420.KS', '카카오':'035720.KS', 'LG에너지솔루션':'373220.KS',
    '셀트리온':'068270.KS', '한화에어로스페이스':'012450.KS',
}

def norm(s):
    return re.sub(r'\s+', '', str(s)).casefold()

@st.cache_data(ttl=86400, show_spinner=False)
def stock_universe():
    """Returns name -> candidate (name,ticker) mapping. No guessing when ambiguous."""
    entries = [(k, v) for k, v in COMMON.items()]
    snapshot = Path(__file__).resolve().parents[1] / 'data' / 'kr_flow.json'
    if snapshot.exists():
        try:
            data = json.loads(snapshot.read_text(encoding='utf-8'))
            for rec in data.get('top200', []):
                code = str(rec.get('ticker', '')).zfill(6)
                name = str(rec.get('name', '')).strip()
                mkt = str(rec.get('market', '')).upper()
                if name and len(code) == 6 and code.isdigit() and mkt in ('KOSPI', 'KOSDAQ'):
                    entries.append((name, code + ('.KS' if mkt == 'KOSPI' else '.KQ')))
        except (OSError, ValueError, TypeError):
            pass
    # 전체 상장 종목 목록은 가능할 때 보강. 실패해도 기본/저장 종목 검색은 작동.
    try:
        import FinanceDataReader as fdr
        listing = fdr.StockListing('KRX')
        if listing is not None and {'Code', 'Name'}.issubset(listing.columns):
            for _, row in listing.iterrows():
                code, name = str(row['Code']).strip().zfill(6), str(row['Name']).strip()
                mkt = str(row.get('Market', '')).upper()
                if len(code) == 6 and code.isdigit() and name and mkt in ('KOSPI','KOSDAQ'):
                    entries.append((name, code + ('.KS' if mkt == 'KOSPI' else '.KQ')))
    except Exception:
        pass
    dedup = {}
    for name, ticker in entries:
        dedup[(norm(name), ticker)] = (name, ticker)
    return list(dedup.values())

def resolve(raw, universe):
    query = str(raw).strip()
    if not query or query.lower() == 'nan':
        return None, '종목명을 입력하세요.'
    if norm(query) == 'cash' or query == '현금':
        return 'CASH', None
    if re.fullmatch(r'\d{6}(?:\.(?:KS|KQ))?', query, re.I):
        q = query.upper()
        if '.' in q:
            return q, None
        # 상장 시장을 목록으로 판단하며, 모르겠으면 유가증권 .KS로 단정하지 않는다.
        hits = sorted({ticker for _, ticker in universe if ticker.startswith(q + '.')})
        if len(hits) == 1:
            return hits[0], None
        return None, f'{query}: 시장 구분이 필요합니다. {query}.KS 또는 {query}.KQ로 입력해 주세요.'
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9.\-^=]{0,19}', query):
        # 한글 이름과 혼동되지 않는 영문 티커 허용 (예: NVDA, AAPL).
        # 한국 종목의 영문명과 정확히 일치하는 경우 종목을 우선합니다.
        hits = sorted({ticker for name, ticker in universe if norm(name) == norm(query)})
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, f'{query}: 동일 명칭의 종목이 여러 개입니다. 종목코드를 입력해 주세요.'
        return query.upper(), None
    hits = sorted({ticker for name, ticker in universe if norm(name) == norm(query)})
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, f'{query}: 같은 이름의 종목이 여러 개입니다. 종목코드를 입력해 주세요.'
    partial = [(name,ticker) for name,ticker in universe if norm(query) in norm(name)]
    options = ', '.join(f'{name}({ticker})' for name,ticker in partial[:6])
    if partial:
        return None, f'{query}: 정확한 종목명을 입력해 주세요. 후보: {options}'
    return None, f'{query}: 종목을 찾을 수 없습니다. 정확한 종목명 또는 6자리 코드+시장 접미사를 입력해 주세요.'

DEFAULT = pd.DataFrame([
