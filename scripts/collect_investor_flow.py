"""광부 투자터미널: TOP200 외국인·기관 EOD 순매수 금액 독립 수집.

매동 공개 API의 날짜별 *게시된* 원 단위 금액만 사용한다. 장중 추정값/임의 추정/0원 대체 금지.
별도 파일로 저장해 검증된 거래대금 TOP200(data/kr_flow.json)을 훼손하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
RANK_FILE = ROOT / 'data' / 'kr_flow.json'
FLOW_FILE = ROOT / 'data' / 'kr_investor_flow.json'
KST = ZoneInfo('Asia/Seoul')
ENDPOINT = 'https://maedong.kr/api/v1/stock/{code}/flow'
# API: IP 60/min, flow 400/day. 1.2초 간격, 200종목 1일 1회, 재시도 없음.
WAIT_SECONDS = 1.2
HEADERS = {'User-Agent': 'MinerResearch/1.0 (personal noncommercial research)',
           'Accept': 'application/json'}


def fingerprint(day: str, codes: list[str]) -> str:
    return hashlib.sha256((day + '|' + ','.join(codes)).encode('utf-8')).hexdigest()


def exact_krw(value):
    """원 단위 정수 또는 null. 수량은 금액으로 환산하지 않는다."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = Decimal(str(value).replace(',', '').strip())
        if not v.is_finite() or v != v.to_integral_value():
            return None
        return int(v)
    except (InvalidOperation, ValueError):
        return None


def extract_flow(payload, code: str, day: str):
    """명확한 종목·날짜·금액 필드만 수락. 값 미게시 시 None."""
    if not isinstance(payload, dict):
        raise ValueError('API 응답이 JSON 객체가 아닙니다')
    body = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    returned_code = body.get('code', payload.get('code'))
    if returned_code is None or str(returned_code).zfill(6) != code:
        raise ValueError('종목코드 불일치 또는 누락')
    records = body.get('rows')
    if not isinstance(records, list):
        raise ValueError('rows 배열이 없는 API 응답')
    same_day = [row for row in records if isinstance(row, dict) and row.get('date') == day]
    if len(same_day) > 1:
        raise ValueError('같은 거래일 수급 행 중복')
    if not same_day:
        return None
    row = same_day[0]
    f = exact_krw(row.get('foreign_net_krw'))
    i = exact_krw(row.get('institution_net_krw'))
    p = exact_krw(row.get('individual_net_krw'))
    if all(v is None for v in (f, i, p)):
        return None
    return {'date': day, 'foreign_net_krw': f, 'institution_net_krw': i,
            'individual_net_krw': p}


def validated_ranking():
    obj = json.loads(RANK_FILE.read_text(encoding='utf-8'))
    if obj.get('status') != 'verified' or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(obj.get('date') or '')):
        raise ValueError('TOP200 자료의 상태 또는 거래일이 미검증')
    date = obj['date']
    if not str(obj.get('date_quality') or '').strip() or obj['date_quality'] == 'unverified':
        raise ValueError('TOP200 원자료 날짜 품질 미검증')
    rank = obj.get('top200') or []
    codes = [str(x.get('ticker') or '') for x in rank]
    if len(codes) != 200 or len(set(codes)) != 200 or any(not re.fullmatch(r'\d{6}', s) for s in codes):
        raise ValueError('TOP200 목록이 정확한 200개의 고유 6자리 코드가 아닙니다')
    return date, codes


def save(out):
    FLOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FLOW_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, FLOW_FILE)


def run(session=None, sleeper=time.sleep, wait=WAIT_SECONDS, max_codes=200):
    date, codes = validated_ranking()
    codes = codes[:min(200, max_codes)]
    signature = fingerprint(date, codes)
    try:
        old = json.loads(FLOW_FILE.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        old = None
    # 이미 같은 TOP200을 모두 요청했다면 수급 API 일간 400회 제한 낭비하지 않음.
    if old and old.get('fingerprint') == signature and set(old.get('attempted_codes') or []) == set(codes):
        print(f'Already queried all {len(codes)} codes for {date}; skipping.')
        return old
    if old and old.get('fingerprint') == signature:
        attempted = set(old.get('attempted_codes') or [])
        rows = dict(old.get('rows') or {})
        errors = list(old.get('errors') or [])
    else:
        attempted, rows, errors = set(), {}, []
    own_session = session is None
    session = session or requests.Session()
    try:
        for code in codes:
            if code in attempted:
                continue
            if attempted:
                sleeper(wait)
            try:
                r = session.get(ENDPOINT.format(code=code), params={'from': date, 'to': date},
                                headers=HEADERS, timeout=12)
                if r.status_code == 429:
                    errors.append(f'{code}: API 429 제한. 남은 종목 요청 중단')
                    break
                r.raise_for_status()
                value = extract_flow(r.json(), code, date)
                if value is not None:
                    rows[code] = value
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                errors.append(f'{code}: {type(exc).__name__}: {str(exc)[:120]}')
            attempted.add(code)
            # 중간에 자동화가 종료되어도 이미 수집한 응답은 보존
            if len(attempted) % 20 == 0:
                save(build_snapshot(date, codes, signature, attempted, rows, errors))
    finally:
        if own_session:
            session.close()
    out = build_snapshot(date, codes, signature, attempted, rows, errors)
    save(out)
    print(f"date={date}, attempted={len(attempted)}/200, any_flow={out['published_codes']}, "
          f"full_flow={out['complete_codes']}, status={out['status']}")
    return out


def build_snapshot(day, codes, sig, attempted, rows, errors):
    full = sum(1 for code in codes if code in rows and
               rows[code]['foreign_net_krw'] is not None and
               rows[code]['institution_net_krw'] is not None)
    return {'source': 'maedong.kr API /api/v1/stock/{code}/flow',
            'collected_at_kst': datetime.now(timezone.utc).astimezone(KST).isoformat(),
            'date': day, 'fingerprint': sig, 'target_codes': len(codes),
            'attempted_codes': sorted(attempted),
            'published_codes': len(rows), 'complete_codes': full,
            'status': ('complete' if full == len(codes) else 'partial' if rows else 'unavailable'),
            'rows': rows, 'errors': errors[:100],
            'note': 'Published EOD investor flows only. Missing records are null, not zero. Coverage differs from TOP200; no inference.'}


if __name__ == '__main__':
    run()
