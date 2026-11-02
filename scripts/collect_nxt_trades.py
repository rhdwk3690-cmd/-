"""광부 투자터미널: NXT 정규시장 + 종가매매 일별 거래대금 수집(분리 저장).

NXT 공식 사이트의 공개 조회 화면이 사용하는 비공식 HTTP 경로 기반.
이 파일은 투자자별 수급을 수집하거나 KRX 거래대금을 덮어쓰지 않는다.
대량·바스켓은 별도 시장이므로 이 결과에 포함되지 않는다.
20:05 이후 일별 확정 스냅샷만 저장하며 실패시 기존 JSON을 보존한다.
"""
import argparse
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'nxt_trades_eod.json'
KST = ZoneInfo('Asia/Seoul')
BASE = 'https://nextrade.co.kr'
ENDPOINTS = {
    'regular': ('brdinfoTime/brdinfoTimeList.do', 'brdinfoTimeList', '/menu/transactionStatusMain/menuList.do'),
    'closing': ('brdinfoEnd/brdinfoEndList.do', 'brdinfoEndList', '/menu/transactionStatusClosing/menuList.do'),
}
MARKETS = {'STK': 'KOSPI', 'KSQ': 'KOSDAQ'}


def as_nonnegative_int(value, field):
    if isinstance(value, bool) or value is None:
        raise ValueError(f'{field}: invalid amount')
    raw = str(value).strip().replace(',', '')
    if re.fullmatch(r'\d+', raw) is None:
        raise ValueError(f'{field}: invalid integer {raw!r}')
    return int(raw)


def fetch_segment(session, segment, day):
    path, list_key, referer = ENDPOINTS[segment]
    params = {
        '_search': 'false', 'pageUnit': '10000', 'pageIndex': '1',
        'sidx': '', 'sord': 'asc', 'scAggDd': day.strftime('%Y%m%d'),
        'scMktId': '', 'searchKeyword': ''
    }
    resp = session.post(BASE + '/' + path, data=params, timeout=30, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; MinerTerminal/1.0)',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Origin': BASE, 'Referer': BASE + referer,
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    })
    resp.raise_for_status()
    # NXT may respond with text/html but the response body is JSON.
    payload = resp.json()
    if not isinstance(payload, dict) or not isinstance(payload.get(list_key), list):
        raise ValueError(f'{segment}: unexpected payload')
    source_rows = payload[list_key]
    expected = as_nonnegative_int(payload.get('records'), f'{segment}.records')
    if len(source_rows) != expected:
        raise ValueError(f'{segment}: incomplete result {len(source_rows)}/{expected}')
    if segment == 'regular':
        set_time = str(payload.get('setTime') or '')
        match = re.fullmatch(r'(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})', set_time)
        if not match or match.group(1) != day.isoformat() or (int(match.group(2)), int(match.group(3))) < (20, 5):
            raise ValueError(f'not final NXT EOD snapshot: {set_time!r}')
        if not 200 <= expected <= 4000:
            raise ValueError(f'unexpected regular market coverage: {expected}')
    elif expected > 4000:
        raise ValueError('unexpected closing auction coverage')

    result = {}
    for row in source_rows:
        if not isinstance(row, dict) or str(row.get('aggDd')) != day.strftime('%Y%m%d'):
            raise ValueError(f'{segment}: missing/mismatched trading date')
        code = str(row.get('isuSrdCd') or '')
        market = MARKETS.get(str(row.get('mktId')))
       if re.fullmatch(r'A[0-9A-Z]{6}', code) is None or market is None:
            raise ValueError(f'{segment}: invalid ticker or market {code!r}')
        code = code[1:]
        if code in result:
            raise ValueError(f'{segment}: duplicate ticker {code}')
        qty = as_nonnegative_int(row.get('accTdQty'), f'{code}.accTdQty')
        amount = as_nonnegative_int(row.get('accTrval'), f'{code}.accTrval')
        if (qty == 0) != (amount == 0):
            raise ValueError(f'{segment}: zero volume/value inconsistency {code}')
        result[code] = {'market': market, 'traded_krw': amount, 'traded_shares': qty}
    return result


def assemble(day, regular, closing):
    if not regular:
        raise ValueError('regular market data unavailable')
    rows = {}
    for code in sorted(set(regular) | set(closing)):
        reg, cls = regular.get(code), closing.get(code)
        if reg and cls and reg['market'] != cls['market']:
            raise ValueError(f'{code}: market mismatch')
        market = (reg or cls)['market']
        r_val = reg['traded_krw'] if reg else 0
        c_val = cls['traded_krw'] if cls else 0
        rows[code] = {
            'market': market, 'regular_traded_krw': r_val,
            'closing_traded_krw': c_val, 'traded_krw': r_val + c_val,
            'traded_shares': (reg['traded_shares'] if reg else 0) + (cls['traded_shares'] if cls else 0),
        }
    return {
        'status': 'verified', 'date': day.isoformat(),
        'collected_at_kst': datetime.now(KST).isoformat(),
        'source': 'NEXTRADE official site public trading screens (unofficial HTTP backend)',
        'coverage': 'NXT regular + closing-price auction only; block/basket NOT included',
        'investor_flow': 'unavailable', 'issues': len(rows), 'rows': rows,
    }


def run(day=None, dest=DEST, session=None):
    today = datetime.now(KST).date()
    day = day or today
    if day > today or (today - day).days > 8 or day.weekday() >= 5:
        raise ValueError(f'not a recent trading date: {day}')
    session = session or requests.Session()
    regular = fetch_segment(session, 'regular', day)
    closing = fetch_segment(session, 'closing', day)
    data = assemble(day, regular, closing)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, dest)
    print(f'NXT EOD verified: {data["date"]}, {data["issues"]} issues; excludes block/basket')
    return data


def self_test():
    a = {'market': 'KOSPI', 'traded_krw': 200_000_000, 'traded_shares': 1000}
    b = {'market': 'KOSPI', 'traded_krw': 10_000_000, 'traded_shares': 50}
    result = assemble(date(2026, 11, 2), {'005930': a}, {'005930': b})
    assert result['rows']['005930']['traded_krw'] == 210_000_000
    assert result['rows']['005930']['traded_shares'] == 1050
    try:
        assemble(date(2026, 11, 2), {'005930': a}, {'005930': {**b, 'market': 'KOSDAQ'}})
    except ValueError:
        pass
    else:
        raise AssertionError('missing market mismatch validation')
    print('Offline self-test PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='YYYY-MM-DD (default: KST today)')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        try:
            run(date.fromisoformat(args.date) if args.date else None)
        except (requests.RequestException, ValueError, OSError) as exc:
            raise SystemExit(f'NXT collection FAILED safely: {exc}')
