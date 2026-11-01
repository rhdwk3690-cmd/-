"""Miner research pilot: H0 55-day breakouts vs H1 constructive bases.

Exploratory event study, not a portfolio backtest. ONLY point-in-time pre-signal
features. Universe is rebuilt every day from prior 20-session traded value.
Raw marcap OHLC is not fully corporate-action adjusted; conservative censoring.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

MARCAP_COMMIT = '6b36e3ca01e7b4dc73c84f279e093843889d26dd'
DATE_START = '2021-01-01'
DATE_END = '2026-10-30'
SIGNAL_START = '2022-01-01'
TRAIN_END = '2024-12-31'
TEST_END = '2026-10-30'
HORIZONS = (20, 60)
COST_EACH_SIDE = 0.0015
REQUIRED = ('Date','Code','Name','Market','Open','High','Low','Close','Volume','Amount','Stocks')


def load_data(cache: Path, years=range(2021, 2027)) -> tuple[pd.DataFrame, list]:
    import pyarrow.parquet as pq
    cache.mkdir(parents=True, exist_ok=True)
    frames, provenances = [], []
    session = requests.Session()
    for year in years:
        url = (f'https://raw.githubusercontent.com/FinanceData/marcap/'
               f'{MARCAP_COMMIT}/data/marcap-{year}.parquet')
        file = cache / f'marcap-{year}.parquet'
        if not file.exists():
            tmp = file.with_suffix('.part')
            try:
                with session.get(url, timeout=(15, 120), stream=True) as resp:
                    resp.raise_for_status()
                    with tmp.open('wb') as fo:
                        for chunk in resp.iter_content(chunk_size=1024*1024):
                            if chunk: fo.write(chunk)
                if tmp.stat().st_size < 100_000:
                    raise ValueError(f'원본 크기 비정상: {year} {tmp.stat().st_size}')
                tmp.rename(file)
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
        p = pq.ParquetFile(file)
        cols = p.schema.names
        missing = sorted(set(REQUIRED)-set(cols))
        if missing:
            raise ValueError(f'{year} 필수 원자료 열 누락 {missing}. 스키마 변경 시 연구 중단')
        sha = hashlib.sha256(file.read_bytes()).hexdigest()
        f = pd.read_parquet(file, columns=list(REQUIRED))
        f['source_year'] = year
        frames.append(f)
        provenances.append({'year': year,'url':url,'sha256':sha,'file_bytes':file.stat().st_size,
                            'rows':len(f),'columns':cols})
        print(f'[source] {year}: {len(f):,} rows, SHA256={sha[:16]}', flush=True)
    data = pd.concat(frames, ignore_index=True)
    return data, provenances


def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    """Validate and construct only information observed by each signal close."""
    d = raw.loc[:, list(REQUIRED)].copy()
    d['Date'] = pd.to_datetime(d['Date'], errors='coerce').dt.tz_localize(None)
    if d['Date'].isna().any(): raise ValueError('원천 거래일 중 날짜 해석 실패')
    d['Code'] = d['Code'].astype('string').str.strip().str.zfill(6)
    d['Market'] = d['Market'].astype('string').str.strip().str.upper()
    d['Name'] = d['Name'].astype('string')
    d = d.loc[d['Market'].isin(['KOSPI','KOSDAQ']) & d['Code'].str.fullmatch(r'\d{6}')]
    if len(d) < 1500: raise ValueError('대상 거래소 원자료 부족')
    if d.duplicated(['Date','Code']).any(): raise ValueError('동일 일자 종목코드 중복')
    for c in ['Open','High','Low','Close','Volume','Amount','Stocks']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    if (d['Date'].max() - d['Date'].min()).days < 360:
        raise ValueError('원본 기간 부족')
    d = d.sort_values(['Code','Date']).reset_index(drop=True)
    days = sorted(d['Date'].unique())
    day_index = {t:i for i,t in enumerate(days)}
    d['di'] = d['Date'].map(day_index).astype('int32')
    g = d.groupby('Code',sort=False,observed=True)
    # For a *signal calculated at close t*, use only trade-value history through t-1.
    d['avg_amount20_prev'] = g['Amount'].transform(lambda x:x.shift(1).rolling(20,min_periods=20).mean())
    d['high55_prev'] = g['High'].transform(lambda x:x.shift(1).rolling(55,min_periods=55).max())
    d['high55_prev_yest'] = g['High'].transform(lambda x:x.shift(2).rolling(55,min_periods=55).max())
    d['prior_close'] = g['Close'].shift(1)
    d['close25ago'] = g['Close'].shift(25)
    d['close125ago'] = g['Close'].shift(125)
    d['di125ago'] = g['di'].shift(125)
    d['base_hi25'] = g['High'].transform(lambda x:x.shift(1).rolling(25,min_periods=25).max())
    d['base_lo25'] = g['Low'].transform(lambda x:x.shift(1).rolling(25,min_periods=25).min())
    d['recent_hi10'] = g['High'].transform(lambda x:x.shift(1).rolling(10,min_periods=10).max())
    d['recent_lo10'] = g['Low'].transform(lambda x:x.shift(1).rolling(10,min_periods=10).min())
    d['older_hi15'] = g['High'].transform(lambda x:x.shift(11).rolling(15,min_periods=15).max())
    d['older_lo15'] = g['Low'].transform(lambda x:x.shift(11).rolling(15,min_periods=15).min())
    # The *rank is recalculated every trading day*; no use of today's top200 in past.
    eligible = (d['avg_amount20_prev'] > 2_000_000_000) & (d['Close']>0) & (d['Open']>0) & (d['Amount']>0)
    d['liquidity_rank'] = (d['avg_amount20_prev'].where(eligible)
                           .groupby(d['Date']).rank(method='first',ascending=False))
    # Require 125 consecutive exchange sessions for prior price-pattern measurement.
    d['history_complete'] = d['di'].sub(d['di125ago']).eq(125)
    valid_today=(d['High']>=d[['Open','Close']].max(axis=1)) & (d['Low']>0) & (d['Low']<=d[['Open','Close']].min(axis=1)) & (d['Stocks']>0) & (d['Volume']>0)
    d['H0'] = (valid_today & d['liquidity_rank'].le(200) & d['history_complete'] &
               d['Close'].gt(d['high55_prev']) &
               d['prior_close'].le(d['high55_prev_yest']) &
               d['Date'].ge(pd.Timestamp(SIGNAL_START)) &
               d['Date'].le(pd.Timestamp(TEST_END)))
    base_depth = 1 - d['base_lo25']/d['base_hi25']
    late_width = d['recent_hi10']/d['recent_lo10']-1
    early_width = d['older_hi15']/d['older_lo15']-1
    pre_rally = d['close25ago']/d['close125ago']-1
    # H1 deliberately nested inside H0 so both groups share the same source/universe.
    d['H1'] = (d['H0'] & pre_rally.ge(0.25) & base_depth.between(0.04,0.30) &
               late_width.ge(0) & early_width.gt(0) & late_width.le(early_width*0.85))
    d['base_depth_pct'] = 100*base_depth
    d['pre_rally_pct'] = 100*pre_rally
    d['late_to_early_width'] = late_width/early_width.replace(0,np.nan)
    return d


def filter_events(d:pd.DataFrame, cooldown=60) -> pd.DataFrame:
    """Common, forward-blind 60-session dedupe on H0, BEFORE labeling H1."""
    candidates = d.loc[d['H0'], ['Code','Name','Date','Market','di','liquidity_rank',
                                  'pre_rally_pct','base_depth_pct','late_to_early_width','H1']].copy()
    candidates = candidates.sort_values(['Code','di'])
    kept=[]
    for _,grp in candidates.groupby('Code',sort=False,observed=True):
        prev=-10_000
        for idx,r in grp.iterrows():
            if int(r['di']) - prev < cooldown: continue
            kept.append(idx);prev=int(r['di'])
    return candidates.loc[kept].sort_values(['Date','Code']).reset_index(drop=True)


def evaluate_events(d:pd.DataFrame, ev:pd.DataFrame):
    """Start at next *exchange* session open, exit 20/60 exchange sessions later.

    Do NOT silently skip delisted/paused stocks. Keep explicit censored records.
    Raw prices are conservatively filtered for corporate-action discontinuities.
    """
    need = set(ev['Code'].astype(str))
    by_code = {code:g.set_index('di',drop=False).sort_index() for code,g in
               d.loc[d['Code'].isin(need)].groupby('Code',sort=False,observed=True)}
    max_di = int(d['di'].max())
    all_rows=[]
    for e in ev.itertuples(index=False):
        sub = by_code[e.Code]
        t = int(e.di)
        for h in HORIZONS:
            row = {'signal_date':e.Date.strftime('%Y-%m-%d'),'Code':e.Code,'Name':str(e.Name),
                   'Market':e.Market,'H1':bool(e.H1),'rank':int(e.liquidity_rank),
                   'base_depth_pct':round(float(e.base_depth_pct),3) if pd.notna(e.base_depth_pct) else None,
                   'pre_rally_pct':round(float(e.pre_rally_pct),3) if pd.notna(e.pre_rally_pct) else None,
                   'h':h, 'status':'pending','return_net_pct':None,'mae_pct':None,
                   'exit_date':None}
            if t+1+h > max_di:
                row['status']='not_yet_mature';all_rows.append(row);continue
            # Every exchange day must have a price row to prevent a halt/delisting
            # from being mistaken for an unusually good zero-return position.
            idx=list(range(t+1,t+2+h))
            if not sub.index.is_unique: raise ValueError('중복 거래 세션')
            if any(j not in sub.index for j in idx):
                row['status']='halted_or_delisted_or_missing';all_rows.append(row);continue
            chunk=sub.loc[idx]
            if (chunk[['Open','High','Low','Close','Stocks']].isna().any().any() or
                (chunk[['Open','High','Low','Close','Stocks']]<=0).any().any()):
                row['status']='bad_prices';all_rows.append(row);continue
            prev = sub.loc[t] if t in sub.index else None
            if prev is None or not (prev['Close']>0 and prev['Stocks']>0):
                row['status']='bad_signal_price';all_rows.append(row);continue
            prices=np.r_[float(prev['Close']),chunk['Close'].to_numpy(dtype=float)]
            shares=np.r_[float(prev['Stocks']),chunk['Stocks'].to_numpy(dtype=float)]
            # 30% price limit, plus a buffer. Huge jumps/stock-count changes
            # invalidate raw-price returns; this is NOT full split adjustment.
            if ((np.abs(prices[1:]/prices[:-1]-1)>0.34).any() or
                (np.abs(shares[1:]/shares[:-1]-1)>0.08).any()):
                row['status']='corporate_action_or_price_gap';all_rows.append(row);continue
            entry=float(chunk.iloc[0]['Open']);exit_close=float(chunk.iloc[-1]['Close'])
            ret=100*((exit_close*(1-COST_EACH_SIDE))/(entry*(1+COST_EACH_SIDE))-1)
            adverse=100*(float(chunk['Low'].min())/entry-1)
            row.update(status='mature',return_net_pct=round(ret,5),
                       mae_pct=round(min(0.0,adverse),5),
                       exit_date=chunk.iloc[-1]['Date'].strftime('%Y-%m-%d'))
            all_rows.append(row)
    return pd.DataFrame(all_rows)


def summarise(rows:pd.DataFrame)->pd.DataFrame:
    stats=[]
    for split,sub in [('train_2022_2024',rows[rows.signal_date <= TRAIN_END]),
                      ('holdout_2025_2026',rows[rows.signal_date > TRAIN_END])]:
        for h in HORIZONS:
            obs=sub[sub.h==h]
            for label,mask in [('H0_all',obs.H1.notna()),('H1_constructive_base',obs.H1==True),
                               ('H0_without_H1',obs.H1==False)]:
                chosen=obs[mask];mature=chosen[chosen.status=='mature'];
                returns=mature['return_net_pct'];mae=mature['mae_pct']
                stats.append({'split':split,'horizon':h,'group':label,
                              'signals_all':len(chosen),'mature':len(mature),
                              'censored_halt_delisting':int(chosen['status'].eq('halted_or_delisted_or_missing').sum()),
                              'censored_corp_action':int(chosen['status'].eq('corporate_action_or_price_gap').sum()),
                              'not_yet_mature':int(chosen['status'].eq('not_yet_mature').sum()),
                              'mean_return_net_pct':round(float(returns.mean()),3) if len(mature) else None,
                              'median_return_net_pct':round(float(returns.median()),3) if len(mature) else None,
                              'win_rate_pct':round(100*float((returns>0).mean()),2) if len(mature) else None,
                              'mean_mae_pct':round(float(mae.mean()),3) if len(mature) else None,
                              'return_p10_pct':round(float(returns.quantile(0.10)),3) if len(mature) else None,
                              'interpretation':'LOW_SAMPLE' if len(mature)<30 else 'EXPLORATORY_ONLY'})
    return pd.DataFrame(stats)


def matched_cohort(rows: pd.DataFrame) -> pd.DataFrame:
    """Preliminary same-month-and-market H1 versus other H0 event comparison."""
    mature=rows.loc[rows.status=='mature'].copy()
    mature['month']=mature.signal_date.str[:7]
    mature['period']=np.where(mature.signal_date<=TRAIN_END,'train','holdout')
    results=[]
    for (period,h,month,market),g in mature.groupby(['period','h','month','Market']):
        a=g[g.H1]
        b=g[~g.H1]
        if len(a)<1 or len(b)<1:continue
        results.append({'period':period,'h':h,'month':month,'market':market,
                        'n_H1':len(a),'n_H0_other':len(b),
                        'H1_mean_return_pct':round(a.return_net_pct.mean(),4),
                        'H0_other_mean_return_pct':round(b.return_net_pct.mean(),4),
                        'H1_minus_other_pct':round(a.return_net_pct.mean()-b.return_net_pct.mean(),4)})
    return pd.DataFrame(results,columns=['period','h','month','market','n_H1','n_H0_other',
        'H1_mean_return_pct','H0_other_mean_return_pct','H1_minus_other_pct'])


def selftest():
    from datetime import datetime, timedelta
    days = pd.bdate_range('2023-01-02',periods=260)
    rec=[]
    for code in [f'{i:06d}' for i in range(1,9)]:
        for i,dt in enumerate(days):
            # An event appears after 125 days with synthetic prior uptrend and base.
            px = 100+0.42*i if i<155 else 165+(i-155)*.10
            if i == 201: px=210
            if i>=202: px=204+(i-202)*.04
            rec.append({'Date':dt,'Code':code,'Name':'TEST','Market':'KOSPI',
                        'Open':px,'High':px*1.006,'Low':px*.994,'Close':px,
                        'Volume':100_000,'Amount':5_000_000_000 if code=='000001' else 3_000_000_000,
                        'Stocks':10000000})
    src=pd.DataFrame(rec)
    p=prepare(src)
    assert p['H0'].any(), 'expected synthetic breakout'
    assert p['liquidity_rank'].max()<=8
    # Membership cannot depend on today's turnover: change it by 100x on one day.
    altered=src.copy();ix=(altered.Code=='000002')&(altered.Date==days[200]);altered.loc[ix,'Amount']=1_000_000_000_000
    p2=prepare(altered)
    b=p.loc[(p.Code=='000002')&(p.Date==days[200]),'liquidity_rank'].iloc[0]
    a=p2.loc[(p2.Code=='000002')&(p2.Date==days[200]),'liquidity_rank'].iloc[0]
    assert a==b, 'same-day turnover leaked into universe ranking'
    sig=filter_events(p)
    out=evaluate_events(p,sig)
    assert not out.empty
    example=out[(out.h==20)&(out.status=='mature')].iloc[0]
    event=p.loc[(p.Code==example.Code)&(p.Date==pd.Timestamp(example.signal_date))].iloc[0]
    entry=p.loc[(p.Code==example.Code)&(p.di==event.di+1),'Open'].iloc[0]
    exitprice=p.loc[(p.Code==example.Code)&(p.Date==pd.Timestamp(example.exit_date)),'Close'].iloc[0]
    expected=100*((exitprice*(1-COST_EACH_SIDE))/(entry*(1+COST_EACH_SIDE))-1)
    assert abs(example.return_net_pct - expected)<1e-4, 'wrong event entry/exit timing'
    # Corp-action count change invalidates both H0 and H1 outcome measurement.
    damaged=p.copy();target=example.Code
    start=int(event.di+3)
    damaged.loc[(damaged.Code==target)&(damaged.di>=start),'Stocks']*=2
    out2=evaluate_events(damaged,sig)
    bad=out2[(out2.Code==target)&(out2.signal_date==example.signal_date)&(out2.h==20)]
    assert bad.iloc[0].status=='corporate_action_or_price_gap'
    assert (p.H1 & ~p.H0).sum()==0
    # Changing any *future* prices must not alter previously calculated signals.
    later=src.copy()
    later.loc[later.Date>days[211], ['Open','High','Low','Close']]*=1.5
    original=prepare(src)
    revised=prepare(later)
    for k in ['H0','H1']:
        assert original.loc[original.Date<=days[200],k].reset_index(drop=True).equals(
            revised.loc[revised.Date<=days[200],k].reset_index(drop=True)), 'future leakage'
    print('SELFTEST PASS: prior-session universe, nested setup, future entry, corporate-action gate, future-leakage')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--selftest',action='store_true')
    parser.add_argument('--cache',default='outputs/source')
    parser.add_argument('--out',default='outputs/research')
    args=parser.parse_args()
    if args.selftest: selftest();return
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    d,provenances=load_data(Path(args.cache))
    pre=prepare(d)
    n_dates=pre['Date'].nunique();stocks=pre['Code'].nunique()
    print(f'[universe] {n_dates} dates / {stocks} distinct historical stock codes')
    if stocks<1800 or n_dates<800: raise ValueError('과거 전종목 또는 거래일 커버리지 부족; 결과 보류')
    ev=filter_events(pre)
    print(f'[signals] H0 {len(ev)}, H1 {int(ev.H1.sum())}')
    if ev.empty: raise ValueError('유효 신호 없음. 데이터와 필터를 검사해야 함')
    outcome=evaluate_events(pre,ev)
    summary=summarise(outcome)
    matched=matched_cohort(outcome)
    outcome.to_csv(out/'signals_and_forward.csv',index=False,encoding='utf-8-sig')
    summary.to_csv(out/'comparison.csv',index=False,encoding='utf-8-sig')
    matched.to_csv(out/'month_market_matched.csv',index=False,encoding='utf-8-sig')
    manifest={'source':'FinanceData/marcap original KRX cross-sections (unadjusted raw OHLC)',
              'source_commit':MARCAP_COMMIT,'source_files':provenances,
              'unique_historical_codes':int(stocks),'unique_market_days':int(n_dates),
              'latest_day':str(pre.Date.max().date()),
              'signal_total_H0':int(len(ev)),'signal_H1':int(ev.H1.sum()),
              'signal_start':SIGNAL_START,'train_end':TRAIN_END,'cost_each_side':COST_EACH_SIDE,
              'research_limits':['unadjusted OHLC with conservative large-corporate-action censorship',
                'no financial statements or fundamentals in this first comparison',
                'point-in-time 20-session traded-value rank, 200 per day',
                'results are event average, not portfolio CAGR/MDD or strategy return',
                'overlapping and correlated signals, multiple testing, future data gaps',
                'delisted or halted signals are censored and quantified, not silently given zero PnL']}
    (out/'data_provenance.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n=== FIRST STAGE H0 vs H1: EVENT RETURNS, NOT PORTFOLIO PERFORMANCE ===')
    print(summary.to_string(index=False))
    print('\n=== Same month & market matched exploratory differences (H1 - H0 without H1) ===')
    if not matched.empty:
        print(matched.groupby(['period','h'])['H1_minus_other_pct'].agg(['count','mean','median']).to_string())
    else:print('No same-month-and-market matched sample; evidence insufficient')
    print('\nData issues and analysis limitations: data_provenance.json')

if __name__=='__main__':main()
