"""Npay FUT market investor flow -> daily KOSPI200 futures-like series.

This endpoint labels marketType=FUT but returns no contract ID. Treat the product
scope as provider-classified, and show the caveat in UI. The price fields appear
to be KRW million, validated with per-contract implied KOSPI200 index points;
therefore converted amount is ESTIMATED notional, NEVER cash investment.
No synthetic data, quantity/currency conflation or source bypass.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'kr_futures_flow.json'
URL = 'https://stock.naver.com/api/domestic/market/trend/daily'
SOURCE = 'Npay Stock - KRX FUT investor daily net trading'
# The FUT payload has trading prices in KRW millions; must pass independent
# per-contract value plausibility screening, otherwise no amount is emitted.
SOURCE_PRICE_UNIT_KRW = 1_000_000
KOSPI200_FUTURES_MULTIPLIER_KRW = 250_000
FOREIGN = '9000'
INDIVIDUAL = '8000'
INSTITUTION = ('6000', '5000', '4000', '3000', '2000', '1000')
OTHER = ('7100', '7000')
TOTAL = '9999'
EXPECTED = {FOREIGN, INDIVIDUAL, *INSTITUTION, *OTHER, TOTAL}
KST = ZoneInfo('Asia/Seoul')


def integer(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r'[+-]?\d+', str(value)):
        raise ValueError(f'not an integer: {str(value)[:32]}')
    return int(value)


def read_day(item, asof):
    if not isinstance(item, dict) or item.get('time') not in ('', None):
        return None  # no intraday snapshot masquerading as EOD
    raw = item.get('bizdate')
    if not isinstance(raw, str) or not re.fullmatch(r'\d{8}', raw):
        raise ValueError('invalid date')
    d = datetime.strptime(raw, '%Y%m%d').date()
    if d > asof or d.weekday() >= 5:
        return None
    net = item.get('netAmounts')
    if not isinstance(net, list) or not net:
        raise ValueError('missing netAmounts')
    info = {}
    for x in net:
        if not isinstance(x, dict):
            raise ValueError('unexpected netAmount member')
        code = str(x.get('investorGubun', ''))
        if code in info:
            raise ValueError(f'duplicate investor: {code}')
        if code not in EXPECTED:
            raise ValueError(f'unknown investor category: {code}')
        buy_q = integer(x.get('buyQuant'))
        sell_q = integer(x.get('sellQuant'))
        buy_price = integer(x.get('buyPrice'))
        sell_price = integer(x.get('sellPrice'))
        diff = integer(x.get('diffValue'))
        if min(buy_q, sell_q, buy_price, sell_price) < 0 or diff != buy_q - sell_q:
            raise ValueError(f'quantity mismatch {code}')
        info[code] = {'contracts': diff, 'buy_q': buy_q, 'sell_q': sell_q,
                      'buy_price': buy_price, 'sell_price': sell_price}
    if set(info) != EXPECTED:
        raise ValueError(f'missing/extra investor codes: {sorted(EXPECTED - set(info))}')

    if info[TOTAL]['contracts'] != 0 or info[TOTAL]['buy_q'] != info[TOTAL]['sell_q']:
        raise ValueError('total market futures contracts do not balance')
    if sum(info[k]['contracts'] for k in EXPECTED if k != TOTAL) != 0:
        raise ValueError('investor net contracts do not balance')

    # The Npay trade price unit is not explicitly stated in the payload.
    # Infer a KOSPI200 futures-price sanity range from mean turnover per contract,
    # 1 price unit=KRW 1m, and exchange multiplier KRW 250,000 per point.
    # Fail closed if underlying product or source format has changed.
    qty = info[TOTAL]['buy_q'] + info[TOTAL]['sell_q']
    traded = info[TOTAL]['buy_price'] + info[TOTAL]['sell_price']
    if qty <= 0 or traded <= 0:
        raise ValueError('zero futures market turnover')
    implied_points = traded * SOURCE_PRICE_UNIT_KRW / qty / KOSPI200_FUTURES_MULTIPLIER_KRW
    if not 100 <= implied_points <= 3000:
        raise ValueError(f'FUT product/price-unit ambiguous, implied points={implied_points:.2f}')

    def group(codes):
        return sum(info[k]['contracts'] for k in codes)
    def nominal(codes):
        return sum(info[k]['buy_price'] - info[k]['sell_price'] for k in codes) * SOURCE_PRICE_UNIT_KRW
    result = {
        'date': d.isoformat(),
        'foreign_net_contracts': group((FOREIGN,)),
        'institution_net_contracts': group(INSTITUTION),
        'individual_net_contracts': group((INDIVIDUAL,)),
        'other_net_contracts': group(OTHER),
        'foreign_net_notional_krw': nominal((FOREIGN,)),
        'institution_net_notional_krw': nominal(INSTITUTION),
        'individual_net_notional_krw': nominal((INDIVIDUAL,)),
        'estimated_reference_points': round(implied_points, 3),
    }
    return result


def parse_payload(obj, asof):
    if not isinstance(obj, dict) or not isinstance(obj.get('content'), list):
        raise ValueError('missing API content')
    out = {}
    for row in obj['content']:
        parsed = read_day(row, asof)
        if parsed:
            d = parsed['date']
            if d in out:
                raise ValueError(f'duplicate trade date: {d}')
            out[d] = parsed
    if not out:
        raise ValueError('API returned no completed dated data')
    return out


def fetch(asof, opener=urlopen):
    args = {'tradeType': 'KRX', 'marketType': 'FUT', 'bizdate': asof.strftime('%Y%m%d'),
            'startIdx': 0, 'pageSize': 45}
    req = Request(URL + '?' + urlencode(args), headers={
        'User-Agent': 'Mozilla/5.0 (MinerDashboard/1.0; research)',
        'Accept': 'application/json',
        'Referer': 'https://stock.naver.com/'})
    try:
        with opener(req, timeout=20) as r:
            if r.status != 200 or 'json' not in r.headers.get('Content-Type', '').lower():
                raise ValueError('unexpected HTTP status/content type')
            raw = r.read(250_000)
            if len(raw) >= 250_000:
                raise ValueError('unexpectedly large response')
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f'Npay FUT API unavailable ({type(exc).__name__})') from exc
    return parse_payload(json.loads(raw), asof)


def assemble(current, previous, asof):
    if not current:
        raise ValueError('no futures records')
    latest = max(current)
    if (asof - date.fromisoformat(latest)).days > 7:
        raise ValueError(f'FUT data stale: {latest}')
    historical = {}
    if isinstance(previous, dict) and previous.get('source') == SOURCE:
        for row in previous.get('history', []):
            try:
                d = date.fromisoformat(row['date'])
                if d <= asof and all(isinstance(row[k], int) and not isinstance(row[k], bool) for k in
                      ('foreign_net_contracts', 'institution_net_contracts', 'individual_net_contracts',
                       'foreign_net_notional_krw', 'institution_net_notional_krw', 'individual_net_notional_krw')):
                    historical[row['date']] = row
            except (KeyError, ValueError, TypeError):
                pass
    historical.update(current)
    hist = [historical[d] for d in sorted(historical)[-260:]]
    return {
        'status': 'verified', 'source': SOURCE, 'source_url': URL,
        'product_scope': 'Npay FUT category; KOSPI200 futures per Npay public market labeling, product ID absent from daily payload',
        'unit': 'contracts', 'nominal_unit': 'KRW', 'nominal_quality': 'estimated_from_Npay_trade_prices_million_krw',
        'nominal_is_cash_flow': False, 'contract_multiplier_krw_per_point': KOSPI200_FUTURES_MULTIPLIER_KRW,
        'latest_date': hist[-1]['date'], 'observations': len(hist),
        'collected_at_kst': datetime.now(timezone.utc).astimezone(KST).isoformat(),
        'history': hist,
        'note': 'Net traded futures notional, NOT cash investment. Derivatives might be hedges. Price-unit inferred from KRW-million trading value and futures multiplier with plausibility screen.'
    }


def run(dest=DEST, *, asof=None, fetcher=fetch):
    asof = asof or datetime.now(timezone.utc).astimezone(KST).date()
    old = None
    try:
        old = json.loads(dest.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        pass
    data = assemble(fetcher(asof), old, asof)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, dest)
    row = data['history'][-1]
    print(f"FUT data VERIFIED date={row['date']}, {len(data['history'])} days; "
          f"foreign={row['foreign_net_contracts']:+d} contracts, "
          f"estimated_notional={row['foreign_net_notional_krw']/1e8:+,.1f} 100M KRW")
    return data


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'Futures data collection FAILED: {exc}', file=sys.stderr)
        sys.exit(1)
