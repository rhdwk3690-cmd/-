"""KR EOD TOP200 ranking; explicit date verification; investor flows never estimated."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parents[1] / "data" / "kr_flow.json"
KST = ZoneInfo("Asia/Seoul")


def number(value):
    if value is None: return 0
    return int(float(str(value).replace(",", "").replace(" ", "") or 0))


def valid_code(s):
    return len(s) == 6 and s.isdigit()


def official(day, key):
    import requests
    rows = []
    for typ, market in [("stk_bydd_trd", "KOSPI"), ("ksq_bydd_trd", "KOSDAQ")]:
        resp = requests.get(f"https://data-dbg.krx.co.kr/svc/apis/sto/{typ}",
                            headers={"AUTH_KEY": key, "User-Agent": "MinerResearch/1.0"},
                            params={"basDd": day}, timeout=25)
        resp.raise_for_status()
        content = resp.json().get("OutBlock_1", [])
        if not isinstance(content, list): raise ValueError("Unexpected KRX response")
        for x in content:
            code = str(x.get("ISU_SRT_CD") or "").strip()
            if not valid_code(code): continue
            value = number(x.get("ACC_TRDVAL"))
            if value <= 0: continue
            rows.append(dict(ticker=code, name=str(x.get("ISU_NM", "")), market=market,
                             close=number(x.get("TDD_CLSPRC")), traded_krw=value,
                             foreign_net_krw=None, institution_net_krw=None))
    if len(rows) < 200: raise ValueError(f"Only {len(rows)} KRX rows")
    return rows


def finance_data_reader():
    import FinanceDataReader as fdr
    import pandas as pd
    df = fdr.StockListing("KRX-MARCAP")
    needed = {"Code", "Name", "Amount", "Close"}
    if df is None or df.empty or not needed.issubset(df.columns):
        raise ValueError("KRX-MARCAP missing required columns")
    rows = []
    for _, x in df.iterrows():
        code = str(x["Code"]).strip().zfill(6)
        if not valid_code(code): continue
        market = str(x.get("MarketId", x.get("Market", "UNKNOWN"))).upper()
        if market in ("STK", "KOSPI", "KS"): market = "KOSPI"
        elif market in ("KSQ", "KOSDAQ", "KQ"): market = "KOSDAQ"
        else: continue
        value = pd.to_numeric(x["Amount"], errors="coerce")
        close = pd.to_numeric(x["Close"], errors="coerce")
        if pd.isna(value) or value <= 0 or pd.isna(close) or close <= 0: continue
        rows.append(dict(ticker=code, name=str(x["Name"]), market=market,
                         close=int(close), traded_krw=int(value),
                         foreign_net_krw=None, institution_net_krw=None))
    if len(rows) < 200: raise ValueError(f"Only {len(rows)} FDR rows")
    return rows


def verify_fdr_date(rows, today):
    """Cross-check same-day close AND traded amount from dated per-stock histories.

    This is a consistency check, not exchange-certified attribution.
    """
    import FinanceDataReader as fdr
    import pandas as pd
    candidates = [r for r in rows if r["ticker"] in ("005930", "000660", "035420", "005380", "068270")]
    if len(candidates) < 2: candidates = rows[:4]
    matches = {}
    errors = []
    for r in candidates[:5]:
        try:
            frame = fdr.DataReader(r["ticker"], (today - timedelta(days=15)).isoformat())
            if frame is None or frame.empty or not {"Close", "Amount"}.issubset(frame.columns):
                errors.append(f"{r['ticker']}: historical Close/Amount unavailable")
                continue
            df = frame.copy()
            df.index = pd.to_datetime(df.index, errors="coerce")
            for dt, values in df.tail(10).iterrows():
                if pd.isna(dt) or dt.date() > today: continue
                try:
                    close = int(float(values["Close"]))
                    amount = int(float(values["Amount"]))
                except (ValueError, TypeError, OverflowError): continue
                if close == r["close"] and amount == r["traded_krw"]:
                    key = dt.date().isoformat()
                    matches.setdefault(key, set()).add(r["ticker"])
        except Exception as e:
            errors.append(f"{r['ticker']}: {type(e).__name__}: {str(e)[:100]}")
    reliable = [(d, len(codes)) for d, codes in matches.items() if len(codes) >= 2]
    if len(reliable) == 1:
        return reliable[0][0], "cross_checked_two_stocks", errors
    errors.append("Trading date unverified: fewer than 2 same-day Close+Amount matches or ambiguous dates")
    return None, "unverified", errors


def main():
    now = datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    output = dict(collected_at_kst=now.astimezone(KST).isoformat(), status="unavailable",
                  source="none", date=None, date_quality="unverified", top200=[],
                  market_flows={}, errors=[],
                  notice="EOD trading-value snapshot; NOT live. Investor net purchases unavailable. Collection time is not trade date.")
    key = os.getenv("KRX_API_KEY", "").strip()
    if key:
        for lag in range(8):
            day = (today - timedelta(days=lag)).strftime("%Y%m%d")
            try:
                rows = official(day, key)
                output.update(status="partial", source="KRX Open API (authenticated EOD)",
                              date=f"{day[:4]}-{day[4:6]}-{day[6:]}",
                              date_quality="official_requested_date",
                              top200=sorted(rows, key=lambda x: x["traded_krw"], reverse=True)[:200])
                break
            except Exception as exc:
                output["errors"].append(f"KRX {day}: {type(exc).__name__}: {str(exc)[:120]}")
    else:
        output["errors"].append("KRX_API_KEY not configured; official API feed not used")
    if not output["top200"]:
        try:
            rows = finance_data_reader()
            date, quality, details = verify_fdr_date(rows, today)
            output.update(status="partial", source="FinanceDataReader KRX-MARCAP (public aggregator)",
                          date=date, date_quality=quality,
                          top200=sorted(rows, key=lambda x: x["traded_krw"], reverse=True)[:200])
            output["errors"].extend(details)
        except Exception as exc:
            output["errors"].append(f"FinanceDataReader: {type(exc).__name__}: {str(exc)[:160]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"status={output['status']}, rows={len(output['top200'])}, trade_date={output['date']}, quality={output['date_quality']}")
    for err in output["errors"][-8:]: print("INFO:", err)
    if not output["top200"]: raise RuntimeError("No usable TOP200 data; see data/kr_flow.json")

if __name__ == "__main__": main()
