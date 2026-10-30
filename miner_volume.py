"""광부 투자터미널 지수 거래량 검증 모듈 - Yahoo 종가+네이버 거래량 날짜별 대조.
비공식 공개 API의 이용 가능 여부는 Streamlit에서 실제 점검해야 합니다."""
import requests
import numpy as np
import pandas as pd
import streamlit as st

_MINER_INDEX_CODES = {'^KS11': 'KOSPI', '^KQ11': 'KOSDAQ'}


def _miner_num(value):
    try:
        return float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return float('nan')


def _miner_naver_rows(payload):
    """네이버 공개 JSON의 버전별 리스트 구조 대응."""
    if isinstance(payload, list):
        for item in payload:
            yield from _miner_naver_rows(item)
    elif isinstance(payload, dict):
        if (('localTradedAt' in payload or 'localDate' in payload)
                and 'accumulatedTradingVolume' in payload):
            yield payload
        else:
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    yield from _miner_naver_rows(value)


def _miner_naver_volume(ticker, yahoo_frame):
    code = _MINER_INDEX_CODES.get(ticker)
    if code is None:
        return {}, '지원하지 않는 지수'

    start = (yahoo_frame.index[-1] - pd.Timedelta(days=450)).strftime('%Y%m%d')
    end = (yahoo_frame.index[-1] + pd.Timedelta(days=1)).strftime('%Y%m%d')
    sources = [
        ('네이버 지수 일별시세',
         f'https://m.stock.naver.com/api/index/{code}/price',
         {'pageSize': 360, 'page': 1}),
        ('네이버 지수 차트',
         f'https://api.stock.naver.com/chart/domestic/index/{code}',
         {'periodType': 'dayCandle', 'startDateTime': start, 'endDateTime': end}),
        ('네이버 지수 차트 대체경로',
         f'https://m.stock.naver.com/api/securityService/chart/domestic/index/{code}',
         {'periodType': 'day'}),
    ]
    headers = {'User-Agent': 'Mozilla/5.0',
               'Referer': 'https://m.stock.naver.com/',
               'Accept': 'application/json'}
    best, best_source, errors = {}, '', []
    for source, url, params in sources:
        try:
            response = requests.get(url, params=params, headers=headers, timeout=12)
            response.raise_for_status()
            result = {}
            for item in _miner_naver_rows(response.json()):
                date_raw = item.get('localTradedAt') or item.get('localDate')
                date = pd.to_datetime(str(date_raw)[:10], errors='coerce')
                if pd.isna(date):
                    continue
                date = date.normalize()
                if date not in yahoo_frame.index:
                    continue
                volume = _miner_num(item.get('accumulatedTradingVolume'))
                close = _miner_num(item.get('closePrice'))
                yahoo_close = float(yahoo_frame.at[date, 'Close'])
                # 같은 날짜, 같은 지수 종가가 0.3% 이내로 일치할 때만 채택
                if (not np.isfinite(volume) or volume <= 0 or
                        not np.isfinite(close) or close <= 0 or
                        abs(close / yahoo_close - 1) > 0.003):
                    continue
                low = _miner_num(item.get('lowPrice'))
                result[date] = (volume, low)
            if len(result) > len(best):
                best, best_source = result, source
            if len(best) >= 240:
                break
        except (requests.RequestException, ValueError, TypeError) as exc:
            errors.append(f'{source}: {type(exc).__name__}')
    return best, (best_source or '; '.join(errors) or '일별 거래량 없음')


def install(yahoo_loader, original_state):
    """app.py의 세 함수에 검증 기능을 연결. 원래 시장 신호 화면은 유지."""
    @st.cache_data(ttl=900, show_spinner=False)
    def load_signal_data(ticker):
        # 새로고침 시 원본 Yahoo 캐시까지 실제 재조회
        yahoo_loader.clear()
        frame = yahoo_loader(ticker).copy()
        original = frame['Volume'].copy()
        # 서로 단위가 다른 Yahoo 거래량과 네이버 거래량을 섞지 않음
        frame['Volume'] = float('nan')
        matched, source = _miner_naver_volume(ticker, frame)
        for date, (volume, low) in matched.items():
            frame.at[date, 'Volume'] = volume
            if np.isfinite(low) and low > 0:
                frame.at[date, 'Low'] = low
        frame.attrs['index_volume_source'] = source
        frame.attrs['index_volume_matched'] = len(matched)
        frame.attrs['index_yahoo_volume_valid'] = int((original > 0).sum())
        return frame


    def signal_volume_ok(df):
        """판정에 필요한 최소 80일 연속 정상 거래량 검사."""
        if len(df) < 80:
            return False
        x = df[['Close', 'Low', 'Volume']].tail(80).apply(pd.to_numeric, errors='coerce')
        return bool(x.notna().all().all() and (x > 0).all().all())


    def oneil_market_state(df):
        """거래량이 끊긴 옛 구간은 제외, 최신일 결측이면 판정 보류."""
        empty = dict(status='판정 보류', day1=None, rally_days=0,
                     ftd=None, dd=[], events=[], reason='')
        if len(df) < 80:
            empty['reason'] = '지수 일봉 80거래일 미만'
            return empty
        valid = (df[['Close', 'Low', 'Volume']]
                 .apply(pd.to_numeric, errors='coerce'))
        valid = valid.notna().all(axis=1) & (valid > 0).all(axis=1)
        if not bool(valid.iloc[-1]):
            empty['reason'] = ('최신 거래일의 거래량 확인 불가 · '
                               + str(df.attrs.get('index_volume_source', '출처 미확인')))
            return empty
        good = 0
        for item in valid.iloc[::-1]:
            if not bool(item):
                break
            good += 1
        if good < 80:
            empty['reason'] = f'최근 연속 유효 거래량 {good}일 · 최소 80일 필요'
            return empty
        # 기존 50일선 및 시장 상태 계산식은 유지. 최대 260일만 사용.
        clean = df.tail(min(good, 260)).copy()
        state = original_state(clean)
        state['reason'] += f' · 검증된 거래량 {len(clean)}일'
        return state
    return load_signal_data, signal_volume_ok, oneil_market_state
