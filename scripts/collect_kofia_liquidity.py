"""KOFIA FreeSIS public website daily investor cash & margin balances.

Bounded 70-calendar-day requests protect against HTTP 200 truncated JSON.
Errors, incompatible schema, denied access, inconsistent official anchor: fail closed.
No access-control bypass, no synthetic observations, no replacement of prior data on failure.
The endpoint is a public *website* JSON call, not the separately keyed official OpenAPI.
"""
from __future__ import annotations
import json,os,re,sys,time,urllib.request,urllib.error
from datetime import date,datetime,timedelta
from decimal import Decimal,InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'data'/'kr_kofia_liquidity.json'
URL='https://freesis.kofia.or.kr/meta/getMetaDataList.do'
SOURCE='KOFIA FreeSIS official statistics website (public read-only JSON)'
KST=ZoneInfo('Asia/Seoul')
SERVICES={'deposit':'STATSCU0100000060BO','credit':'STATSCU0100000070BO'}
ANCHOR_DATE='2026-10-29'
ANCHOR={'deposit_million_krw':88713283,'credit_million_krw':29088592}

class ValidationError(ValueError): pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def amount(x,label):
    if x is None or isinstance(x,bool): raise ValidationError(f'{label}: amount missing')
    s=str(x).strip().replace(',','')
    if not re.fullmatch(r'[+-]?\d+(?:\.0+)?',s): raise ValidationError(f'{label}: not an integral million KRW amount')
    try:
        n=Decimal(s)
        if not n.is_finite() or n!=n.to_integral_value(): raise ValidationError(f'{label}: amount not integral')
        return int(n)
    except InvalidOperation as e: raise ValidationError(f'{label}: invalid amount') from e

def parse_date(x,today):
    if not isinstance(x,str) or not re.fullmatch(r'\d{8}',x): raise ValidationError(f'invalid reported date {str(x)[:20]}')
    try:d=datetime.strptime(x,'%Y%m%d').date()
    except ValueError as e:raise ValidationError('invalid date') from e
    if d>today or d.weekday()>=5 or (today-d).days>460: raise ValidationError(f'out-of-range source date: {d}')
    return d.isoformat()

def parse_service(rows,service,today):
    if not isinstance(rows,list) or not rows: raise ValidationError(f'{service}: missing ds1 rows')
    result={}
    for row in rows:
        if not isinstance(row,dict): raise ValidationError(f'{service}: non-dict row')
        raw=row.get('TMPV1')
        if raw in ('합계','평균'): continue
        key=parse_date(str(raw) if raw is not None else raw,today)
        if key in result: raise ValidationError(f'{service}: duplicate date: {key}')
        main=amount(row.get('TMPV2'),f'{service}/{key}/TMPV2')
        if service=='deposit':
            if not 10_000_000<=main<=250_000_000:raise ValidationError(f'deposit {key}: implausible amount')
            result[key]={'deposit_million_krw':main}
        elif service=='credit':
            if not 1_000_000<=main<=120_000_000:raise ValidationError(f'credit {key}: implausible amount')
            out={'credit_million_krw':main}
            if row.get('TMPV3') is not None and row.get('TMPV4') is not None:
                a=amount(row['TMPV3'],f'{key}: credit KOSPI')
                b=amount(row['TMPV4'],f'{key}: credit KOSDAQ')
                if min(a,b)<0 or a+b>main+3:raise ValidationError(f'{key}: invalid credit split')
                out['credit_kospi_million_krw']=a
                out['credit_kosdaq_million_krw']=b
            result[key]=out
        else:raise ValidationError('unknown service')
    return result

def request_chunk(service,start,end,opener=None,sleeper=time.sleep):
    """Single limited data window; bounded retries on HTTP200 *truncated* JSON only."""
    if service not in SERVICES: raise ValidationError('unsupported service')
    payload={'dmSearch':{'tmpV40':'1000000','tmpV41':'1','tmpV1':'D',
             'tmpV45':start.strftime('%Y%m%d'),'tmpV46':end.strftime('%Y%m%d'),
             'OBJ_NM':SERVICES[service]}}
    body=json.dumps(payload,separators=(',',':')).encode('utf-8')
    req=urllib.request.Request(URL,data=body,method='POST',headers={
         'Content-Type':'application/json','Accept':'application/json',
         'Referer':'https://freesis.kofia.or.kr/',
         'User-Agent':'Mozilla/5.0 (compatible; MinerPersonalResearch/1.0)'})
    opener=opener or urllib.request.build_opener(NoRedirect())
    for trial in range(1,4):
        try:
            with opener.open(req,timeout=25) as response:
                status=response.status
                kind=response.headers.get('Content-Type','')
                raw=response.read(800_001)
            if status!=200 or 'json' not in kind.lower() or len(raw)>800_000:
                raise ValidationError(f'{service}/{start}:{end}: unexpected status, content type or size: {status}, {kind}, {len(raw)}')
            if not raw.strip().startswith(b'{'):
                raise ValidationError(f'{service}/{start}:{end}: non-JSON body despite JSON header')
            if not raw.rstrip().endswith(b'}'):
                raise ValueError(f'incomplete JSON body ({len(raw)} bytes; not ending with closing brace)')
            parsed=json.loads(raw.decode('utf-8'))
            if not isinstance(parsed,dict) or not isinstance(parsed.get('ds1'),list):
                raise ValidationError(f'{service}/{start}:{end}: unexpected JSON schema')
            print(f'KOFIA {service} {start}..{end} rows={len(parsed["ds1"])} bytes={len(raw)}',flush=True)
            return parsed['ds1']
        except urllib.error.HTTPError as e:
            # Access controls (especially 403 and 429) are never retried or bypassed.
            raise ValidationError(f'{service}/{start}:{end}: HTTP {e.code}, stop; no bypass') from e
        except (UnicodeError,json.JSONDecodeError,ValueError) as e:
            if trial>=3: raise ValidationError(f'{service}/{start}:{end}: malformed/truncated JSON after {trial} bounded attempts: {str(e)[:160]}') from e
            print(f'KOFIA {service} {start}..{end} partial response; bounded retry {trial}/2: {str(e)[:90]}',flush=True)
            sleeper(1.5*trial)
    raise AssertionError('unreachable')

