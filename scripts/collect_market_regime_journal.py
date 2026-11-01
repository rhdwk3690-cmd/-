"""As-observed market-environment daily journal; supplemental EOD stage.

Loads SAME Yahoo close and date-matched Npay index volume as the Streamlit app.
Executes the EXACT current `oneil_market_state` and DD helper definitions taken
from app.py (without importing/rendering app.py), then market_signal_qa independent
replay and `market_regime.classify_environment`. Never fabricate earlier labels.
"""
from __future__ import annotations
import ast
import json
import math
import os
from pathlib import Path
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'data'/'kr_market_regime_journal.json'
KST=ZoneInfo('Asia/Seoul')
TICKERS={'KOSPI':'^KS11','KOSDAQ':'^KQ11'}


def load_index(ticker):
    import pandas as pd
    import yfinance as yf
    raw=yf.download(ticker,period='3y',interval='1d',auto_adjust=False,
                    progress=False,threads=False)
    if raw is None or raw.empty:
        raise ValueError(f'{ticker}: no Yahoo index bars')
    if isinstance(raw.columns,pd.MultiIndex):
        raw.columns=raw.columns.get_level_values(0)
    if not {'Close','Low','Volume'}.issubset(raw.columns):
        raise ValueError(f'{ticker}: missing Close/Low/Volume')
    frame=raw.copy()
    frame.index=pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    frame=frame[~frame.index.duplicated(keep='last')].sort_index()
    for col in ('Close','Low','Volume'):
        frame[col]=pd.to_numeric(frame[col],errors='coerce')
    frame=frame.dropna(subset=['Close'])
    frame=frame[frame['Close']>0]
    if len(frame)<205:
        raise ValueError(f'{ticker}: less than 205 closing observations')
    return frame


def index_volume(frame, ticker):
    import numpy as np
    from miner_volume import _miner_naver_volume
    frame=frame.copy()
    frame['Volume']=float('nan')
    matched,source=_miner_naver_volume(ticker,frame)
    for d,(volume,low) in matched.items():
        frame.at[d,'Volume']=volume
        if np.isfinite(low) and low>0:
            frame.at[d,'Low']=low
    frame.attrs['index_volume_source']=source
    frame.attrs['index_volume_matched']=len(matched)
    print(f'{ticker}: {source}, date/close matched Npay index-volume days={len(matched)}',flush=True)
    return frame


def current_engine():
    """Extract deployed pure definitions; fail if changed/ambiguous instead of drifting."""
    import numpy as np
    import pandas as pd
    path=ROOT/'app.py'
    tree=ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
    gain=[n for n in tree.body if isinstance(n,ast.Assign)
          and any(isinstance(t,ast.Name) and t.id=='ONEIL_FTD_GAIN' for t in n.targets)]
    dd=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_oneil_dd_asof']
    state=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='oneil_market_state']
    if len(gain)!=1 or len(dd)!=1 or not state:
        raise ValueError('deployed app market engine definitions changed')
    threshold=ast.literal_eval(gain[0].value)
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not 0.005<=threshold<=0.025:
        raise ValueError('unsupported FTD threshold')
    # Actual installed app uses the last definition, wrapped by miner_volume.install.
    chosen=state[-1]
    needed={'_oneil_dd_asof','signal_volume_ok','ONEIL_FTD_GAIN'}
    referenced={n.id for n in ast.walk(chosen) if isinstance(n,ast.Name)}
    if not needed.issubset(referenced):
        raise ValueError('deployed engine API no longer compatible')
    def original_volume_ok(df):
        if not {'Close','Low','Volume'}.issubset(df.columns) or len(df)<205:
            return False
        t=df[['Close','Low','Volume']].tail(260).apply(pd.to_numeric,errors='coerce')
        return bool(t.notna().all().all() and (t>0).all().all())
    node=ast.Module(body=[dd[0],chosen],type_ignores=[])
    ast.fix_missing_locations(node)
    ns={'pd':pd,'np':np,'ONEIL_FTD_GAIN':float(threshold),
        'signal_volume_ok':original_volume_ok}
    exec(compile(node,str(path),'exec'),ns,ns)
    fn=ns['oneil_market_state']
    def wrapped(frame):
        import pandas as pd
        empty=dict(status='판정 보류',day1=None,rally_days=0,ftd=None,dd=[],events=[],reason='')
        if len(frame)<80:
            empty['reason']='지수 일봉 80거래일 미만';return empty
        valid=frame[['Close','Low','Volume']].apply(pd.to_numeric,errors='coerce')
        valid=valid.notna().all(axis=1)&(valid>0).all(axis=1)
        if not bool(valid.iloc[-1]):
            empty['reason']='최신 거래일 거래량 미확인';return empty
        good=0
        for it in valid.iloc[::-1]:
            if not bool(it):break
            good+=1
        if good<80:
            empty['reason']=f'최근 연속 유효 거래량 {good}일';return empty
        clean=frame.tail(min(good,260)).copy()
        return fn(clean)
    return wrapped


