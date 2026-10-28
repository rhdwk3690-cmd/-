"""KR EOD ranking collector. No fabricated investor flows or price dates."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parents[1] / 'data' / 'kr_flow.json'
KST = ZoneInfo('Asia/Seoul')


def number(value):
    if value is None: return 0
    return int(float(str(value).replace(',', '').replace(' ', '') or 0))


def valid_code(s):
    return len(s) == 6 and s.isdigit()


def official(day, key):
    import requests
    rows = []
    for typ, market in [('stk_bydd_trd', 'KOSPI'), ('ksq_bydd_trd', 'KOSDAQ')]:
        url = f'https://data-dbg.krx.co.kr/svc/apis/sto/{typ}'
        resp = requests.get(url, headers={'AUTH_KEY':key, 'User-Agent':'MinerResearch/1.0'}, params={'basDd':day}, timeout=25)
        resp.raise_for_status()
        payload = resp.json()
        content = payload.get('OutBlock_1', [])
        if not isinstance(content, list): raise ValueError(f'{typ}: unexpected response')
        for x in content:
            code = str(x.get('ISU_SRT_CD') or x.get('ISU_CD') or '').strip()
            # ISU_CD sometimes a 12-character ISIN; short-code is needed for a reliable join.
            if not valid_code(code): continue
            val = number(x.get('ACC_TRDVAL'))
            if val <= 0: continue
            rows.append({'ticker':code, 'name':str(x.get('ISU_NM','')), 'market':market,
                         'close':number(x.get('TDD_CLSPRC')), 'traded_krw':val,
                         'foreign_net_krw':None, 'institution_net_krw':None})
    if len(rows) < 200: raise ValueError(f'official KRX: only {len(rows)} usable rows')
    return rows


def finance_data_reader():
    import FinanceDataReader as fdr
    import pandas as pd
    df = fdr.StockListing('KRX-MARCAP')
    needed = {'Code','Name','Amount','Close'}
    if df is None or df.empty or not needed.issubset(df.columns):
        raise ValueError('KRX-MARCAP missing required columns')
    rows = []
    for _, x in df.iterrows():
        code = str(x['Code']).strip().zfill(6)
        if not valid_code(code): continue
        market = str(x.get('MarketId', x.get('Market', 'UNKNOWN'))).upper()
        if market in ('STK', 'KOSPI', 'KS'): market='KOSPI'
        elif market in ('KSQ','KOSDAQ','KQ'): market='KOSDAQ'
        else: continue  # Exclude unverified market types, ETFs and ETNs.
        value = pd.to_numeric(x['Amount'], errors='coerce')
        close = pd.to_numeric(x['Close'], errors='coerce')
        if pd.isna(value) or value <= 0 or pd.isna(close): continue
        rows.append({'ticker':code,'name':str(x['Name']),'market':market,'close':int(close),
                     'traded_krw':int(value),'foreign_net_krw':None,'institution_net_krw':None})
    if len(rows)<200: raise ValueError(f'FDR: {len(rows)} valid KOSPI/KOSDAQ rows')
    return rows


def main():
    now = datetime.now(timezone.utc)
    output={'collected_at_kst':now.astimezone(KST).isoformat(), 'status':'unavailable',
            'source':'none', 'date':None, 'top200':[], 'market_flows':{}, 'errors':[],
            'notice':'외국인·기관 수급 미제공. 거래대금 순위는 실시간이 아니며 수집일과 시세 기준일이 다를 수 있습니다.'}
    key=os.getenv('KRX_API_KEY','').strip()
    if key:
        today=now.astimezone(KST).date()
        for lag in range(8):
            day=(today-timedelta(days=lag)).strftime('%Y%m%d')
            try:
                rows=official(day,key)
                output.update(status='partial',source='KRX Open API (authenticated EOD)',
                              date=f'{day[:4]}-{day[4:6]}-{day[6:]}',
                              top200=sorted(rows,key=lambda x:x['traded_krw'],reverse=True)[:200])
                break
            except Exception as exc:
                output['errors'].append(f'KRX {day}: {type(exc).__name__}: {str(exc)[:130]}')
    else:
        output['errors'].append('KRX_API_KEY not configured; official market close feed unavailable.')
    if not output['top200']:
        try:
            rows=finance_data_reader()
            output.update(status='partial',source='FinanceDataReader KRX-MARCAP (unverified trading date)',
                          date=None,top200=sorted(rows,key=lambda x:x['traded_krw'],reverse=True)[:200])
            output['errors'].append('FinanceDataReader response does not reliably identify trading date; date deliberately blank.')
        except Exception as exc:
            output['errors'].append(f'FinanceDataReader: {type(exc).__name__}: {str(exc)[:160]}')
    # Always write a diagnostic file, but make actual unavailable results explicit.
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"status={output['status']} rows={len(output['top200'])} source={output['source']} date={output['date']}")
    for err in output['errors'][-10:]: print('INFO:',err)
    if not output['top200']: raise RuntimeError('No TOP200 data from either provider. See diagnostic data/kr_flow.json')

if __name__=='__main__': main()
