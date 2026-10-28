"""Best-effort KR stock flow snapshot. EOD ONLY, not intraday or live data."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parents[1] / 'data' / 'kr_flow.json'


def main():
    now = datetime.now(timezone.utc)
    output = {'collected_at_kst': now.astimezone(ZoneInfo('Asia/Seoul')).isoformat(),
              'status': 'unavailable', 'source': 'pykrx / KRX-derived public data (best effort)',
              'date': None, 'top200': [], 'market_flows': {}, 'errors': [],
              'notice': '종가 기준 확정 데이터만 제공. 장중 실시간 수급이 아닙니다. KRX 제공 정책 변경 시 실패할 수 있습니다.'}
    try:
        from pykrx import stock
        import pandas as pd
        # Avoid weekend/holiday guessing: accept only a date with enough valid stock rows.
        valid = []
        today = now.astimezone(ZoneInfo('Asia/Seoul')).date()
        for lag in range(0, 9):
            day = (today - timedelta(days=lag)).strftime('%Y%m%d')
            market_tables = []
            for market in ('KOSPI', 'KOSDAQ'):
                try:
                    frame = stock.get_market_ohlcv_by_ticker(day, market=market)
                    if frame is None or frame.empty or '거래대금' not in frame.columns:
                        continue
                    frame = frame.copy()
                    frame.index = frame.index.astype(str).str.zfill(6)
                    frame['시장'] = market
                    market_tables.append(frame)
                except Exception as exc:
                    output['errors'].append(f'{day} {market} 거래대금 조회 실패: {type(exc).__name__}: {str(exc)[:100]}')
            if market_tables:
                combined = pd.concat(market_tables)
                combined['거래대금'] = pd.to_numeric(combined['거래대금'], errors='coerce').fillna(0)
                combined = combined[combined['거래대금'] > 0]
                if len(combined) >= 200:
                    valid = [day, combined]
                    break
        if not valid:
            raise RuntimeError('유효한 KOSPI/KOSDAQ 종목별 거래대금 자료를 확보하지 못했습니다.')
        day, combined = valid
        output['date'] = f'{day[:4]}-{day[4:6]}-{day[6:]}'
        # This API's KOSPI/KOSDAQ stock universe excludes exchange-traded products.
        ranked = combined.sort_values('거래대금', ascending=False).head(200)
        flows = {}
        for market in ('KOSPI', 'KOSDAQ'):
            for investor in ('외국인', '기관합계'):
                try:
                    df = stock.get_market_net_purchases_of_equities(day, day, market, investor)
                    if df is None or df.empty or '순매수거래대금' not in df.columns:
                        continue
                    for ticker, row in df.iterrows():
                        key = str(ticker).zfill(6)
                        flows.setdefault(key, {})[investor] = int(row['순매수거래대금'])
                except Exception as exc:
                    output['errors'].append(f'{market} {investor} 종목 수급: {type(exc).__name__}: {str(exc)[:140]}')
            try:
                start = (datetime.strptime(day, '%Y%m%d') - timedelta(days=40)).strftime('%Y%m%d')
                data = stock.get_market_trading_value_by_date(start, day, market)
                if data is not None and not data.empty:
                    dates = pd.to_datetime(data.index)
                    for dt, (_, row) in zip(dates, data.iterrows()):
                        date_key = dt.strftime('%Y-%m-%d')
                        output['market_flows'].setdefault(market, []).append({
                            'date': date_key,
                            'foreign_krw': int(row.get('외국인합계', 0)),
                            'institution_krw': int(row.get('기관합계', 0)),
                            'individual_krw': int(row.get('개인', 0))})
            except Exception as exc:
                output['errors'].append(f'{market} 시장 수급: {type(exc).__name__}: {str(exc)[:140]}')
        rows = []
        for ticker, row in ranked.iterrows():
            try:
                name = stock.get_market_ticker_name(ticker)
            except Exception:
                name = ticker
            f = flows.get(ticker, {})
            rows.append({'ticker': ticker, 'name': str(name), 'market': str(row['시장']),
                         'close': int(row['종가']), 'traded_krw': int(row['거래대금']),
                         'foreign_net_krw': f.get('외국인'), 'institution_net_krw': f.get('기관합계')})
        output['top200'] = rows
        output['status'] = 'ok' if len(rows) == 200 else 'partial'
    except Exception as exc:
        output['errors'].append(f'{type(exc).__name__}: {str(exc)[:300]}')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"KR flow status={output['status']} date={output['date']} rows={len(output['top200'])} market_flow={list(output['market_flows'])}")
    for error in output['errors'][-5:]: print('WARN:', error)

if __name__ == '__main__':
    main()
