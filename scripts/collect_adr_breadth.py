"""Daily KOSPI+KOSDAQ public-market breadth, stored to compute ADR20 offline.

Maedong /api/v1/market?date=YYYY-MM-DD returns a dated, market-wide up/down
snapshot. Initial backfill uses bounded GETs. Subsequent runs normally fetch
one or two new dates. Never requests the current date (which can be provisional).
No synthetic dates, zero-filled holidays, or unofficial KRX/IBD claims.
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data'/'kr_market_adr20.json'
URL = 'https://maedong.kr/api/v1/market'
SOURCE = 'maedong.kr public market breadth (KOSPI+KOSDAQ combined)'
KST = ZoneInfo('Asia/Seoul')
MAX_ARCHIVE = 260

class SourceError(ValueError):
    pass

def parse(payload, requested):
    if not isinstance(payload,dict):
        raise SourceError('API root is not an object')
    data=payload.get('data') if isinstance(payload.get('data'),dict) else payload
    issued=data.get('date')
    if issued!=requested.isoformat():
        raise SourceError(f'date mismatch requested={requested} returned={issued!r}')
    b=data.get('breadth')
    if not isinstance(b,dict):
        raise SourceError('no market breadth counts')
    fields=(b.get('up'),b.get('down'),b.get('unchanged',b.get('flat')))
    if any(type(x) is not int for x in fields):
        raise SourceError('up/down/flat must be integer counts')
    up,down,flat=fields
    if any(x<0 for x in fields) or not 1400 <= up+down+flat <= 5000:
        raise SourceError(f'implausible aggregate breadth {fields}')
    if up+down==0:
        raise SourceError('no directional market breadth')
    if requested.weekday()>=5:
        raise SourceError('market breadth on weekend not accepted')
    return {'date':requested.isoformat(),'up':up,'down':down,'flat':flat,
            'universe_total':up+down+flat}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

def fetch_day(day):
    req=urllib.request.Request(URL+'?'+urllib.parse.urlencode({'date':day.isoformat()}),headers={
        'Accept':'application/json', 'User-Agent':'MinerTerminal/1.0 (personal noncommercial research)'})
    opener=urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req,timeout=12) as resp:
            if resp.status!=200 or 'json' not in resp.headers.get('Content-Type','').lower():
                raise SourceError(f'unexpected HTTP/content type: {resp.status}')
            raw=resp.read(180_001)
            if len(raw)>180_000:
                raise SourceError('API response too large')
    except urllib.error.HTTPError as exc:
        if exc.code in (404,204):
            return None
        if exc.code==429:
            raise SourceError('maedong HTTP 429 quota; stop without bypass/retry') from exc
        raise SourceError(f'maedong HTTP {exc.code}') from exc
    try:
        return parse(json.loads(raw),day)
    except (ValueError,UnicodeError) as exc:
        raise SourceError(f'invalid dated JSON: {exc}') from exc

def load_previous(dest,today):
    if not dest.exists():
        return {}
    try:
        obj=json.loads(dest.read_text(encoding='utf-8'))
        if obj.get('status')!='verified' or obj.get('source')!=SOURCE:
            return {}
        records={}
        for row in obj.get('history',[]):
            if not isinstance(row,dict):
                return {}
            d=date.fromisoformat(row['date'])
            if d>=today or row['date'] in records or parse({'date':row['date'],'breadth':{'up':row['up'],'down':row['down'],'unchanged':row['flat']}},d)['universe_total']!=row['universe_total']:
                return {}
            records[row['date']]=row
        return records
    except (ValueError,TypeError,KeyError,OSError):
        return {}

def weekdays_before(today,limit=48):
    """Only prior weekdays, never unfinalized intraday records."""
    day=today-timedelta(days=1)
    dates=[]
    while len(dates)<limit:
        if day.weekday()<5:
            dates.append(day)
        day-=timedelta(days=1)
    return dates

def validate_recent(rows,today):
    if len(rows)<20:
        raise SourceError(f'ADR20 needs >=20 actual days; collected {len(rows)}')
    last=date.fromisoformat(rows[-1]['date'])
    if (today-last).days>8:
        raise SourceError(f'latest market breadth stale: {last}')
    recent=rows[-20:]
    # Consecutive *observed* trading days, with a transparent gap sanity check.
    for a,b in zip(recent[:-1],recent[1:]):
        gap=(date.fromisoformat(b['date'])-date.fromisoformat(a['date'])).days
        if gap>8:
            raise SourceError(f'gap of {gap} calendar days in ADR20 window')
    numerator=sum(x['up'] for x in recent)
    denominator=sum(x['down'] for x in recent)
    if denominator<1:
        raise SourceError('ADR20 denominator zero')
    return {'start_date':recent[0]['date'],'end_date':recent[-1]['date'],
            'days':20,'up_sum':numerator,'down_sum':denominator,
            'value_pct':round(100*numerator/denominator,2)}



def preview_today_adr(rows, today, request, now=None):
    # Same-day Maedong breadth is provisional; never added to confirmed history.
    now=now or datetime.now(KST)
    if (now.date()!=today or today.weekday()>=5
        or (now.hour, now.minute)<(16, 15)):
        return None
    try:
        current=request(today)
    except (SourceError, urllib.error.URLError, TimeoutError, OSError) as exc:
        # Do not make a failed provisional fetch invalidate confirmed 20-day history.
        print('ADR20 provisional unavailable: '+str(exc)[:160],file=sys.stderr)
        return None
    if current is None:
        return None
    if current['date']!=today.isoformat():
        raise SourceError('Provisional trade date mismatch')
    if len(rows)<19 or rows[-1]['date']>=current['date']:
        return None
    recent=rows[-19:]+[current]
    for before,after in zip(recent[:-1],recent[1:]):
        if (date.fromisoformat(after['date'])-date.fromisoformat(before['date'])).days>8:
            return None
    up=sum(row['up'] for row in recent)
    down=sum(row['down'] for row in recent)
    if down<=0:
        return None
    return {
        'date':current['date'],'provisional':True,
        'up':current['up'],'down':current['down'],
        'flat':current['flat'],'universe_total':current['universe_total'],
        'start_date':recent[0]['date'], 'confirmed_through':rows[-1]['date'],
        'up_sum':up,'down_sum':down,'days':20,
        'value_pct':round(100*up/down,2),
        'note':'19 previously confirmed days + same-day provisional market breadth; may be revised'
    }

def run(dest=OUT,today=None,request=fetch_day,sleep=time.sleep):
    today=today or datetime.now(KST).date()
    previous=load_previous(dest,today)
    recent_dates=weekdays_before(today,limit=48)
    # Bootstrap: enough candidates for Korean exchange holidays. Incremental: fetch
    # only last 4 weekdays to recover delayed publication, instead of 20+ calls.
    to_fetch=recent_dates if len(previous)<20 else recent_dates[:5]
    missing=[d for d in to_fetch if d.isoformat() not in previous]
    latest_seen= max(previous) if previous else None
    errors=[]
    for i,day in enumerate(missing):
        try:
            row=request(day)
        except (SourceError,urllib.error.URLError,TimeoutError,OSError) as exc:
            if '429' in str(exc):
                raise
            errors.append(f'{day}: {type(exc).__name__}: {str(exc)[:90]}')
            row=None
        if row is not None:
            if row['date']!=day.isoformat():
                raise SourceError(f'requester returned wrong date {row["date"]}')
            previous[row['date']]=row
        # Keep below provider's 60 requests/minute; no burst or quota bypass.
        if i<len(missing)-1:
            sleep(1.25)
        if len(previous)>=20 and latest_seen is None and len(missing)>20:
            # On bootstrap, no need to query all 48 candidates once 25
            # actual dated rows are secured; 5-day buffer for public holidays.
            if len(previous)>=25:
                break
    rows=[previous[d] for d in sorted(previous)[-MAX_ARCHIVE:]]
    adr=validate_recent(rows,today)
    preview=preview_today_adr(rows,today,request)
    obj={'status':'verified','source':SOURCE,'source_url':URL,
         'market_scope':'KOSPI+KOSDAQ aggregate market breadth; as classified by provider',
         'source_data_quality':'prior-weekday dated observations; provisional current date excluded',
         'unit':'stocks','latest_date':rows[-1]['date'],'observations':len(rows),
         'adr20':adr,'history':rows,'provisional_adr20':preview,
         'collected_at_kst':datetime.now(KST).isoformat(),
         'notice':'Free public non-KRX source; the earliest/backfilled dates were not independently reconciled against KRX. Holidays absent, not zero-filled. No intraday provisional.',
         'skipped_or_invalid_dates':errors[-20:]}
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(tmp,dest)
    print(f'ADR20 VERIFIED source={SOURCE}, latest={obj["latest_date"]}, obs={len(rows)}, adr={adr["value_pct"]:.2f}, invalid={len(errors)}, provisional={preview["date"] if preview else "not_available"}')
    return obj

if __name__=='__main__':
    try:
        run()
    except Exception as exc:
        print('ADR20 COLLECTION FAILED (prior file preserved): '+type(exc).__name__+': '+str(exc),file=sys.stderr)
        raise SystemExit(1)