def snapshot_flags(frame):
    close=frame['Close']
    if len(close)<205:
        raise ValueError('MA200 requires >=205 actual index observations')
    c=float(close.iloc[-1]);m20=float(close.tail(20).mean())
    m50=float(close.tail(50).mean());m200=float(close.tail(200).mean())
    return [bool(c>m20),bool(m20>m50),bool(c>m200),bool(m50>m200)]


def to_prices(frame):
    return [{'date':d.strftime('%Y-%m-%d'),'close':float(v)} for d,v in frame['Close'].items()]


def run():
    from market_regime_journal import record_journal
    from market_regime import classify_environment, RULE_VERSION
    from market_signal_qa import assess_market_signal
    now=datetime.now(KST)
    frames={name:index_volume(load_index(ticker),ticker) for name,ticker in TICKERS.items()}
    prices={name:to_prices(frame) for name,frame in frames.items()}
    dates={name:frame.index[-1].strftime('%Y-%m-%d') for name,frame in frames.items()}
    signal=None
    if len(set(dates.values()))!=1:
        print(f'INDEX DATE MISMATCH; no new market label: {dates}',flush=True)
    else:
        day=next(iter(dates.values()))
        engine=current_engine()
        states={name:{'date':frame.index[-1],'flags':snapshot_flags(frame)}
                for name,frame in frames.items()}
        qa={name:assess_market_signal(frame,engine,now=now)
            for name,frame in frames.items()}
        try:
            adr=json.loads((ROOT/'data'/'kr_market_adr20.json').read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError):
            adr=None
        result=classify_environment(states,qa,adr,today=now.date())
        signal={
            'date':day,'code':result['code'],'environment':result['status'],
            'rule_version':RULE_VERSION,
            'price_flags':result['price_flags'],'dd_counts':result['dd_counts'],
            'ftd_count':result['ftd_count'],
            'adr20_date':result['adr20']['date'] if result['adr20'] else None,
            'adr20_value':result['adr20']['value'] if result['adr20'] else None,
            'reasons':result['reasons'],
            'index_close':{name:float(frame['Close'].iloc[-1]) for name,frame in frames.items()},
            'qa':{name:{key:qa[name].get(key) for key in ('status','reason','date','dd_count','ftd','market_status','source','matched')}
                  for name in frames},
            'source_date_verified':dates,
        }
        print(f'NEW OBSERVED LABEL {day}: {signal["code"]} / {signal["environment"]}',flush=True)
        if result['code']=='withheld':
            print('Classification withheld: '+'; '.join(result['reasons']),flush=True)
    old=None
    if OUT.exists():
        old=json.loads(OUT.read_text(encoding='utf-8'))
    current=record_journal(old,incoming_prices=prices,signal=signal,
                           observed_at=now.isoformat(),through=now.date())
    if current==old:
        print('JOURNAL UNCHANGED — no new signal or matured outcome',flush=True)
        return current
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(current,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(tmp,OUT)
    matured=sum(1 for r in current['records'] for x in r['forward'].values() if x['status']=='mature')
    print(f'JOURNAL VERIFIED AND STORED records={len(current["records"])} maturity_windows={matured} last={current["records"][-1]["date"] if current["records"] else "none"}',flush=True)
    return current


if __name__=='__main__':
    try:run()
    except Exception as exc:
        print(f'MARKET REGIME JOURNAL FAILED; previous file preserved: {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)
