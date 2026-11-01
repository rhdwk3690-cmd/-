"""Market-signal integrity checks. Never infer an unverified market credit balance.

The KOFIA reference is a *fixed, dated public snapshot*, not a live API.
The Oct 28 values are reconstructed from the Oct 29 level and 1-day delta
on https://freesis.kofia.or.kr/stat/main.do, observed on 2026-11-01.
"""
from __future__ import annotations

from datetime import date

KOFIA_SOURCE = 'https://freesis.kofia.or.kr/stat/main.do'
KOFIA_ASOF = '2026-10-29'
# Exact KOFIA published figures: KRW MILLIONS, 2026-10-29.
KOFIA_MILLION_KRW = {
    'deposit_balance': 88_713_283,
    'deposit_day_delta': 415_783,
    'credit_balance': 29_088_592,
    'credit_day_delta': -240_418,
}
BASELINE_DATE = '2026-10-28'


def official_baseline():
    """Compute prior trading-day KOFIA balances (2026-10-28)."""
    x = KOFIA_MILLION_KRW
    return {
        'date': BASELINE_DATE,
        'deposit_million_krw': x['deposit_balance'] - x['deposit_day_delta'],
        'credit_million_krw': x['credit_balance'] - x['credit_day_delta'],
    }


def audit_npay_history(history):
    """Audit only exactly dated rows. No fallback to a nearby date."""
    out = {'baseline_date': BASELINE_DATE, 'official_asof': KOFIA_ASOF,
           'source_url': KOFIA_SOURCE, 'deposit_status': 'unavailable',
           'credit_status': 'unavailable', 'credit_difference_100m_krw': None}
    if not isinstance(history, list):
        return out
    matches = [r for r in history if isinstance(r, dict) and r.get('date') == BASELINE_DATE]
    if len(matches) != 1:
        return out
    r = matches[0]
    ref = official_baseline()
    for kind, field in (('deposit', 'deposit_raw_100m'), ('credit', 'credit_raw_100m')):
        observed = r.get(field)
        if type(observed) is not int or observed <= 0:
            continue
        expected_in_100m = ref[kind + '_million_krw'] / 100.0
        difference = round(float(observed - expected_in_100m), 4)
        # Official KRW millions / Npay integer 100M KRW => rounding tolerance 1 x 100M KRW.
        out[kind + '_status'] = 'matched' if abs(difference) <= 1 else 'mismatched'
        out[kind + '_npay_trillion'] = observed / 10000.0
        out[kind + '_official_trillion'] = ref[kind + '_million_krw'] / 1_000_000.0
        out[kind + '_difference_100m_krw'] = difference
    return out


def oscillator(history, field):
    """5/20 observation MA oscillator, only if dates are unique and reasonably consecutive."""
    if not isinstance(history, list) or len(history) < 20:
        return None
    h = history[-20:]
    try:
        dates = [date.fromisoformat(r['date']) for r in h]
        values = [r[field] for r in h]
        if any(type(v) is not int or v <= 0 for v in values):
            return None
        if len(set(dates)) != 20 or dates != sorted(dates):
            return None
        if (dates[-1] - dates[0]).days > 42:
            return None
        ma20 = sum(values) / 20
        ma5 = sum(values[-5:]) / 5
        return 100 * (ma5 / ma20 - 1)
    except (ValueError, TypeError, KeyError):
        return None


def load_dated_json(path):
    import json
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
