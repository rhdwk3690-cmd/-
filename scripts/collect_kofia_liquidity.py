"""Collect KOFIA FreeSIS *website* public statistics, not the separately keyed OpenAPI.

Read-only two small JSON requests; fail closed if schema, date, units, reference
values, or historical overlap cannot be validated. Do not bypass access controls.
Official screen fields are in KRW millions, unlike Npay's undocumented unit.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'kr_kofia_liquidity.json'
URL = 'https://freesis.kofia.or.kr/meta/getMetaDataList.do'
SOURCE = 'KOFIA FreeSIS official statistics website (public read-only JSON)'
KST = ZoneInfo('Asia/Seoul')
SERVICES = {
    'deposit': 'STATSCU0100000060BO',  # 투자자예탁금, including derivatives collateral
    'credit': 'STATSCU0100000070BO',   # 신용거래융자 전체 = total
}
# Grounded independently in the FreeSIS homepage, date 2026-10-29, unit KRW million.
ANCHOR_DATE = '2026-10-29'
ANCHOR = {'deposit_million_krw': 88_713_283, 'credit_million_krw': 29_088_592}


class ValidationError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def amount(value, label):
    if value is None or isinstance(value, bool):
        raise ValidationError(f'{label} missing amount')
    raw = str(value).strip().replace(',', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.0+)?', raw):
        raise ValidationError(f'{label} invalid whole-million amount')
    try:
        v = Decimal(raw)
        if not v.is_finite() or v != v.to_integral_value():
            raise ValidationError(f'{label} not an integer million KRW')
        return int(v)
    except InvalidOperation as exc:
        raise ValidationError(f'{label} invalid amount') from exc


def parse_date(value, today):
    if not isinstance(value, str) or not re.fullmatch(r'\d{8}', value):
        raise ValidationError(f'invalid source date {str(value)[:40]!r}')
    d = datetime.strptime(value, '%Y%m%d').date()
    if d > today or d.weekday() >= 5 or (today - d).days > 460:
        raise ValidationError(f'invalid future/non-weekday/ancient source date {d}')
    return d.isoformat()


def parse_service(payload, service, today):
    if not isinstance(payload, dict) or not isinstance(payload.get('ds1'), list):
        raise ValidationError(f'{service} JSON schema: expected ds1 list')
    if not payload['ds1']:
        raise ValidationError(f'{service}: empty official statistics result')
    result = {}
    for row in payload['ds1']:
        if not isinstance(row, dict):
            raise ValidationError(f'{service}: non-object row')
        day = row.get('TMPV1')
        if day in ('합계', '평균'):
            continue
        key = parse_date(str(day) if day is not None else day, today)
        if key in result:
            raise ValidationError(f'{service}: duplicate date {key}')
        main = amount(row.get('TMPV2'),f'{service}/{key}/TMPV2')
        if service == 'deposit':
            # Restrict to plausible 10tr to 250tr for the contemporary market.
            if not 10_000_000 <= main <= 250_000_000:
                raise ValidationError(f'{service}/{key} outside plausible millions range')
            result[key] = {'deposit_million_krw':main}
        elif service == 'credit':
            if not 1_000_000 <= main <= 120_000_000:
                raise ValidationError(f'{service}/{key} outside plausible millions range')
            item = {'credit_million_krw':main}
            if row.get('TMPV3') is not None and row.get('TMPV4') is not None:
                kospi=amount(row['TMPV3'],f'{service}/{key}/kospi')
                kosdaq=amount(row['TMPV4'],f'{service}/{key}/kosdaq')
                if min(kospi,kosdaq)<0 or kospi+kosdaq > main+3:
                    raise ValidationError(f'{service}/{key} invalid market breakdown')
                item['credit_kospi_million_krw']=kospi
                item['credit_kosdaq_million_krw']=kosdaq
            result[key]=item
        else:
            raise ValidationError('unsupported service')
    if len(result) < 60:
        raise ValidationError(f'{service}: insufficient historical rows {len(result)}')
    return result


def fetch_service(service, start, end, opener=None):
    if service not in SERVICES:
        raise ValidationError('unsupported service')
    body = json.dumps({'dmSearch':{
        'tmpV40':'1000000','tmpV41':'1','tmpV1':'D',
        'tmpV45':start.strftime('%Y%m%d'),'tmpV46':end.strftime('%Y%m%d'),
        'OBJ_NM':SERVICES[service],
    }},separators=(',',':')).encode('utf-8')
    request=urllib.request.Request(URL,data=body,method='POST',headers={
        'Content-Type':'application/json', 'Accept':'application/json',
        'Referer':'https://freesis.kofia.or.kr/',
        'User-Agent':'Mozilla/5.0 (compatible; MinerPersonalResearch/1.0)',
    })
    opener=opener or urllib.request.build_opener(NoRedirect())
    with opener.open(request,timeout=25) as response:
        status=response.status
        content_type=response.headers.get('Content-Type','')
        raw=response.read(2_000_001)
    if status!=200 or 'json' not in content_type.lower() or len(raw)>2_000_000:
        raise ValidationError(f'{service}: unexpected HTTP status/content-type/size: {status}, {content_type}')
    try:
        return json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise ValidationError(f'{service}: malformed JSON') from exc


def assemble(deposits, credits, previous, today):
    if len(deposits) < 60 or len(credits) < 60:
        raise ValidationError('source histories require >= 60 dates each')
    common=sorted(set(deposits)&set(credits))
    if len(common)<60:
        raise ValidationError(f'aligned official dates insufficient: {len(common)}')
    latest=date.fromisoformat(common[-1])
    if (today-latest).days>10:
        raise ValidationError(f'FreeSIS official data stale: {latest}')
    if abs((date.fromisoformat(max(deposits))-date.fromisoformat(max(credits))).days)>5:
        raise ValidationError('deposit and credit are published for widely different dates')
    # Official portal homepage 2026-10-29 fixed reference, values in million KRW.
    # Anchor only when the day exists in the returned 400d window.
    if ANCHOR_DATE in deposits:
        if abs(deposits[ANCHOR_DATE]['deposit_million_krw']-ANCHOR['deposit_million_krw'])>1:
            raise ValidationError('FreeSIS deposit disagrees with its official homepage anchor')
    if ANCHOR_DATE in credits:
        if abs(credits[ANCHOR_DATE]['credit_million_krw']-ANCHOR['credit_million_krw'])>1:
            raise ValidationError('FreeSIS credit disagrees with its official homepage anchor')
    if today-timedelta(days=405) <= date.fromisoformat(ANCHOR_DATE) <= today and latest >= date.fromisoformat(ANCHOR_DATE) and not (ANCHOR_DATE in deposits and ANCHOR_DATE in credits):
        raise ValidationError('official 2026-10-29 reference row missing from recent response')
    history={}
    if isinstance(previous,dict) and previous.get('status')=='official_source_validated' and previous.get('source')==SOURCE:
        for row in previous.get('history',[]):
            try:
                k=row['date']
                if date.fromisoformat(k)>today:
                    continue
                if all(type(row.get(field)) is int and row[field]>0 for field in ANCHOR):
                    history[k]=row
            except (KeyError,ValueError,TypeError):
                continue
    for k in common:
        history[k]={'date':k,**deposits[k],**credits[k]}
    ordered=[history[k] for k in sorted(history)[-280:]]
    if ordered[-1]['date']!=common[-1]:
        raise ValidationError('merged latest date differs from actual response date')
    return {
        'status':'official_source_validated','source':SOURCE,
        'source_url':'https://freesis.kofia.or.kr/stat/main.do',
        'data_access_url':URL,
        'data_access_method':'Public website JSON, not the separate approved-key KOFIA OpenAPI',
        'unit':'KRW_million','unit_confirmed_from':'FreeSIS official public homepage: 백만원',
        'credit_definition':'신용거래융자 전체 (KOSPI/KOSDAQ market total from FreeSIS credit balance screen)',
        'deposit_definition':'투자자예탁금 (장내파생상품 거래예수금 포함)',
        'latest_date':ordered[-1]['date'],'observations':len(ordered),
        'collected_at_kst':datetime.now(timezone.utc).astimezone(KST).isoformat(),
        'history':ordered,
        'note':'Dated published balances, not real-time flows. Compare Npay only on identical dates. Does not imply this is the keyed OpenAPI. No fabricated units/values.',
    }


def run(dest=DEST,today=None,requester=fetch_service):
    today=today or datetime.now(KST).date()
    start=today-timedelta(days=405)
    try:
        previous=json.loads(dest.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        previous=None
    dep=parse_service(requester('deposit',start,today),'deposit',today)
    cred=parse_service(requester('credit',start,today),'credit',today)
    obj=assemble(dep,cred,previous,today)
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(tmp,dest)
    last=obj['history'][-1]
    print(f"KOFIA official statistics validated: latest={obj['latest_date']} days={obj['observations']} deposit_million_krw={last['deposit_million_krw']} credit_million_krw={last['credit_million_krw']}")
    return obj


if __name__=='__main__':
    try:
        run()
    except Exception as exc:
        print(f'KOFIA official source collection FAILED (prior snapshot preserved): {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)
