"""광부 투자터미널 계좌 방어 레이더 V10.

입력: 국내 종목명/별칭/종목코드/미국 Yahoo 티커 + 수동 비중.
실제 증권 계좌를 조회하지 않으며, 과거 데이터 기반 가상 위험 계산만 수행합니다.
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.title('🛡️ 광부 투자터미널 | 계좌 방어 레이더')
st.markdown('''<style>.block-container{max-width:1500px;padding-top:1.35rem}
[data-testid="stMetric"]{border:1px solid rgba(128,140,160,.25);background:rgba(128,140,160,.05);border-radius:12px;padding:12px}</style>''', unsafe_allow_html=True)
st.caption('실제 계좌 연동 없이 입력한 종목과 비중으로 과거 위험을 분석하는 연구 화면입니다.')

# 사용자가 자주 입력하는 종목명은 인터넷 조회가 실패하더라도 인식합니다.
KNOWN = {
    '삼성전자': '005930.KS',
    '삼성전자우': '005935.KS',
    'SK하이닉스': '000660.KS',
    '하이닉스': '000660.KS',
    '삼성전기': '009150.KS',
    '두산': '000150.KS',
    '네이버': '035420.KS',
    'NAVER': '035420.KS',
    '현대차': '005380.KS',
    '기아': '000270.KS',
    'LG에너지솔루션': '373220.KS',
    '현금': 'CASH',
    'CASH': 'CASH',
}


def _normalized(text):
    return re.sub(r'\s+', '', str(text or '')).casefold()


@st.cache_data(ttl=3600, show_spinner=False)
def stock_names():
    """원격 호출 없이 이미 수집된 TOP200 종목을 이름 사전에 추가합니다.
    거래일 미확인 데이터이므로 여기에 쓰인 것은 이름/시장/코드뿐입니다.
    """
    entries = [(name, ticker) for name, ticker in KNOWN.items()]
    data_file = Path(__file__).resolve().parents[1] / 'data' / 'kr_flow.json'
    if data_file.exists():
        try:
            obj = json.loads(data_file.read_text(encoding='utf-8'))
            for row in obj.get('top200', []):
                code = str(row.get('ticker', '')).strip()
                name = str(row.get('name', '')).strip()
                market = str(row.get('market', '')).upper()
                suffix = {'KOSPI': '.KS', 'KOSDAQ': '.KQ'}.get(market)
                if suffix and re.fullmatch(r'\d{6}', code) and name:
                    entries.append((name, code + suffix))
        except (OSError, ValueError, TypeError):
            pass  # 검색 목록 파일 손상은 기존 기본 종목 검색을 방해하지 않음
    return entries


def resolve_stock(value, universe):
    """이름/코드/해외 티커 -> Yahoo Finance 티커, 오류 메시지.
    일치하지 않는 이름은 임의 티커로 대체하지 않습니다.
    """
    raw = str(value or '').strip()
    key = _normalized(raw)
    if not key:
        return None, '종목명이 비어 있습니다.'
    if key in ('현금', 'cash'):
        return 'CASH', None
    if re.fullmatch(r'\d{6}\.(?:KS|KQ)', raw, flags=re.I):
        return raw.upper(), None
    # 입력한 6자리 코드는 목록/기본 코드에 존재하는 경우에만 시장 접미사를 보완합니다.
    if re.fullmatch(r'\d{6}', raw):
        matched = {ticker for _, ticker in universe if ticker.startswith(raw + '.')}
        if len(matched) == 1:
            return matched.pop(), None
        return None, f'{raw}: 시장이 불명확합니다. 예: {raw}.KS 또는 {raw}.KQ로 입력해 주세요.'
    exact = {ticker for name, ticker in universe if _normalized(name) == key}
    if len(exact) == 1:
        return exact.pop(), None
    if len(exact) > 1:
        return None, f'{raw}: 같은 이름의 다른 종목이 있습니다. 종목코드를 입력해 주세요.'
    partial = {(name, ticker) for name, ticker in universe if key in _normalized(name)}
    codes = {ticker for _, ticker in partial}
    if len(codes) == 1:
        return codes.pop(), None
    if partial:
        examples = ', '.join(f'{name} ({ticker})' for name, ticker in sorted(partial)[:6])
        return None, f'{raw}: 여러 후보가 있습니다. {examples}'
    # 미국 티커는 대문자 알파벳, 점, 하이픈만 안전하게 허용합니다.
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9.\-]{0,11}', raw) and not any('\uac00' <= c <= '\ud7a3' for c in raw):
st.divider()
st.caption('주의: 매일 동일 비중으로 리밸런싱한 가상 포트폴리오입니다. 실제 계좌 수익률, 매입단가, 세금, 수수료, 환율효과, 실거래 체결은 반영되지 않습니다.')
