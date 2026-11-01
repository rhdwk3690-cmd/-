"""KOSPI/KOSDAQ market-level investor trading trend collector from Naver Finance.

Fallback for pykrx's authenticated KRX website. NAVER is a *secondary provider*,
not a KRX official API. Its public market-level daily table is in 100M KRW.
If a table changes, is blocked, or has no parsable dated entries, fail closed.
Never infer an absent value, a date, or the ETF composition of the provider.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'kr_market_total_flow.json'
KST = ZoneInfo('Asia/Seoul')
MARKETS = {'KOSPI': '01', 'KOSDAQ': '02'}
FIELDS = {'개인': 'individual_net_krw', '외국인': 'foreign_net_krw', '기관계': 'institution_net_krw'}
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; MinerFinanceResearch/1.0)',
           'Referer': 'https://finance.naver.com/sise/',
           'Accept': 'text/html,application/xhtml+xml'}
URL = 'https://finance.naver.com/sise/investorDealTrendDay.naver'


def numeric_100m_to_krw(value):
    """Convert disclosed 100M KRW amounts to exact integer won, never assume missing is zero."""
    if value is None or isinstance(value, bool) or pd.isna(value):
        raise ValueError('missing net amount')
    s = str(value).strip().replace(',', '').replace('−', '-')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', s):
        raise ValueError(f'invalid numerical amount {s[:60]!r}')
    try:
        val = Decimal(s) * Decimal(100_000_000)
    except InvalidOperation as exc:
        raise ValueError('invalid decimal') from exc
    if not val.is_finite() or val != val.to_integral_value():
        raise ValueError('net amount is not exact whole KRW')
    return int(val)


def parse_day(value):
    s = str(value).strip()
    for fmt in ('%y.%m.%d', '%Y.%m.%d', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def matching_columns(df):
    """Identify column roles by actual header labels, including multi-row Naver headers."""
    roles = {}
    for col in df.columns:
        parts = col if isinstance(col, tuple) else (col,)
        names = [str(x).strip().replace(' ', '') for x in parts]
        compact = '|'.join(x for x in names if not x.lower().startswith('unnamed'))
        for label in ('날짜', *FIELDS):
            if label in names or (label == '기관계' and '기관계' in compact):
                if label in roles and roles[label] != col:
                    raise ValueError(f'ambiguous column {label}')
                roles[label] = col
    if set(roles) != {'날짜', *FIELDS}:
        raise ValueError(f'invalid Naver table columns; found {sorted(roles)}')
    return roles


def parse_naver_html(html, *, asof, market):
    if not isinstance(html, str) or len(html) < 100:
        raise ValueError(f'{market}: empty or invalid HTML')
    if '단위' not in html or ('억원' not in html and '억 원' not in html):
        raise ValueError(f'{market}: 100M KRW unit not confirmed in source HTML')
    if '날짜' not in html or '기관계' not in html or '외국인' not in html:
        raise ValueError(f'{market}: expected investor trading table not present')
    try:
        tables = pd.read_html(StringIO(html), displayed_only=False)
    except (ValueError, ImportError) as exc:
        raise ValueError(f'{market}: Naver HTML has no valid tables') from exc
    found = []
    for frame in tables:
        try:
            roles = matching_columns(frame)
        except ValueError:
            continue
        results = {}
        for _, row in frame.iterrows():
            day = parse_day(row[roles['날짜']])
            if day is None:
                continue
            if day > asof or day.weekday() >= 5:
                continue
            key = day.isoformat()
            if key in results:
                raise ValueError(f'{market}: duplicate trading date {key}')
            amounts = {output: numeric_100m_to_krw(row[roles[label]])
                       for label, output in FIELDS.items()}
            if all(v == 0 for v in amounts.values()):
                continue
            results[key] = amounts
        if results:
            found.append(results)
    if len(found) != 1:
        raise ValueError(f'{market}: expected one dated investor table, got {len(found)}')
    return found[0]


def fetch_naver(asof, session=None):
    owns = session is None
    session = session or requests.Session()
    data = {}
    try:
        for market, sosok in MARKETS.items():
            response = session.get(URL, params={'bizdate': asof.strftime('%Y%m%d'),
                                               'sosok': sosok, 'page': 1},
                                   headers=HEADERS, timeout=15)
            response.raise_for_status()
            # Old Naver Finance uses EUC-KR; requests may get it from Content-Type.
            response.encoding = response.encoding or response.apparent_encoding or 'euc-kr'
            data[market] = parse_naver_html(response.text, asof=asof, market=market)
    finally:
        if owns:
            session.close()
    return data


def assemble(rows, previous, asof, max_age=8):
    if set(rows) != set(MARKETS):
        raise ValueError('both KOSPI and KOSDAQ required')
    days = sorted(set(rows['KOSPI']) & set(rows['KOSDAQ']))
    if not days:
        raise ValueError('no common dated market records')
    latest = date.fromisoformat(days[-1])
    if (asof-latest).days > max_age or latest > asof:
        raise ValueError(f'stale/future source data: {latest}')
    all_days = {}
    if isinstance(previous, dict):
        for e in previous.get('history', []):
            try:
                d = date.fromisoformat(e['date'])
                if d > asof: continue
                for market in MARKETS:
                    for field in FIELDS.values():
                        v = e[market][field]
                        if not isinstance(v, int) or isinstance(v, bool):
                            raise ValueError('noninteger history')
                all_days[e['date']] = e
            except (KeyError, ValueError, TypeError):
                continue
    for day in days:
        all_days[day] = {'date': day, **{m: rows[m][day] for m in MARKETS}}
    history = [all_days[d] for d in sorted(all_days)[-260:]]
    # Existing KRX-validated histories may have a later date than this Naver snapshot.
    # Require source returned day to be the actual latest after merge, not just latest fetched.
    return {'status': 'verified',
            'source': 'Naver Finance - market investor daily net trading',
            'source_page': URL,
            'scope': 'KOSPI / KOSDAQ market-level daily investor net trading; provider composition not independently audited',
            'includes_etf_etn_elw': None,
            'unit': 'KRW',
            'collected_at_kst': datetime.now(timezone.utc).astimezone(KST).isoformat(),
            'latest_date': history[-1]['date'],
            'observations': len(history), 'history': history,
            'futures_status': 'not_connected',
            'note': 'NAVER public table (not KRX official API); source values disclosed in 100M KRW, converted into KRW. ETF composition not independently confirmed.'}


def run(dest=DEST, today=None, session=None):
    today = today or datetime.now(timezone.utc).astimezone(KST).date()
    try:
        previous = json.loads(dest.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        previous = None
    rows = fetch_naver(today, session=session)
    out = assemble(rows, previous, today)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + '.tmp')
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(tmp, dest)
    print(f"NAVER market totals: latest {out['latest_date']} history={len(out['history'])}, source=Naver, scope not independently audited")
    return out


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', default=str(DEST))
    args = p.parse_args()
    try:
        run(dest=Path(args.output))
    except Exception as exc:
        print(f'NAVER market-total data collection FAILED: {exc}', file=sys.stderr)
        sys.exit(1)
