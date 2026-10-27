"""Fear & Greed v2: causal indicators, trend strategy, and next-session backtest.
Usage:
  python fear_greed_engine.py --market KR --excel market.xlsx --out results
  python fear_greed_engine.py --market US --out results  # requires yfinance
  python fear_greed_engine.py --market US --csv us_prices.csv --out results

US CSV: Date,S&P500,NASDAQ,VIX,HYG,IEF,QQQ,SPY (10Y,5Y optional)
Korean Excel: sheets KOSPI, KOSDAQ and original Korean column labels.
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

WINDOW = 252
MIN_PERIODS = 126
FEE_BPS = 5.0  # one-way, on each position change

def rsi(x, n=10):
    x = pd.to_numeric(x, errors='coerce')
    d = x.diff(); ups = d.clip(lower=0); downs = -d.clip(upper=0)
    u = ups.rolling(n, min_periods=n).mean(); v = downs.rolling(n, min_periods=n).mean()
    res = 100 - 100 / (1 + u / v.replace(0, np.nan))
    res = res.mask((v == 0) & (u > 0), 100)
    res = res.mask((u == 0) & (v > 0), 0)
    return res.mask((u == 0) & (v == 0), 50)

def causal_scale(s, higher_is_greed=True):
    s = pd.to_numeric(s, errors='coerce').replace([np.inf, -np.inf], np.nan)
    lo = s.rolling(WINDOW, min_periods=MIN_PERIODS).min()
    hi = s.rolling(WINDOW, min_periods=MIN_PERIODS).max()
    out = ((s - lo) / (hi - lo).replace(0, np.nan)).clip(0, 1)
    out = out.mask((hi == lo) & lo.notna(), .5)
    return out if higher_is_greed else 1 - out

def macd_hist(s):
    fast = s.ewm(span=12, adjust=False).mean()
    slow = s.ewm(span=26, adjust=False).mean()
    line = fast - slow
    return line - line.ewm(span=9, adjust=False).mean()

def clean(df):
    d = df.copy()
    if 'Date' in d.columns:
        d['Date'] = pd.to_datetime(d['Date'], errors='coerce'); d = d.set_index('Date')
    else:
        d.index = pd.to_datetime(d.index, errors='coerce')
    d = d.loc[~d.index.isna()].sort_index()
    d = d.loc[~d.index.duplicated(keep='last')]
    for c in d.columns: d[c] = pd.to_numeric(d[c], errors='coerce')
    return d.replace([np.inf, -np.inf], np.nan)

def engine(df, price, volatility, credit=None, put=None, call=None, bond5=None, bond10=None):
    d = clean(df)
    if price not in d or volatility not in d: raise ValueError(f'Missing price/volatility: {price}, {volatility}')
    # Use rows with observed price; never forward-fill absent prices or risk inputs.
    d = d.dropna(subset=[price]).copy()
    p = d[price]
    d['momentum'] = (p / p.rolling(125, min_periods=125).mean() - 1) * 100
    d['rsi10'] = rsi(p)
    raw = {'momentum': (d['momentum'], True), 'rsi': (d['rsi10'], True),
           'volatility': (d[volatility], False)}
    if credit:
        if credit not in d: raise ValueError(f'Missing {credit}')
        raw['risk_appetite'] = (d[credit], True)
    if put and call:
        if put not in d or call not in d: raise ValueError('Missing put/call input')
        raw['put_call'] = (d[put] / d[call].replace(0, np.nan), False)
    if bond5 and bond10:
        if bond5 not in d or bond10 not in d: raise ValueError('Missing bond inputs')
        # Existing Korean model sign preserved; not independently validated as greed direction.
        raw['bond_diff'] = (d[bond10] - d[bond5], True)
    components = pd.DataFrame({k: causal_scale(s, direction) for k, (s, direction) in raw.items()}, index=d.index)
    d['fg_score'] = components.mean(axis=1, skipna=False) * 100
    for col in components: d['component_' + col] = components[col] * 100
    d['fg_ema20'] = d['fg_score'].ewm(span=20, adjust=False, ignore_na=True).mean()
    # Avoid bridging gaps for trading purposes: trading signal requires today's actual FG.
    d['fg_hist'] = macd_hist(d['fg_score'] / 100)
    d['ema13'] = p.ewm(span=13, adjust=False).mean()
    d['price_hist'] = macd_hist(p)
    d['elder'] = np.select([(d.ema13.diff() > 0) & (d.price_hist.diff() > 0),
                            (d.ema13.diff() < 0) & (d.price_hist.diff() < 0)],
                           ['green', 'red'], default='blue')
    ma_cols = []
    for n in (20, 60, 120, 200):
        k = f'ma{n}'; ma_cols.append(k); d[k] = p.rolling(n, min_periods=n).mean()
    d['superma'] = d[ma_cols].mean(axis=1, skipna=False)
    d['gap_pct'] = 100 * (p / d['superma'] - 1)
    # Custom DeMark counts exactly as in supplied scripts (Sell=4, Buy=2).
    sell, buy = np.zeros(len(d), dtype=int), np.zeros(len(d), dtype=int)
    vals = p.to_numpy()
    for i in range(len(d)):
        if i >= 4 and np.isfinite(vals[i]) and np.isfinite(vals[i-4]) and vals[i] > vals[i-4]:
            sell[i] = sell[i-1] + 1
        if i >= 2 and np.isfinite(vals[i]) and np.isfinite(vals[i-2]) and vals[i] < vals[i-2]:
            buy[i] = buy[i-1] + 1
    d['td_sell4'] = sell; d['td_buy2'] = buy
    d['trend_up'] = (p > d['ma200']) & (d['ma20'] > d['ma60'])
    d['fg_rising'] = (d['fg_score'] > d['fg_ema20']) & (d['fg_hist'] > 0)
    d['fg_falling'] = (d['fg_score'] < d['fg_ema20']) & (d['fg_hist'] < 0)
    # Debounce: entry on regime agreement; exit on structural trend deterioration or severe pessimism.
    entry = d['trend_up'] & d['fg_rising'] & (d['elder'] != 'red')
    exit_ = (~d['trend_up']) | ((d['fg_falling']) & (d['elder'] == 'red'))
    valid = d[['fg_score', 'fg_ema20', 'fg_hist', 'superma']].notna().all(axis=1)
    state = 0; targets = []
    for e, x, ok in zip(entry, exit_, valid):
        if not ok: state = 0  # fail safe, no trading on incomplete current data
        elif x: state = 0
        elif e: state = 1
        targets.append(state)
    d['target'] = targets
    # Standard next-close-to-next-close test: signal after close t affects return t+1.
    d['position'] = d['target'].shift(1).fillna(0)
    d['asset_return'] = p.pct_change(fill_method=None).fillna(0)
    d['turnover'] = d['position'].diff().abs().fillna(d['position'].abs())
    d['net_return'] = d['position'] * d['asset_return'] - d['turnover'] * FEE_BPS / 10000
    d['equity'] = (1 + d['net_return']).cumprod()
    d['benchmark'] = (1 + d['asset_return']).cumprod()
    return d

def metrics(df, col='net_return'):
    r = df[col].dropna()
    if len(r) < 2: return {}
    curve = (1 + r).cumprod()
    dd = curve / curve.cummax() - 1
    years = len(r) / 252
    cagr = float(curve.iloc[-1] ** (1 / years) - 1) if curve.iloc[-1] > 0 else np.nan
    vol = float(r.std(ddof=1) * np.sqrt(252))
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if r.std(ddof=1) > 0 else np.nan
    return {'observations': len(r), 'total_return': float(curve.iloc[-1] - 1),
            'cagr': cagr, 'annual_vol': vol, 'sharpe_rf0': sharpe,
            'mdd': float(dd.min()), 'positive_days_pct': float((r > 0).mean()*100)}

def load_kr(path):
    out = {}
    for sheet, price in [('KOSPI','코스피'), ('KOSDAQ','코스닥')]:
        d = pd.read_excel(path, sheet_name=sheet)
        if 'Date' not in d: d = d.rename(columns={d.columns[0]: 'Date'})
        out[sheet] = engine(d, price=price, volatility='코스피 200 변동성지수',
                            put='최근월물 PUT ATM', call='최근월물 CALL ATM',
                            bond5='5년 국채선물 추종 지수', bond10='10년국채선물지수')
    try:
        flow = pd.read_excel(path, sheet_name='개인순매수와코스피지수')
        if flow.shape[1] >= 3:
            flow = flow.iloc[:, :3].copy()
            flow.columns = ['Date', 'Flow_KOSPI_Close', 'Individual_NetBuy_100M']
            flow = clean(flow)
            flow['individual_netbuy_trillion'] = flow['Individual_NetBuy_100M'] / 10000
            flow['flow_index_return'] = flow['Flow_KOSPI_Close'].pct_change(fill_method=None)
            q3 = (flow['flow_index_return'] < 0) & (flow['individual_netbuy_trillion'] < 0)
            flow['capitulation_candidate'] = q3 & q3.shift(1, fill_value=False)
            out['KOSPI'] = out['KOSPI'].join(flow[['individual_netbuy_trillion', 'capitulation_candidate']], how='left')
    except ValueError:
        pass  # optional sheet absent
    return out

def load_us(csv=None, start='2020-01-01'):
    if csv:
        d = pd.read_csv(csv)
    else:
        try: import yfinance as yf
        except ImportError as e: raise RuntimeError('Install yfinance: pip install yfinance') from e
        tickers = ['^GSPC','^IXIC','^VIX','HYG','IEF','QQQ','SPY']
        data = yf.download(tickers, start=start, auto_adjust=False, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data = data['Close'] if 'Close' in data.columns.get_level_values(0) else data.xs('Close', axis=1, level=1)
        d = data.rename(columns={'^GSPC':'S&P500','^IXIC':'NASDAQ','^VIX':'VIX'}).reset_index()
    d = clean(d)
    for col in ['HYG','IEF','VIX','S&P500','NASDAQ']:
        if col not in d: raise ValueError(f'Missing US data column: {col}')
    d['Risk_Appetite'] = d['HYG'] / d['IEF'].replace(0, np.nan)
    return {'SP500': engine(d,'S&P500','VIX',credit='Risk_Appetite'),
            'NASDAQ': engine(d,'NASDAQ','VIX',credit='Risk_Appetite')}

def plot(df, title, dest):
    recent = df.iloc[-252:].copy()
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                             gridspec_kw={'height_ratios': [2, 1.6, 1.2]})
    axes[0].plot(recent.index, recent['equity'], label='Strategy (net)')
    axes[0].plot(recent.index, recent['benchmark'], label='Buy and hold')
    axes[0].legend(); axes[0].set_title(title + ' (last 252 trading days, full-history wealth)')
    axes[1].plot(recent.index, recent['fg_score'], label='F&G')
    axes[1].plot(recent.index, recent['fg_ema20'], label='F&G EMA20')
    axes[1].legend(); axes[1].set_ylim(0,100)
    axes[2].step(recent.index, recent['position'], where='post', label='Exposure')
    axes[2].set_ylim(-.1,1.1); axes[2].legend()
    for ax in axes: ax.grid(alpha=.2)
    fig.tight_layout(); fig.savefig(dest, dpi=150); plt.close(fig)

def execute(results, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, df in results.items():
        # Fair comparison: start after all indicators have become available.
        test = df.loc[df['fg_score'].notna() & df['superma'].notna()].copy()
        if len(test) < 30:
            print(f'{name}: insufficient complete observations ({len(test)})'); continue
        test['position'] = test['target'].shift(1).fillna(0)
        test['turnover'] = test['position'].diff().abs().fillna(test['position'].abs())
        test['asset_return'] = test.iloc[:,0]*0 if False else df.loc[test.index, 'asset_return']
        test['net_return'] = test['position'] * test['asset_return'] - test['turnover']*FEE_BPS/10000
        test['equity'] = (1+test['net_return']).cumprod()
        test['benchmark'] = (1+test['asset_return']).cumprod()
        s = metrics(test, 'net_return'); b = metrics(test, 'asset_return')
        for k,v in s.items(): rows.append({'market':name, 'model':'strategy', 'metric':k,'value':v})
        for k,v in b.items(): rows.append({'market':name, 'model':'buy_hold', 'metric':k,'value':v})
        rows.append({'market':name,'model':'strategy','metric':'one_way_trades','value':float(test.turnover.sum())})
        rows.append({'market':name,'model':'strategy','metric':'start_date','value':str(test.index[0].date())})
        rows.append({'market':name,'model':'strategy','metric':'end_date','value':str(test.index[-1].date())})
        test.to_csv(out / f'{name}_signals.csv', encoding='utf-8-sig')
        plot(test, name, out / f'{name}_chart.png')
        print(f'{name}: {test.index[0].date()} to {test.index[-1].date()} | strategy CAGR={s.get("cagr",float("nan")):.2%} | MDD={s.get("mdd",float("nan")):.2%} | buyhold CAGR={b.get("cagr",float("nan")):.2%}')
    pd.DataFrame(rows).to_csv(out / 'comparison.csv', index=False, encoding='utf-8-sig')

def main():
    a = argparse.ArgumentParser()
    a.add_argument('--market', required=True, choices=['KR','US']); a.add_argument('--excel'); a.add_argument('--csv'); a.add_argument('--start', default='2020-01-01'); a.add_argument('--out', default='results')
    args = a.parse_args()
    if args.market == 'KR' and not args.excel: a.error('KR requires --excel')
    execute(load_kr(args.excel) if args.market == 'KR' else load_us(args.csv, args.start), args.out)
if __name__ == '__main__': main()
