"""광부 시장신호: Npay 공개 일별 투자자예탁금/신용융자잔고 수집.

비공식 공개 API: 관측 날짜/원시 정수/전일 증감/차트 교차대조 검증.
원문 JSON은 단위를 제공하지 않으므로 1 단위=1억원은 '해석'으로 기록한다.
이용 가능성/응답 구조 변경 시 기존 정상 스냅샷을 보존하고 실패한다.
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'kr_market_liquidity.json'
HOST = 'https://stock.naver.com'
LIST_PATH = '/api/domestic/market/trendDeposit'
CHART_PATH = '/api/domestic/market/trendDeposit/chart'
KST = ZoneInfo('Asia/Seoul')
FIELDS = {'customerDeposit': 'deposit_raw_100m', 'creditLoan': 'credit_raw_100m'}
DIFFS = {'customerDepositDiff': 'deposit_diff_raw_100m', 'creditLoanDiff': 'credit_diff_raw_100m'}
MAX_ROWS = 260

class ValidationError(ValueError):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def source_int(value):
    if isinstance(value, bool) or value is None:
        raise ValidationError('missing or boolean amount')
    raw = str(value).strip()
    if not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+|[+-]?\d+', raw):
        raise ValidationError('non-integer amount')
    return int(raw.replace(',', ''))


def parse_row(row, *, today):
    if not isinstance(row, dict):
        raise ValidationError('row must be an object')
    raw_date = row.get('bizdate')
    if not isinstance(raw_date, str) or not re.fullmatch(r'\d{8}', raw_date):
        raise ValidationError('missing source-supplied 8-digit trade date')
    day = datetime.strptime(raw_date, '%Y%m%d').date()
    if day > today or day.weekday() >= 5 or (today-day).days > 400:
        raise ValidationError(f'invalid/future/stale date: {day}')
    amounts = {target: source_int(row.get(k)) for k,target in {**FIELDS, **DIFFS}.items()}
    if not (10_000 <= amounts['deposit_raw_100m'] <= 5_000_000):
        raise ValidationError(f'deposit outside sanity range: {day}')
    if not (1_000 <= amounts['credit_raw_100m'] <= 3_000_000):
        raise ValidationError(f'credit balance outside sanity range: {day}')
    if max(abs(amounts['deposit_diff_raw_100m']), abs(amounts['credit_diff_raw_100m'])) > 300_000:
        raise ValidationError(f'change outside sanity range: {day}')
    return {'date': day.isoformat(), **amounts}


def parse_list(payload, today):
    if not isinstance(payload, dict) or not isinstance(payload.get('content'), list):
        raise ValidationError('daily list JSON schema changed')
    if not payload['content']:
        return []
    return [parse_row(x, today=today) for x in payload['content']]


def parse_chart(payload, today):
    if not isinstance(payload,list):
        raise ValidationError('chart JSON schema changed')
    return [parse_row(r,today=today) for r in payload]


def source_request(path, params):
    url=HOST+path+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={
        'Accept':'application/json',
        'Referer':HOST+'/',
        'User-Agent':'Mozilla/5.0 (compatible; MinerResearch/1.0)',
    })
    op=urllib.request.build_opener(NoRedirect())
    with op.open(req,timeout=20) as resp:
        if resp.status != 200 or 'json' not in resp.headers.get('Content-Type','').lower():
            raise ValidationError(f'invalid HTTP response type/status: {resp.status}')
        body=resp.read(1_000_001)
        if len(body) > 1_000_000:
            raise ValidationError('JSON body too large')
    return json.loads(body)


def fetch(*,today,request=source_request):
    records={}
    oldest=None
    for page in range(7):
        payload=request(LIST_PATH,{'startIdx':page,'pageSize':20})
        batch=parse_list(payload,today)
        if not batch:
            break
        for row in batch:
            key=row['date']
            if key in records:
                raise ValidationError(f'duplicate page/row date: {key}')
            records[key]=row
        if len(batch)<20 or len(records)>=120:
            break
    if len(records)<20:
        raise ValidationError(f'insufficient history: {len(records)} days')
    days=sorted(records)
    if (today-date.fromisoformat(days[-1])).days>10:
        raise ValidationError(f'stale source latest date: {days[-1]}')
    if (date.fromisoformat(days[-1])-date.fromisoformat(days[0])).days>400:
        raise ValidationError('date range longer than allowed')
    hist=[records[k] for k in days]
    # Previous day from the same source is useful as an independent consistency check.
    for older,newer in zip(hist[:-1],hist[1:]):
        for val,diff in [('deposit_raw_100m','deposit_diff_raw_100m'),
                         ('credit_raw_100m','credit_diff_raw_100m')]:
            # API rounds each figure to 100M KRW; off-by-one is allowed.
            if abs((newer[val]-older[val])-newer[diff])>2:
                raise ValidationError(f'{newer["date"]} {val} inconsistent daily difference')

    end=today.strftime('%Y%m%d')
    start=(today-timedelta(days=110)).strftime('%Y%m%d')
    chart=parse_chart(request(CHART_PATH,{'startDate':start,'endDate':end}),today)
    overlap=0
    for c in chart:
        if c['date'] in records:
            r=records[c['date']]
            if any(r[k]!=c[k] for k in (*FIELDS.values(), *DIFFS.values())):
                raise ValidationError(f'list/chart conflict on {c["date"]}')
            overlap+=1
    if overlap<3:
        raise ValidationError(f'list/chart overlap too small: {overlap}')
    return hist,overlap


def assemble(new, previous, today, overlap):
    merged={}
    if isinstance(previous,dict) and previous.get('status')=='source_validated' and previous.get('source')=='Npay Stock public investor deposit and credit loan JSON':
        for r in previous.get('history',[]):
            if isinstance(r,dict) and isinstance(r.get('date'),str):
                try:
                    d=date.fromisoformat(r['date'])
                    if d>today: continue
                    if all(type(r.get(k)) is int for k in (*FIELDS.values(),*DIFFS.values())):
                        merged[r['date']]=r
                except ValueError: pass
    for r in new:
        merged[r['date']]=r
    history=[merged[d] for d in sorted(merged)[-MAX_ROWS:]]
    if not history:
        raise ValidationError('no daily records')
    return {
        'status':'source_validated',
        'source':'Npay Stock public investor deposit and credit loan JSON',
        'source_url':HOST+LIST_PATH,
        'source_chart_url':HOST+CHART_PATH,
        'unit_assumption':'100M_KRW_per_raw_integer',
        'unit_independently_confirmed':False,
        'notice':'공개 JSON에는 단위가 표기되지 않습니다. 단위당 1억원 해석은 공식 KOFIA 자료로 교차검증이 필요합니다.',
        'latest_date':history[-1]['date'],
        'observations':len(history),
        'chart_overlap_verified_days':overlap,
        'collected_at_kst':datetime.now(timezone.utc).astimezone(KST).isoformat(),
        'history':history,
    }


def run(*,dest=DEST,today=None,request=source_request):
    today=today or datetime.now(timezone.utc).astimezone(KST).date()
    try:
        previous=json.loads(dest.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        previous=None
    history,overlap=fetch(today=today,request=request)
    snapshot=assemble(history,previous,today,overlap)
    dest.parent.mkdir(parents=True,exist_ok=True)
    temporary=dest.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,dest)
    last=snapshot['history'][-1]
    print(f"Liquidity source validated: {snapshot['latest_date']}, history={len(snapshot['history'])}, chart_overlap={overlap}, deposit_raw={last['deposit_raw_100m']}, credit_raw={last['credit_raw_100m']}; unit interpretation requires KOFIA crosscheck")
    return snapshot

if __name__=='__main__':
    try:
        run()
    except Exception as exc:
        print('LIQUIDITY COLLECTION FAILED: '+str(exc),file=sys.stderr)
        sys.exit(1)