def retrieve_service(service,start,end,request=request_chunk,pause=time.sleep):
    """Fetch 70-day inclusive windows, then cross-check overlapping dates and totals."""
    combined={}
    cur=start
    while cur<=end:
        chunk_end=min(end,cur+timedelta(days=69))
        rows=request(service,cur,chunk_end)
        for r in rows:
            if not isinstance(r,dict):raise ValidationError('non-object source row')
            raw=str(r.get('TMPV1',''))
            if raw in ('합계','평균'):continue
            day=datetime.strptime(raw,'%Y%m%d').date() if re.fullmatch(r'\d{8}',raw) else None
            if day is None or not(cur<=day<=chunk_end):raise ValidationError(f'{service}: out-of-window or invalid source date: {raw}')
            if raw in combined:raise ValidationError(f'{service}: duplicate source date: {raw}')
            combined[raw]=r
        cur=chunk_end+timedelta(days=1)
        if cur<=end:pause(1.1)
    return list(combined.values())

def assemble(deposits,credits,previous,today):
    if min(len(deposits),len(credits))<60: raise ValidationError('official source returned <60 dates for one series')
    common=sorted(set(deposits)&set(credits))
    if len(common)<60:raise ValidationError(f'official date overlap too small: {len(common)}')
    if (today-date.fromisoformat(common[-1])).days>10:raise ValidationError(f'stale official source latest={common[-1]}')
    if abs((date.fromisoformat(max(deposits))-date.fromisoformat(max(credits))).days)>5:
        raise ValidationError('deposit and credit latest days differ >5 days')
    history={}
    if isinstance(previous,dict) and previous.get('status')=='official_source_validated' and previous.get('source')==SOURCE:
        for row in previous.get('history',[]):
            try:
                key=row['date']
                if date.fromisoformat(key)>today:continue
                if all(type(row.get(k)) is int and row[k]>0 for k in ANCHOR):history[key]=row
            except (ValueError,KeyError,TypeError):pass
    for day in common:history[day]={'date':day,**deposits[day],**credits[day]}
    ordered=[history[d] for d in sorted(history)[-280:]]
    if ordered[-1]['date']!=common[-1]:raise ValidationError('merged source latest date conflict')
    # Historical fixed published homepage anchor (date-and-value match).
    matching=next((r for r in ordered if r['date']==ANCHOR_DATE),None)
    if matching is not None:
        for key,expected in ANCHOR.items():
            if abs(matching[key]-expected)>1:raise ValidationError(f'KOFIA homepage anchor mismatch: {key}')
    elif date.fromisoformat(ANCHOR_DATE)<=today<=date.fromisoformat(ANCHOR_DATE)+timedelta(days=90):
        raise ValidationError('recent official reference date missing')
    return {
        'status':'official_source_validated','source':SOURCE,
        'source_url':'https://freesis.kofia.or.kr/stat/main.do',
        'data_access_url':URL,
        'data_access_method':'Public website JSON, not the separate approved-key KOFIA OpenAPI',
        'unit':'KRW_million','unit_confirmed_from':'FreeSIS official public homepage: 백만원',
        'credit_definition':'신용거래융자 전체 (KOSPI/KOSDAQ market total from FreeSIS credit balance screen)',
        'deposit_definition':'투자자예탁금 (장내파생상품 거래예수금 포함)',
        'latest_date':ordered[-1]['date'],'observations':len(ordered),
        'collected_at_kst':datetime.now(KST).isoformat(),
        'history':ordered,
        'note':'Official published balances, not real-time flows. Compare Npay on matching dates only; no synthetic data.'}

def run(dest=DEST,today=None,request=request_chunk):
    today=today or datetime.now(KST).date()
    try:previous=json.loads(dest.read_text(encoding='utf-8'))
    except (OSError,ValueError):previous=None
    # First pass requests enough history for 60-day indicator, subsequent passes update last 110 days.
    start=today-timedelta(days=110 if isinstance(previous,dict) and previous.get('status')=='official_source_validated' and len(previous.get('history',[]))>=60 else 405)
    dep=parse_service(retrieve_service('deposit',start,today,request=request), 'deposit', today)
    cred=parse_service(retrieve_service('credit',start,today,request=request), 'credit', today)
    output=assemble(dep,cred,previous,today)
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(tmp,dest)
    latest=output['history'][-1]
    print(f'KOFIA official validated latest={output["latest_date"]} n={len(output["history"])} deposit_million={latest["deposit_million_krw"]} credit_million={latest["credit_million_krw"]}')
    return output

if __name__=='__main__':
    try: run()
    except Exception as e:
        print(f'KOFIA official collection FAILED: {type(e).__name__}: {e} (prior verified file preserved)',file=sys.stderr)
        sys.exit(1)
