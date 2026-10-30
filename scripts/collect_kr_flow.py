"""광부 투자터미널 | KOSPI/KOSDAQ 거래대금 TOP 200 (검증된 거래일만 게시).

우선순위: KRX 공식 API(인증키가 이미 설정된 경우) -> 한국주식데이터 공개 주식시세.
무료 공개 원본: https://aikstockdata.com/data/public/quotes.csv
원천: 금융위원회 공공데이터포털. 제공처 이용 조건: 비영리 개인 연구, 출처 명시.

T+1 확정 종가이며 투자자별 순매수 금액은 이 파일에 포함되지 않는다.
날짜 미확인 상태로 임의 날짜를 부여하거나 순매수 수치를 추정하지 않는다.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "kr_flow.json"
KST = ZoneInfo("Asia/Seoul")
AIK = "https://aikstockdata.com/data/public"
HEADERS = {"User-Agent": "MinerTerminal/1.0 (noncommercial personal research)",
           "Accept": "application/json,text/csv,*/*"}
MIN_ROWS = 1500
MAX_STALE_DAYS = 10  # 긴 연휴 대비. 오래된 확정값은 자동 최신값으로 둔갑시키지 않음.


class DataValidationError(ValueError):
    """거래일, 표본, 값이 독립적으로 검증되지 않은 원자료."""


def integer(value, name: str) -> int:
    """원 단위 정수. 누락·비정상값을 조용히 0으로 바꾸지 않음."""
    raw = str(value if value is not None else "").replace(",", "").strip()
    try:
        val = Decimal(raw)
        if not val.is_finite() or val != val.to_integral_value():
            raise ValueError
        return int(val)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DataValidationError(f"{name}: 숫자 아님 ({raw[:30]})") from exc


def parse_day(value: str, now_day: date, kind: str) -> str:
    """한 날짜를 실제 거래일의 날짜값으로 받아 미래·장기 지연을 차단."""
    raw = str(value or "").strip().replace("-", "")
    if not re.fullmatch(r"\d{8}", raw):
        raise DataValidationError(f"{kind} 기준일이 8자리 날짜가 아닙니다: {raw}")
    try:
        d = datetime.strptime(raw, "%Y%m%d").date()
    except ValueError as exc:
        raise DataValidationError(f"{kind} 기준일 형식 오류: {raw}") from exc
    if d > now_day:
        raise DataValidationError(f"{kind} 기준일이 미래입니다: {d}")
    if (now_day - d).days > MAX_STALE_DAYS:
        raise DataValidationError(f"{kind} 원자료 지연: {d} ({MAX_STALE_DAYS}일 초과)")
    return d.isoformat()


def validate_universe(rows: list[dict], label: str) -> list[dict]:
    if len(rows) < MIN_ROWS:
        raise DataValidationError(f"{label}: 유효 종목 수 부족 ({len(rows)})")
    code_set = set()
    counts = {"KOSPI": 0, "KOSDAQ": 0}
    for row in rows:
        code = row["ticker"]
        if not re.fullmatch(r"\d{6}", code):
            raise DataValidationError(f"{label}: 종목코드 오류: {code}")
        if code in code_set:
            raise DataValidationError(f"{label}: 종목코드 중복: {code}")
        code_set.add(code)
        if row["market"] not in counts:
            raise DataValidationError(f"{label}: 알 수 없는 시장: {row['market']}")
        if row["traded_krw"] <= 0 or row["close"] <= 0:
            raise DataValidationError(f"{label}: 0 이하 값 포함: {code}")
        counts[row["market"]] += 1
    if min(counts.values()) < 300:
        raise DataValidationError(f"{label}: 시장별 종목 수 부족: {counts}")
    return sorted(rows, key=lambda row: (-row["traded_krw"], row["ticker"]))[:200]


def official(day: str, key: str, session: requests.Session) -> list[dict]:
    """KRX 주식시장 거래대금; ETF·ETN 전용 엔드포인트는 사용하지 않는다."""
    rows = []
    for typ, market in (("stk_bydd_trd", "KOSPI"), ("ksq_bydd_trd", "KOSDAQ")):
        resp = session.get(f"https://data-dbg.krx.co.kr/svc/apis/sto/{typ}",
                           headers={"AUTH_KEY": key, **HEADERS},
                           params={"basDd": day.replace("-", "")}, timeout=25)
        resp.raise_for_status()
        payload = resp.json()
        block = payload.get("OutBlock_1") if isinstance(payload, dict) else None
        if not isinstance(block, list) or not block:
            raise DataValidationError(f"KRX {market}: 빈/비정상 API 응답")
        for item in block:
            code = str(item.get("ISU_SRT_CD") or "").strip()
            if not re.fullmatch(r"\d{6}", code):
                continue
            volume = integer(item.get("ACC_TRDVAL"), "ACC_TRDVAL")
            close = integer(item.get("TDD_CLSPRC"), "TDD_CLSPRC")
            if not volume or not close:
                continue
            rows.append({"ticker": code, "name": str(item.get("ISU_NM") or "").strip(),
                         "market": market, "close": close, "traded_krw": volume,
                         "foreign_net_krw": None, "institution_net_krw": None})
    return validate_universe(rows, "KRX")


def parse_aik_stock_csv(csv_bytes: bytes, index: dict, today: dict, now_day: date) -> tuple[list[dict], str, dict]:
    """CSV 모든 basDt == 카탈로그 quote_basis_date == today.quote_as_of 인지 확인."""
    if not isinstance(index, dict) or not isinstance(today, dict):
        raise DataValidationError("공개 메타데이터 형식 오류")
    date_index = parse_day(index.get("quote_basis_date_iso") or index.get("quote_basis_date"),
                           now_day, "카탈로그")
    date_today = parse_day(today.get("quote_as_of_iso") or today.get("quote_as_of"),
                           now_day, "시장 다이제스트")
    if date_index != date_today:
        raise DataValidationError(f"메타 기준일 불일치: index={date_index}, today={date_today}")
    id1, id2 = index.get("snapshot_id"), today.get("snapshot_id")
    if id1 and id2 and id1 != id2:
        raise DataValidationError(f"원천 스냅샷 불일치: {id1} / {id2}")

    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    needed = {"basDt", "종목코드", "종목명", "mrktCtg", "clpr", "trPrc"}
    if not reader.fieldnames or not needed.issubset(set(reader.fieldnames)):
        raise DataValidationError(f"시세 CSV 필수 열 누락: {sorted(needed - set(reader.fieldnames or []))}")
    all_count, market_count, excluded_nontrade = 0, {"KOSPI": 0, "KOSDAQ": 0}, 0
    rows, all_codes = [], set()
    for item in reader:
        all_count += 1
        record_date = parse_day(item.get("basDt"), now_day, "CSV")
        if record_date != date_index:
            raise DataValidationError(f"CSV 기준일 혼합: {record_date} != {date_index}")
        code = str(item.get("종목코드") or "").strip().zfill(6)
        if not re.fullmatch(r"\d{6}", code) or code in all_codes:
            raise DataValidationError(f"CSV 종목코드 중복/형식 오류: {code}")
        all_codes.add(code)
        market = str(item.get("mrktCtg") or "").strip().upper()
        if market not in ("KOSPI", "KOSDAQ", "KONEX"):
            raise DataValidationError(f"CSV 알 수 없는 시장 구분: {market}")
        if market == "KONEX":
            continue
        market_count[market] += 1
        traded = integer(item.get("trPrc"), f"{code} 거래대금")
        close = integer(item.get("clpr"), f"{code} 종가")
        if traded < 0 or close < 0:
            raise DataValidationError(f"{code}: 음수 종가 또는 거래대금")
        if traded == 0 or close == 0:
            excluded_nontrade += 1
            continue
        rows.append({"ticker": code, "name": str(item.get("종목명") or "").strip(),
                     "market": market, "close": close, "traded_krw": traded,
                     "foreign_net_krw": None, "institution_net_krw": None})

    if all_count < MIN_ROWS or min(market_count.values()) < 300:
        raise DataValidationError(f"종목 전체 수 부족: total={all_count}, markets={market_count}")
    coverage = index.get("coverage") or {}
    published_n = coverage.get("published_n")
    if published_n is not None and all_count != int(published_n):
        raise DataValidationError(f"카탈로그 종목 수 불일치: CSV={all_count}, index={published_n}")
    breadth = today.get("market_breadth") or {}
    if breadth.get("total") is not None and all_count != int(breadth["total"]):
        raise DataValidationError(f"다이제스트 종목 수 불일치: CSV={all_count}, today={breadth['total']}")
    # 금융위 '주식시세'만 사용한다는 분류가 카탈로그에 확인되어야 ETF 제외를 보장할 수 있다.
    excluded_note = str(coverage.get("excludes_note") or "").upper()
    if "ETF" not in excluded_note:
        raise DataValidationError("원천의 ETF 제외 범위가 카탈로그에 명시되지 않았습니다")
    top = validate_universe(rows, "aikstockdata")
    metadata = {"snapshot_id": id1 or id2, "quotes_rows": all_count,
                "eligible_markets": market_count, "excluded_nontrading": excluded_nontrade,
                "universe_rule": "금융위 주식시세 KOSPI/KOSDAQ만; ETF 비포함(공급처 카탈로그 명시)"}
    return top, date_index, metadata


def aik_public(session: requests.Session, now_day: date) -> tuple[list[dict], str, dict]:
    payload = []
    for name in ("index.json", "today.json", "quotes.csv"):
        response = session.get(f"{AIK}/{name}", headers=HEADERS, timeout=35)
        response.raise_for_status()
        payload.append(response.content if name.endswith(".csv") else response.json())
    return parse_aik_stock_csv(payload[2], payload[0], payload[1], now_day)


def previous_verified() -> dict | None:
    if not OUT.exists():
        return None
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        good_qualities = {"official_requested_date", "csv_basDt_index_today_match"}
        if (old.get("date_quality") in good_qualities
            and len(old.get("top200") or []) == 200 and old.get("date")):
            return old
    except (ValueError, OSError):
        pass
    return None


def main() -> None:
    now = datetime.now(timezone.utc).astimezone(KST)
    today_day = now.date()
    errors = []
    result = None
    key = os.getenv("KRX_API_KEY", "").strip()
    with requests.Session() as session:
        if key:
            for lag in range(0, 8):
                requested = today_day - timedelta(days=lag)
                if requested.weekday() >= 5:
                    continue
                try:
                    asof = requested.isoformat()
                    rows = official(asof, key, session)
                    result = {"top200": rows, "date": asof,
                              "date_quality": "official_requested_date",
                              "source": "KRX Open API (authenticated daily stock trades)",
                              "source_url": "https://data.krx.co.kr/",
                              "verification": {"universe_rule": "KRX 주식시장 STK/KSQ; ETF/ETN 시세 API 아님"}}
                    break
                except (requests.RequestException, ValueError) as exc:
                    errors.append(f"KRX {requested}: {type(exc).__name__}: {str(exc)[:160]}")
        if result is None:
            try:
                rows, asof, check = aik_public(session, today_day)
                result = {"top200": rows, "date": asof,
                          "date_quality": "csv_basDt_index_today_match",
                          "source": "aikstockdata.com (Financial Services Commission public EOD stock prices)",
                          "source_url": f"{AIK}/quotes.csv",
                          "verification": check}
            except (requests.RequestException, ValueError, UnicodeError, csv.Error) as exc:
                errors.append(f"aikstockdata: {type(exc).__name__}: {str(exc)[:250]}")

    if result is None:
        prior = previous_verified()
        if prior is not None:
            print("Collection failed; keeping previous VERIFIED TOP200 unchanged.")
            for err in errors: print("INFO:", err)
            return
        result = {"top200": [], "date": None, "date_quality": "unverified",
                  "source": "none", "source_url": None, "verification": {}}
        status = "unavailable"
    else:
        status = "verified"

    output = {"collected_at_kst": now.isoformat(), "status": status,
              **result, "market_flows": {}, "errors": errors,
              "notice": ("T+1 EOD stocks only. Trade date verified from source, not collection time. "
                         "Foreign and institutional investor net purchases are NOT in this file. "
                         "aikstockdata license: attribution, noncommercial use only.")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"status={status}, TOP200={len(output['top200'])}, "
          f"trade_date={output['date']}, quality={output['date_quality']}")
    for err in errors[-5:]:
        print("INFO:", err)
    if not output["top200"]:
        raise RuntimeError("No verified TOP200; data file marked unavailable instead of guessing dates.")


if __name__ == "__main__":
    main()
