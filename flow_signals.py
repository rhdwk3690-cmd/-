"""광부 투자터미널 수급 지표 - 순수 계산 모듈(네트워크/Streamlit 없음).

모든 수치는 '그 거래일의 거래대금 TOP200 종목 표본'에 한정된다.
시장 전체 KRX 공식 투자자별 수급과 혼동하지 않는다.
최초부터 5/20개 유효 거래일이 쌓일 때까진 오실레이터를 표시하지 않는다.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

MARKETS = ('ALL', 'KOSPI', 'KOSDAQ')
MAX_HISTORY = 260


def _valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('날짜 형식이 YYYY-MM-DD가 아닙니다')
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError('유효하지 않은 거래일') from e


def _money(value):
    # None을 0으로 바꾸지 않는다. float/bool은 원 단위 정확한 숫자가 아니다.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def summarize_snapshot(ranking: dict, flow: dict) -> dict:
    """순매수/거래대금과 확산도를 계산. 날짜/종목 구성/금액 가용성 검증 필수."""
    if ranking.get('status') != 'verified':
        raise ValueError('거래대금 TOP200이 verified 상태가 아닙니다')
    day = ranking.get('date')
    _valid_date(day)
    if not isinstance(flow, dict) or flow.get('date') != day:
        raise ValueError('수급 거래일과 거래대금 기준일 불일치')
    ranked = ranking.get('top200')
    if not isinstance(ranked, list) or len(ranked) != 200:
        raise ValueError('TOP200의 종목 수가 200개가 아닙니다')
    codes = [str(x.get('ticker', '')) for x in ranked]
    if len(set(codes)) != 200 or any(not re.fullmatch(r'\d{6}', x) for x in codes):
        raise ValueError('TOP200 코드가 중복되거나 비정상입니다')
    fp = hashlib.sha256((day + '|' + ','.join(codes)).encode('utf-8')).hexdigest()
    if flow.get('fingerprint') != fp:
        raise ValueError('수급과 TOP200 종목 구성이 불일치합니다')
    rows = flow.get('rows')
    if not isinstance(rows, dict):
        raise ValueError('수급 rows는 코드별 객체여야 합니다')

    buckets = {m: [] for m in MARKETS}
    for r in ranked:
        code = r['ticker']
        market = r.get('market')
        trade = _money(r.get('traded_krw'))
        if market not in ('KOSPI', 'KOSDAQ') or trade is None or trade <= 0:
            raise ValueError(f'{code}: 시장/거래대금이 유효하지 않습니다')
        record = rows.get(code)
        f = i = None
        if isinstance(record, dict) and record.get('date') == day:
            f = _money(record.get('foreign_net_krw'))
            i = _money(record.get('institution_net_krw'))
        tup = (trade, f, i)
        buckets['ALL'].append(tup)
        buckets[market].append(tup)

    metrics = {}
    for market, values in buckets.items():
        target = len(values)
        traded_total = sum(x[0] for x in values)
        paired = [(trade, f, i) for trade, f, i in values if f is not None and i is not None]
        count = len(paired)
        traded_paired = sum(x[0] for x in paired)
        foreign = sum(x[1] for x in paired)
        institution = sum(x[2] for x in paired)
        both_buy = sum(f > 0 and i > 0 for _, f, i in paired)
        both_sell = sum(f < 0 and i < 0 for _, f, i in paired)
        combined_buy = sum(f + i > 0 for _, f, i in paired)
        pct = lambda amount: 100 * amount / traded_paired if traded_paired else None
        metrics[market] = {
            'target_count': target,
            'paired_count': count,
            'target_traded_krw': traded_total,
            'paired_traded_krw': traded_paired,
            'coverage_pct': 100 * count / target if target else 0,
            'turnover_coverage_pct': 100 * traded_paired / traded_total if traded_total else 0,
            'foreign_net_krw': foreign if count else None,
            'institution_net_krw': institution if count else None,
            'joint_net_krw': foreign + institution if count else None,
            'foreign_strength_pct': pct(foreign),
            'institution_strength_pct': pct(institution),
            'joint_strength_pct': pct(foreign + institution),
            'both_buy_count': both_buy,
            'both_sell_count': both_sell,
            'combined_buy_count': combined_buy,
            'diffusion_pct': 100 * (both_buy - both_sell) / count if count else None,
        }
    return {
        'date': day,
        'scope': 'Daily changing KOSPI+KOSDAQ traded-value TOP200 only',
        'metrics': metrics,
    }


def merge_history(old_history, latest_summary, *, limit=MAX_HISTORY):
    """날짜별 단일 관측값을 보관. 재실행하면 같은 날짜는 최신 값으로 대체."""
    by_date = {}
    for row in old_history if isinstance(old_history, list) else []:
        if isinstance(row, dict) and isinstance(row.get('metrics'), dict):
            try:
                _valid_date(row.get('date'))
            except ValueError:
                continue
            by_date[row['date']] = row
    if latest_summary and isinstance(latest_summary.get('metrics'), dict):
        _valid_date(latest_summary['date'])
        by_date[latest_summary['date']] = latest_summary
    return [by_date[d] for d in sorted(by_date)[-limit:]]


def valid_history(history, market='ALL'):
    """5/20일: 두 투자자 금액과 거래대금이 충실히 확보된 *고유 거래일*만 사용."""
    if market not in MARKETS:
        raise ValueError('잘못된 시장 이름')
    by_date = {}
    for entry in history if isinstance(history, list) else []:
        try:
            if not isinstance(entry, dict):
                continue
            d = entry['date']
            _valid_date(d)
            v = entry['metrics'][market]
            target = v['target_count']
            paired = v['paired_count']
            turnover = v['paired_traded_krw']
            if (not isinstance(target, int) or target <= 0 or
                    not isinstance(paired, int) or paired < 1 or
                    not isinstance(turnover, int) or turnover <= 0 or
                    v['coverage_pct'] < 95 or v['turnover_coverage_pct'] < 98 or
                    not isinstance(v['joint_net_krw'], int)):
                continue
            by_date[d] = entry
        except (KeyError, TypeError, ValueError):
            continue
    return [by_date[d] for d in sorted(by_date)]


def rolling_strength(history, market='ALL', window=5):
    """최근 N개 품질 통과 관측일의 합산 순매수/합산 거래대금. 임의 보간 없음."""
    if window < 1:
        raise ValueError('window는 양수여야 합니다')
    rows = valid_history(history, market)
    if len(rows) < window:
        return None
    rows = rows[-window:]
    # 관측 누락에 의한 오래된 구간을 5/20일로 잘못 표시하지 않는다.
    span = (_valid_date(rows[-1]['date']) - _valid_date(rows[0]['date'])).days
    if span > (12 if window == 5 else 43 if window == 20 else window * 3):
        return None
    total_flow = sum(x['metrics'][market]['joint_net_krw'] for x in rows)
    total_traded = sum(x['metrics'][market]['paired_traded_krw'] for x in rows)
    if total_traded <= 0:
        return None
    return {'pct': 100 * total_flow / total_traded, 'start': rows[0]['date'],
            'end': rows[-1]['date'], 'observations': len(rows)}
