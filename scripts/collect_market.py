"""Free delayed market snapshot experiment; not streaming or official real-time data."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

TICKERS = {"KOSPI":"^KS11","KOSDAQ":"^KQ11","S&P500":"^GSPC","NASDAQ":"^IXIC","USD/KRW":"KRW=X","WTI":"CL=F","BRENT":"BZ=F","US10Y":"^TNX","VIX":"^VIX"}
OUTPUT=Path(__file__).resolve().parents[1] / 'data' / 'market_snapshot.json'

def main():
    now=datetime.now(timezone.utc)
    records={}
    for name,ticker in TICKERS.items():
        try:
            frame=yf.download(ticker,period='10d',interval='1d',progress=False,auto_adjust=False,threads=False)
            if isinstance(frame.columns,pd.MultiIndex): frame.columns=frame.columns.get_level_values(0)
            close=pd.to_numeric(frame['Close'],errors='coerce').dropna()
            if len(close)<2: raise ValueError('less than two valid closes')
            dt=pd.Timestamp(close.index[-1]); date=dt.strftime('%Y-%m-%d')
            records[name]={"ticker":ticker,"price":round(float(close.iloc[-1]),5),"change_pct":round(float((close.iloc[-1]/close.iloc[-2]-1)*100),3),"price_date":date,"source":"Yahoo Finance (daily close)","status":"daily_close"}
        except Exception as exc:
            records[name]={"ticker":ticker,"status":"error","error":str(exc)[:180]}
    data={"collected_at_utc":now.isoformat(),"collected_at_kst":now.astimezone(ZoneInfo('Asia/Seoul')).isoformat(),"markets":records,"notice":"Delayed daily closing price snapshot, not real-time ticks. A successful collection does not imply current trading day data."}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Saved', OUTPUT, 'successes:',sum(x.get('status')=='daily_close' for x in records.values()))

if __name__=='__main__':main()
