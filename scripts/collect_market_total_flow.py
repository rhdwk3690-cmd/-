"""광부 투자터미널: KOSPI/KOSDAQ 시장 단위 현물 투자자 순매수 집계.

비공식 Naver Stock 공개 JSON (KRX 거래 기준)만 사용한다.
단위를 억원으로 추정하지 않고 응답의 buyPrice/sellPrice/diffValue 원 단위를 검산한다.
- 9000 외국인; 8000 개인; 기관 세부코드 1000~7000(7100 기타법인 제외)
- 9001 기타외국인, 7100 기타법인은 별도 그룹. 이들을 기관/외국인으로 합치지 않음.
- 실제 거래일과 일자별 종가 확정 값(time 빈 문자열)만 허용.
- 잘못된 응답, 접근 제한, 날짜/매매금액 불일치면 이전 파일 보존.

공개 서비스의 비공식 내부 경로로, 변경/차단 시 수집 실패할 수 있다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'kr_market_total_flow.json'
URL = 'https://stock.naver.com/api/domestic/market/trend/daily'
KST = ZoneInfo('Asia/Seoul')
MARKETS = ('KOSPI', 'KOSDAQ')
INSTITUTION_CODES = ('1000', '2000', '3000', '3100', '4000', '5000', '6000', '7000')
INVESTOR_CODES = ('9000', '8000', '7100', '9001') + INSTITUTION_CODES
MAX_HISTORY = 260


def won(value):
    """응답 금액은 정수 원. 자료 누락/소수/지수 표기/불리언을 0원으로 바꾸지 않는다."""
    if isinstance(value, bool) or value is None:
        raise ValueError('null / bool amount')
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r'[+-]?(?:0|[1-9]\d*)', value.strip()):
        return int(value.strip())
    raise ValueError(f'invalid whole KRW amount: {str(value)[:45]!r}')


def parse_record(row, asof):
    if not isinstance(row, dict):
        raise ValueError('daily row not object')
    day = row.get('bizdate')
    if not isinstance(day, str) or not re.fullmatch(r'\d{8}', day):
        raise ValueError('missing explicit YYYYMMDD trade date')
    d = datetime.strptime(day, '%Y%m%d').date()
    if d > asof or d.weekday() >= 5:
        raise ValueError(f'invalid date {day}')
    # Intraday rows must not be mistaken for finalized daily investor values.
    if row.get('time') not in ('', None):
        return None
    items = row.get('netAmounts')
    if not isinstance(items, list) or not items:
        raise ValueError(f'{day}: missing netAmounts')
    groups = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f'{day}: investor entry not object')
        code = str(item.get('investorGubun', '')).strip()
        if not re.fullmatch(r'\d{4}', code) or code in groups:
            raise ValueError(f'{day}: duplicate/bad investor group {code!r}')
        net = won(item.get('diffValue'))
        bought = won(item.get('buyPrice'))
        sold = won(item.get('sellPrice'))
        if bought < 0 or sold < 0 or net != bought - sold:
            raise ValueError(f'{day}: inconsistent KRW buy/sell/net for investor {code}')
        groups[code] = net
    missing = set(INVESTOR_CODES).difference(groups)
    if missing:
        raise ValueError(f'{day}: missing investor groups {sorted(missing)}')
    unknown = set(groups).difference(set(INVESTOR_CODES) | {'7050'})
    if unknown:
        raise ValueError(f'{day}: unrecognized investor groups {sorted(unknown)}')

    institution = sum(groups[k] for k in INSTITUTION_CODES)
    # Some providers may send institutional total (7050); never double count it.
    if '7050' in groups and abs(groups['7050'] - institution) > 10_000_000:
        raise ValueError(f'{day}: institution aggregate 7050 differs from details')
    # Seller amounts and buyer amounts across disjoint groups should nearly balance.
    balance = institution + groups['8000'] + groups['9000'] + groups['7100'] + groups['9001']
    if abs(balance) > 50_000_000:
        raise ValueError(f'{day}: investors do not approximately balance ({balance:,} KRW)')
    return d.isoformat(), {
        'foreign_net_krw': groups['9000'],
        'institution_net_krw': institution,
        'individual_net_krw': groups['8000'],
        'other_corporate_net_krw': groups['7100'],
        'other_foreign_net_krw': groups['9001'],
    }


def parse_response(payload, market, asof):
    if market not in MARKETS or not isinstance(payload, dict):
        raise ValueError('invalid market/response')
    content = payload.get('content')
    if not isinstance(content, list) or not content:
        raise ValueError(f'{market}: missing daily content')
    data = {}
    for row in content:
        result = parse_record(row, asof)
        if result is None:
            continue
        day, amounts = result
        if day in data:
            raise ValueError(f'{market}: duplicate trade date {day}')
        data[day] = amounts
    if not data:
        raise ValueError(f'{market}: no end-of-day (time empty) entries')
    return data


def fetch_market(market, asof, opener=None):
    if market not in MARKETS:
        raise ValueError('invalid market')
    params = urllib.parse.urlencode({
        'tradeType': 'KRX', 'marketType': market, 'bizdate': asof.strftime('%Y%m%d'),
        'startIdx': 0, 'pageSize': 20,
    })
    req = urllib.request.Request(URL + '?' + params, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; MinerResearch/1.0)',
        'Accept': 'application/json', 'Referer': 'https://stock.naver.com/',
    })
    request = opener or urllib.request.urlopen
    with request(req, timeout=20) as resp:
        if resp.status != 200:
            raise ValueError(f'{market}: HTTP {resp.status}')
        content_type = resp.headers.get('Content-Type', '')
        if 'json' not in content_type.lower():
            raise ValueError(f'{market}: unexpected content type {content_type}')
        raw = resp.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError(f'{market}: response too large')
    return parse_response(json.loads(raw), market, asof)


def assemble(rows, previous, asof):
    if not isinstance(rows, dict) or set(rows) != set(MARKETS):
        raise ValueError('both markets required')
    common = sorted(set(rows['KOSPI']).intersection(rows['KOSDAQ']))
    if not common:
        raise ValueError('KOSPI/KOSDAQ have no common dated rows')
    new_latest = date.fromisoformat(common[-1])
    if new_latest > asof or (asof - new_latest).days > 8:
        raise ValueError(f'stale market response {new_latest}')
    history = {}
    if isinstance(previous, dict) and isinstance(previous.get('history'), list):
        for entry in previous['history']:
            try:
                if not isinstance(entry, dict):
                    continue
                d = date.fromisoformat(entry['date'])
                if d > asof:
                    continue
                for market in MARKETS:
                    for field in ('foreign_net_krw', 'institution_net_krw', 'individual_net_krw'):
                        v = entry[market][field]
                        if not isinstance(v, int) or isinstance(v, bool):
                            raise ValueError('invalid prior data')
                history[d.isoformat()] = entry
            except (ValueError, TypeError, KeyError):
                continue
    for day in common:
        history[day] = {'date': day, **{m: rows[m][day] for m in MARKETS}}
    entries = [history[d] for d in sorted(history)[-MAX_HISTORY:]]
    if not entries:
        raise ValueError('empty merged market history')
    return {
        'status': 'verified',
        # Retain the existing UI's accepted secondary-provider label.
        'source': 'Naver Finance - market investor daily net trading',
        'source_page': URL,
        'scope': 'KRX tradeType; KOSPI/KOSDAQ market-level investor trading via public Naver Stock JSON',
        'includes_etf_etn_elw': None,
        'unit': 'KRW',
        'investor_codes': {
            'foreign': '9000', 'individual': '8000',
            'institution_detail': list(INSTITUTION_CODES),
            'other_corporate_excluded': '7100', 'other_foreign_excluded': '9001',
        },
        'collected_at_kst': datetime.now(timezone.utc).astimezone(KST).isoformat(),
        'latest_date': entries[-1]['date'],
        'observations': len(entries), 'history': entries,
        'futures_status': 'not_connected',
        'note': 'Unofficial public Naver Stock JSON, not official KRX open API. Integer KRW verified against buyPrice-sellPrice; other corporate/foreign kept separate. ETF inclusion not independently audited.',
    }


def run(dest=DEST, today=None, fetcher=None):
    today = today or datetime.now(timezone.utc).astimezone(KST).date()
    try:
        previous = json.loads(dest.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        previous = None
    fetcher = fetcher or fetch_market
    rows = {market: fetcher(market, today) for market in MARKETS}
    obj = assemble(rows, previous, today)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, dest)
    last = obj['history'][-1]
    print(f"Market total VERIFIED date={last['date']}, days={len(obj['history'])}, source=stock.naver.com KRX JSON")
    for market in MARKETS:
        r = last[market]
        print(f"{market} foreign={r['foreign_net_krw']} KRW, institution={r['institution_net_krw']} KRW, individual={r['individual_net_krw']} KRW")
    return obj


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', default=str(DEST))
    args = p.parse_args()
    try:
        run(dest=Path(args.output))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, OSError, urllib.error.URLError) as exc:
        print(f'Market total collection FAILED safely: {exc}', file=sys.stderr)
        sys.exit(1)
