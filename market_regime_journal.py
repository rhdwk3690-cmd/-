"""Immutable as-observed Korean market environment journal and forward index evaluation.

The rule label is saved once when observed (no retrospective classification).
Future performance is evaluated ONLY from strictly later, jointly observed
KOSPI/KOSDAQ daily closes and after 5/20/60 actual exchange sessions.
No trading strategy return, no dividends/costs, no fabricated historical signals.
"""
from __future__ import annotations
import copy
import math
from datetime import date, datetime

SCHEMA = 'miner-market-regime-journal-v1'
MARKETS = ('KOSPI', 'KOSDAQ')
HORIZONS = (5, 20, 60)


class JournalError(ValueError):
    pass


def date_key(value):
    try:
        if isinstance(value, str):
            parsed = date.fromisoformat(value)
        elif isinstance(value, datetime):
            parsed = value.date()
        elif isinstance(value, date):
            parsed = value
        else:
            raise ValueError('invalid date type')
        return parsed.isoformat()
    except (ValueError, TypeError) as exc:
        raise JournalError(f'invalid ISO date: {value!r}') from exc


def validate_prices(prices, *, through):
    """Require dated, positive, monotonically ordered actual closes per index."""
    limit = date_key(through)
    if not isinstance(prices, dict) or set(prices) != set(MARKETS):
        raise JournalError('KOSPI and KOSDAQ closing series required')
    result = {}
    for market in MARKETS:
        rows = prices[market]
        if not isinstance(rows, list) or not rows:
            raise JournalError(f'{market}: no dated closes')
        prior = None
        output = []
        for item in rows:
            if not isinstance(item, dict):
                raise JournalError('close row must be a mapping')
            d = date_key(item.get('date'))
            v = item.get('close')
            if prior is not None and d <= prior:
                raise JournalError(f'{market}: duplicate or unsorted dates')
            if d > limit:
                raise JournalError(f'{market}: future close {d} exceeds {limit}')
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                raise JournalError(f'{market}: invalid close at {d}')
            output.append({'date': d, 'close': round(float(v), 6)})
            prior = d
        result[market] = output
    return result


def merge_closes(previous, incoming, *, through):
    valid_new = validate_prices(incoming, through=through)
    if previous is None:
        return valid_new
    valid_old = validate_prices(previous, through=through)
    result = {}
    for market in MARKETS:
        old = {row['date']: row['close'] for row in valid_old[market]}
        for row in valid_new[market]:
            d, v = row['date'], row['close']
            if d in old:
                # Never silently rewrite a close already used to evaluate a signal.
                if abs(v / old[d] - 1) > 0.0015:
                    raise JournalError(f'{market}: previously saved close was revised >0.15% on {d}')
                continue
            old[d] = v
        result[market] = [{'date': d, 'close': old[d]} for d in sorted(old)]
    return result


def evaluate(prices, *, signal_date):
    """Close-to-close forward return and peak-to-trough close MDD, for N shared sessions."""
    d = date_key(signal_date)
    maps = {market: {x['date']: x['close'] for x in prices[market]} for market in MARKETS}
    shared = sorted(set(maps['KOSPI']) & set(maps['KOSDAQ']))
    one_sided = set(maps['KOSPI']) ^ set(maps['KOSDAQ'])
    if d not in shared:
        return {str(h): {'status': 'pending', 'reason': 'signal date not in both markets'} for h in HORIZONS}
    start = shared.index(d)
    outcomes = {}
    for horizon in HORIZONS:
        if start + horizon >= len(shared):
            outcomes[str(horizon)] = {'status': 'pending', 'completed_sessions': len(shared) - start - 1,
                                       'needed_sessions': horizon}
            continue
        window = shared[start:start + horizon + 1]
        if any(window[0] <= u <= window[-1] for u in one_sided):
            outcomes[str(horizon)] = {'status': 'pending', 'reason': 'a trading date exists for one index only'}
            continue
        # A wide gap means some sessions could be absent. Never assign the wrong N-session horizon.
        if any((date.fromisoformat(y) - date.fromisoformat(x)).days > 8 for x,y in zip(window, window[1:])):
            outcomes[str(horizon)] = {'status': 'pending', 'reason': 'missing or unverified trading-session gap'}
            continue
        metrics = {'status': 'mature', 'exit_date': window[-1], 'sessions': horizon}
        for market in MARKETS:
            values = [maps[market][w] for w in window]
            peak = values[0]
            mdd = 0.0
            for v in values:
                peak = max(peak, v)
                mdd = min(mdd, v / peak - 1)
            metrics[market] = {'entry_close': values[0], 'exit_close': values[-1],
                               'return_pct': round((values[-1] / values[0] - 1) * 100, 4),
                               'max_drawdown_pct': round(mdd * 100, 4)}
        outcomes[str(horizon)] = metrics
    return outcomes


