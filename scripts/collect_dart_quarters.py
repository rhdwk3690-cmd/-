"""Dated official OpenDART quarterly profitability for Miner Terminal.

No intraday API calls in Streamlit. Per-run batch eventually covers the entire
saved TOP200 universe. Data is from CURRENT OpenDART financial API, which may
reflect later restatements: NOT a point-in-time historical backtest dataset.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import datetime, date
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
TOP_FILE = ROOT / "data" / "kr_flow.json"
OUTPUT = ROOT / "data" / "kr_dart_quarters.json"
KST = ZoneInfo('Asia/Seoul')
API = 'https://opendart.fss.or.kr/api'
REPORT_CODES = {1:'11013', 2:'11012', 3:'11014', 4:'11011'}
SALES_IDS = {'ifrs-full_Revenue','ifrs_Revenue','ifrs-full_RevenueFromContractsWithCustomers','ifrs_RevenueFromContractsWithCustomers'}
OP_IDS = {'dart_OperatingIncomeLoss','ifrs-full_ProfitLossFromOperatingActivities','ifrs_ProfitLossFromOperatingActivities'}
SALES_NAMES = {'매출액','매출','수익(매출액)','영업수익','수익'}
OP_NAMES = {'영업이익','영업이익(손실)','영업손익'}
ERROR_CODES = {'010','011','012','020','021','100','101','800','900','901'}


def amount(v):
    t = str(v if v is not None else '').replace(',','').strip()
    if re.fullmatch(r'\([0-9]+\)', t): return -int(t[1:-1])
    if re.fullmatch(r'-?[0-9]+', t): return int(t)
    return None


def report_key(r):
    """Original statutory report only; use original receipt date."""
    title = str(r.get('report_nm') or '').strip()
    m = re.match(r'^(분기보고서|반기보고서|사업보고서)\s*\(\s*(20\d\d)\s*[./-]\s*(0?[0-9]|1[0-2])\s*\)', title)
    if not m: return None
    kind, year, month = m.group(1), int(m.group(2)), int(m.group(3))
    if (kind, month) not in {('분기보고서',3),('반기보고서',6),('분기보고서',9),('사업보고서',12)}: return None
    received, no = str(r.get('rcept_dt','')), str(r.get('rcept_no',''))
    if not re.fullmatch(r'20\d{6}',received) or not re.fullmatch(r'\d{14}',no): return None
    try: receipt = date.fromisoformat(f'{received[:4]}-{received[4:6]}-{received[6:]}')
    except ValueError: return None
    return {'year':year,'quarter':month//3,'filed':receipt.isoformat(),'receipt':no,'title':title}


def choose_account(rows, ids, names, value_key):
    for statement in ('IS','CIS'):
        subset = [x for x in rows if x.get('sj_div') == statement]
        for key in ('account_id','account_nm'):
            options = [x for x in subset if (x.get('account_id') in ids if key=='account_id' else str(x.get('account_nm','')).strip() in names)]
            vals = [amount(x.get(value_key)) for x in options]
            valid = [x for x in vals if x is not None]
            if valid and len(set(valid)) == 1: return valid[0]
            if len(set(valid)) > 1: return None
    return None


def pick_financials(rows, q):
    """Same quarter only; never mistake Q2/Q3 accumulated 6/9M as 3M."""
    if not rows: return None
    r = choose_account(rows, SALES_IDS, SALES_NAMES, 'thstrm_amount')
    o = choose_account(rows, OP_IDS, OP_NAMES, 'thstrm_amount')
    if r is None or o is None or r <= 0: return None
    if q < 4:
        yr = choose_account(rows, SALES_IDS, SALES_NAMES, 'frmtrm_q_amount')
        yo = choose_account(rows, OP_IDS, OP_NAMES, 'frmtrm_q_amount')
        # Previous-year quarter can be missing: keep the latest 3M observation but no YoY.
        prior = (yr, yo) if yr is not None and yo is not None and yr > 0 else None
        return {'current':(r,o),'prior_year':prior}
    # Annual report is FY, NOT Q4. Q4 needs subtracting Q3 YTD separately.
    return {'annual':(r,o),'prior_year_annual':(
        choose_account(rows, SALES_IDS, SALES_NAMES, 'frmtrm_amount'),
        choose_account(rows, OP_IDS, OP_NAMES, 'frmtrm_amount'))}


def derive_q4(fy_rows, q3_rows):
    fy = pick_financials(fy_rows,4)
    if not fy or not q3_rows: return None
    rev9 = choose_account(q3_rows, SALES_IDS, SALES_NAMES, 'thstrm_add_amount')
    op9 = choose_account(q3_rows, OP_IDS, OP_NAMES, 'thstrm_add_amount')
    if rev9 is None or op9 is None: return None
    r,o = fy['annual'][0]-rev9, fy['annual'][1]-op9
    if r<=0:return None
    # Prior-year Q4 needs last-year annual minus prior-year 9M; not always available.
    return (r,o)


def growth(now, old):
    if now is None or old is None or old <= 0: return None
    return round((now/old - 1)*100, 2)


def operating_growth(now, old):
    if now is None or old is None: return (None, '미확인')
    if old<=0 and now>0: return (None, '흑자전환')
    if old>0 and now<=0: return (None, '적자전환')
    if old<0 and now<0: return (None, '적자지속')
    if old==0: return (None, '기저 0')
    return (round((now/old-1)*100,2), '증가' if now>old else '감소' if now<old else '보합')


def build_metrics(current, yoy, qoq):
    r,o=current
    yr,yo=yoy if yoy is not None else (None,None)
    pr,po=qoq if qoq is not None else (None,None)
    yoy_op,yoy_status=operating_growth(o,yo)
    qoq_op,qoq_status=operating_growth(o,po)
    def margin(x,y): return round(x/y*100,2) if x is not None and y and y>0 else None
    m=margin(o,r); my=margin(yo,yr); mp=margin(po,pr)
    return {
        'sales_krw':r,'operating_income_krw':o,'margin_pct':m,
        'revenue_yoy_pct':growth(r,yr),'revenue_qoq_pct':growth(r,pr),
        'op_yoy_pct':yoy_op,'op_yoy_status':yoy_status,
        'op_qoq_pct':qoq_op,'op_qoq_status':qoq_status,
        'margin_yoy_pp':round(m-my,2) if my is not None else None,
        'margin_qoq_pp':round(m-mp,2) if mp is not None else None,
        'yoy_base_available':yoy is not None,'qoq_base_available':qoq is not None
    }


class Dart:
    def __init__(self,key):
        if not re.fullmatch('[A-Za-z0-9]{40}',key or ''): raise RuntimeError('DART_API_KEY GitHub Secret 확인 필요 (40자리)')
        self.s=requests.Session()
        self.key=key
        self.calls=0
        self.cache={}

    def get(self, endpoint, **params):
        ref=(endpoint,tuple(sorted(params.items())))
        if ref in self.cache:return self.cache[ref]
        for attempt in range(3):
            try:
                resp=self.s.get(f'{API}/{endpoint}',params={'crtfc_key':self.key,**params},timeout=(10,40))
                resp.raise_for_status()
                out=resp.json()
                self.calls+=1
                status=str(out.get('status',''))
                if status in ERROR_CODES: raise RuntimeError(f'OpenDART API status={status}: {str(out.get("message",""))[:70]}')
                if status not in ('000','013','014'): raise RuntimeError(f'예상하지 못한 DART 응답 코드 {status}')
                self.cache[ref]=out
                time.sleep(.13)
                return out
            except requests.RequestException as e:
                if attempt==2: raise RuntimeError(f'DART 요청 오류: {type(e).__name__}') from e
                time.sleep(1+attempt)
        raise RuntimeError('unreachable')

    def get_corp_map(self):
        r=self.s.get(f'{API}/corpCode.xml',params={'crtfc_key':self.key},timeout=(12,90));r.raise_for_status()
        if not zipfile.is_zipfile(io.BytesIO(r.content)): raise RuntimeError('DART 고유번호 ZIP 수신 실패')
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            root=ET.fromstring(z.read(next(n for n in z.namelist() if n.lower().endswith('.xml'))))
        mapping={};names={};amb=set()
        for item in root.findall('.//list'):
            ticker=(item.findtext('stock_code') or '').strip()
            corp=(item.findtext('corp_code') or '').strip()
            if re.fullmatch(r'\d{6}',ticker) and re.fullmatch(r'\d{8}',corp):
                if ticker in mapping and mapping[ticker]!=corp:amb.add(ticker)
                mapping[ticker]=corp; names[ticker]=(item.findtext('corp_name') or '').strip()
        for t in amb:mapping.pop(t,None)
        return mapping,names

    def reports(self,corp,today):
        result=[]
        begin=f'{today.year-2}0101'
        for page in range(1,7):
            j=self.get('list.json',corp_code=corp,bgn_de=begin,end_de=today.strftime('%Y%m%d'),
                       pblntf_ty='A',page_no=str(page),page_count='100',last_reprt_at='N')
            if j['status'] in ('013','014'):break
            for row in j.get('list',[]):
                info=report_key(row)
                if info and info['filed']<=today.isoformat():result.append(info)
            if page*100>=int(j.get('total_count') or len(j.get('list',[]))):break
        first={}
        for r in result:
            key=(r['year'],r['quarter'])
            if key not in first or (r['filed'],r['receipt'])<(first[key]['filed'],first[key]['receipt']):first[key]=r
        return first

    def fs(self,corp,year,quarter,preferred):
        ref=(corp,year,quarter,preferred)
        if ref in self.cache:return self.cache[ref]
        j=self.get('fnlttSinglAcntAll.json',corp_code=corp,bsns_year=str(year),
                   reprt_code=REPORT_CODES[quarter],fs_div=preferred)
        rows=j.get('list') or [] if j.get('status')=='000' else []
        self.cache[ref]=rows
        return rows


def prev_key(year,quarter):
    return (year,quarter-1) if quarter>1 else (year-1,4)


def single_company(dart,corp,code,name,today):
    reports=dart.reports(corp,today)
    if not reports:return {'status':'no_original_filing','name':name,'code':code}
    latest_year,latest_q=max(reports)
    report=reports[(latest_year,latest_q)]
    prev_year,prev_q=prev_key(latest_year,latest_q)
    def extract(fs):
        def read(y,q):
            if (y,q) not in reports:return None
            return dart.fs(corp,y,q,fs)
        if latest_q==4:
            q3=read(latest_year,3)
            val=derive_q4(read(latest_year,4),q3)
            if val is None:return None
            py=derive_q4(read(latest_year-1,4), read(latest_year-1,3))
        else:
            data=pick_financials(read(latest_year,latest_q),latest_q)
            if data is None:return None
            val=data['current'];py=data['prior_year']
        if prev_q==4: pre=derive_q4(read(prev_year,4),read(prev_year,3))
        else:
            pdata=pick_financials(read(prev_year,prev_q),prev_q)
            pre=pdata['current'] if pdata else None
        return val,py,pre
    # All comparisons from the same consolidated (or separate) scope.
    for fs in ('CFS','OFS'):
        res=extract(fs)
        if res:
            current,yoy,qoq=res
            metrics=build_metrics(current,yoy,qoq)
            return {'status':'ok' if metrics['yoy_base_available'] and metrics['qoq_base_available'] else 'partial',
                    'code':code,'name':name,'period':f'{latest_year}Q{latest_q}',
                    'filing_date':report['filed'],'receipt':report['receipt'],
                    'dart_link':f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={report["receipt"]}',
                    'fs_div':fs,**metrics,'checked_at':datetime.now(KST).isoformat()}
    return {'status':'missing_financials','name':name,'code':code,'period':f'{latest_year}Q{latest_q}',
            'filing_date':report['filed'],'checked_at':datetime.now(KST).isoformat()}


def load_top200():
    data=json.loads(TOP_FILE.read_text(encoding='utf-8'))
    if data.get('status')!='verified' or len(data.get('top200',[]))!=200:
        raise ValueError('TOP200 검증 파일을 읽을 수 없음')
    return {str(item['ticker']):item['name'] for item in data['top200'] if re.fullmatch(r'\d{6}',str(item.get('ticker','')))}


def main():
    today=datetime.now(KST).date()
    top=load_top200()
    old={}
    if OUTPUT.exists():
        src=json.loads(OUTPUT.read_text(encoding='utf-8'))
        if src.get('source')=='OpenDART official periodic financial statements':
            old=src.get('rows') or {}
    manu=[x.strip() for x in os.environ.get('STOCK_CODES','').split(',') if x.strip()]
    if manu:
        if len(manu)>40 or any(not re.fullmatch(r'\d{6}',x) for x in manu):raise ValueError('STOCK_CODES에는 6자리 종목코드 최대 40개 입력')
        selection=list(dict.fromkeys(manu))
    else:
        # The 40 is a *daily batch size*, NOT a universe cap. Rotate across all TOP200.
        priority=['005930','000660','009150','000150']
        candidate=list(dict.fromkeys([c for c in priority if c in top]+list(top)))
        candidate.sort(key=lambda c:(str(old.get(c,{}).get('checked_at','')), 0 if c in priority else 1))
        selection=candidate[:40]
    dart=Dart(os.environ.get('DART_API_KEY',''))
    corp_map, names = dart.get_corp_map()
    rows=old.copy();errors={};done=0
    for code in selection:
        name=top.get(code) or names.get(code) or code
        corp=corp_map.get(code)
        if not corp:
            rows[code]={'status':'no_corp_code','name':name,'code':code,'checked_at':datetime.now(KST).isoformat()}
            continue
        try:
            rows[code]=single_company(dart,corp,code,name,today)
            done+=1
        except Exception as exc:
            # Retain prior validated data instead of pretending missing/failed is a zero.
            errors[code]=f'{type(exc).__name__}: {str(exc)[:75]}'
            print(f'{code}: failed to refresh ({type(exc).__name__})',flush=True)
    if not done:raise RuntimeError('이번 실행에서 신규 재무자료 확인 성공 종목 0건; 기존 자료 유지')
    result={'source':'OpenDART official periodic financial statements','collected_at_kst':datetime.now(KST).isoformat(),
            'data_quality':'current_endpoint_may_reflect_restatements_not_point_in_time','target_universe':'saved TOP200',
            'universe_asof':json.loads(TOP_FILE.read_text(encoding='utf-8'))['date'],
            'coverage':{'in_top200':sum(x in rows for x in top),'universe':len(top),'latest_batch_count':len(selection),
                        'last_successes':done,'last_failures':len(errors),'api_calls':dart.calls},
            'notes':'Current OpenDART APIs may include later restatements. Original statutory filing date recorded, but not audited PIT. Fiscal Q4 = audited FY - Q3 YTD; separate financial statement scope not mixed with consolidated. Missing values stay null.',
            'rows':rows}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('DART quarter batch:',result['coverage'],'failed codes:',list(errors))


def selftest():
    q=[{'sj_div':'IS','account_id':'ifrs-full_Revenue','account_nm':'매출액',
         'thstrm_amount':'200','frmtrm_q_amount':'100','thstrm_add_amount':'530'},
       {'sj_div':'IS','account_id':'dart_OperatingIncomeLoss','account_nm':'영업이익',
         'thstrm_amount':'40','frmtrm_q_amount':'10','thstrm_add_amount':'95'}]
    assert pick_financials(q,3)=={'current':(200,40),'prior_year':(100,10)}
    annual=[{**q[0],'thstrm_amount':'800'}, {**q[1],'thstrm_amount':'130'}]
    assert derive_q4(annual,q)==(270,35)
    m=build_metrics((200,40),(100,10),(150,20))
    assert m['revenue_yoy_pct']==100 and m['revenue_qoq_pct']==33.33
    assert m['margin_yoy_pp']==10 and m['margin_qoq_pp']==6.67
    v=build_metrics((180,20),(120,-5),(200,25))
    assert v['op_yoy_pct'] is None and v['op_yoy_status']=='흑자전환'
    assert report_key({'report_nm':'정정분기보고서 (2026.09)','rcept_dt':'20261103','rcept_no':'20261103000001'}) is None
    assert prev_key(2026,1)==(2025,4)
    print('SELFTEST PASS: YoY and QoQ, Q4 derive, negative base, original filing dates')


if __name__=='__main__':
    if '--selftest' in sys.argv:selftest()
    else:main()