def record_journal(existing, *, incoming_prices, signal, observed_at, through):
    """Merge source closes, freeze first observed label, mature prior outcomes.

    A signal with code='withheld' is retained as a diagnostic, never included
    in any future class-level performance statistics.
    """
    observed = datetime.fromisoformat(observed_at)
    if observed.tzinfo is None:
        raise JournalError('observed_at must include timezone')
    current_day = date_key(through)
    if observed.date().isoformat() != current_day:
        raise JournalError('observation local date mismatch')
    if existing is None:
        prior_prices = None
        prior_records = []
    else:
        if not isinstance(existing, dict) or existing.get('schema') != SCHEMA:
            raise JournalError('existing journal schema mismatch')
        prior_prices = existing.get('index_closes')
        prior_records = existing.get('records')
        if not isinstance(prior_records, list):
            raise JournalError('existing records not list')
    prices = merge_closes(prior_prices, incoming_prices, through=through)
    seen = {}
    for entry in prior_records:
        d = date_key(entry.get('date'))
        if d in seen:
            raise JournalError('duplicate archived decision date')
        if not entry.get('observed_at_kst') or entry.get('code') not in {'withheld','defensive','watch','conditional','expansion'}:
            raise JournalError('archived decision integrity error')
        seen[d] = copy.deepcopy(entry)
    if signal is not None:
        if not isinstance(signal, dict):
            raise JournalError('signal must be mapping')
        d = date_key(signal.get('date'))
        if d > current_day:
            raise JournalError('cannot record a signal on a future date')
        if (date.fromisoformat(current_day) - date.fromisoformat(d)).days > 7:
            raise JournalError('source signal too stale to archive')
        # A label may be created only for the LAST observed joint session, not for an
        # earlier day for which later close data are already known (look-ahead).
        if any(incoming_prices[m][-1]['date'] != d for m in MARKETS):
            raise JournalError('cannot backdate labels when newer index closes are already known')
        if signal.get('code') not in {'withheld','defensive','watch','conditional','expansion'}:
            raise JournalError('unknown market classification')
        if d not in seen:
            row = copy.deepcopy(signal)
            row['date'] = d
            row['observed_at_kst'] = observed_at
            # Prevent accidental storage of retroactive or computed future outcomes from the caller.
            row.pop('forward', None)
            seen[d] = row
    records = []
    for d in sorted(seen):
        row = seen[d]
        row['forward'] = evaluate(prices, signal_date=d)
        records.append(row)
    result = {
        'schema': SCHEMA, 'status': 'observational_unbacktested',
        'source': 'Yahoo Finance verified daily index closes; live Npay-index-volume QA; dated maedong breadth',
        'rule_scope': 'daily point-in-time labels; no retroactive label backfill',
        'outcome_scope': 'close-to-close uninvested index returns and close-based peak-to-trough MDD',
        'horizons_trading_sessions': list(HORIZONS),
        'index_closes': prices,
        'records': records,
    }
    # Write timestamps only if the journal really changed (prevents unnecessary commits).
    prior_comparable = copy.deepcopy(existing) if isinstance(existing, dict) else None
    if prior_comparable is not None:
        prior_comparable.pop('updated_at_kst', None)
    if result != prior_comparable:
        result['updated_at_kst'] = observed_at
    elif existing is not None:
        result['updated_at_kst'] = existing.get('updated_at_kst', observed_at)
    return result
