"""Market-entry ENVIRONMENT rules for Miner. Not a trading signal.

Pure deterministic logic: no network, no indicators invented, no data interpolation.
Version 1: deliberately conservative and UNBACKTESTED. Distinguishes observed
market conditions from a recommendation to buy/sell a particular security.
"""
from __future__ import annotations
from datetime import date
from typing import Any

RULE_VERSION = 'experiment-v1-2026-11'


def _date(value: Any):
    if hasattr(value, 'date'):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError('날짜가 없거나 유효하지 않습니다')


def verified_adr20(obj: dict | None, *, as_of: date) -> tuple[dict | None, str]:
    """Recompute from exactly the final 20 SAVED trading-day rows."""
    try:
        if not isinstance(obj, dict) or obj.get('status') != 'verified':
            return None, '검증된 ADR20 저장 파일이 없습니다'
        if obj.get('unit') != 'stocks' or obj.get('source') != 'maedong.kr public market breadth (KOSPI+KOSDAQ combined)':
            return None, 'ADR20 원자료의 출처 또는 종목 수 단위를 검증하지 못했습니다'
        h = obj['history']
        if not isinstance(h, list) or len(h) < 20:
            return None, 'ADR20에 필요한 20개 관측일이 부족합니다'
        days = [_date(x['date']) for x in h]
        if days != sorted(set(days)):
            return None, 'ADR20의 일별 날짜가 중복되거나 정렬되지 않았습니다'
        if str(days[-1]) != obj.get('latest_date'):
            return None, 'ADR20 최종 날짜가 저장된 메타데이터와 다릅니다'
        if days[-1] > as_of:
            return None, 'ADR20이 지수 가격보다 미래 날짜입니다'
        if (as_of-days[-1]).days > 7:
            return None, 'ADR20이 지수 가격보다 7일 넘게 지연되어 있습니다'
        recent = h[-20:]
        for row in recent:
            nums = [row.get(k) for k in ('up', 'down', 'flat', 'universe_total')]
            if any(type(n) is not int or n < 0 for n in nums):
                return None, 'ADR20 상승·하락·보합 원자료 형식이 올바르지 않습니다'
            if sum(nums[:3]) != nums[3] or nums[3] < 1400:
                return None, 'ADR20 일별 종목 수가 맞지 않습니다'
        num = sum(r['up'] for r in recent)
        den = sum(r['down'] for r in recent)
        if den <= 0:
            return None, 'ADR20 분모가 0입니다'
        v = round(num/den*100, 2)
        declared = obj.get('adr20', {})
        if (declared.get('days') != 20 or declared.get('start_date') != str(days[-20])
                or declared.get('end_date') != str(days[-1])
                or declared.get('up_sum') != num or declared.get('down_sum') != den
                or abs(float(declared.get('value_pct', -1000))-v) > 0.011):
            return None, 'ADR20 저장 계산값과 원자료 재계산이 다릅니다'
        return {'date': str(days[-1]), 'value': v, 'start': str(days[-20]),
                'up_sum':num, 'down_sum':den, 'days':20}, ''
    except (KeyError,TypeError,ValueError,OverflowError,AttributeError):
        return None, 'ADR20 데이터 검증 중 오류가 발견됐습니다'


def classify_environment(states: dict, audits: dict, adr_obj: dict | None, *, today: date) -> dict:
    """Use ONLY matched, independently verified 2-index QA and dated ADR20.

    Thresholds (80/90/110 ADR, 3/4 DD, 4/6 out of 8 price flags) are
    EXPERIMENTAL guardrails, not validated probabilities or optimized parameters.
    """
    base = {'status':'판정 보류','code':'withheld','date':None,'adr20':None,
            'price_flags':None,'dd_counts':{},'ftd_count':None,
            'reasons':[], 'limits': ['규칙은 실험용으로 백테스트하지 않았음',
                                    '개별 종목 매수·매도 신호나 권장 비중이 아님']}
    def hold(reason):
        base['reasons'].append(reason)
        return base
    try:
        if set(states) != {'KOSPI','KOSDAQ'} or set(audits) != {'KOSPI','KOSDAQ'}:
            return hold('코스피·코스닥 두 지수의 입력이 모두 필요합니다')
        dates = {_date(states[x].get('date')) for x in ('KOSPI','KOSDAQ')}
        if len(dates) != 1:
            return hold('코스피와 코스닥의 가격 기준일이 다릅니다')
        price_date = dates.pop()
        base['date'] = str(price_date)
        if price_date > today or (today-price_date).days > 7:
            return hold('지수 가격이 미래 날짜이거나 7일 넘게 지연됐습니다')
        score = 0
        dd_counts={}
        ftd_count=0
        statuses={}
        for x in ('KOSPI','KOSDAQ'):
            flags=states[x].get('flags')
            if not isinstance(flags, (list,tuple)) or len(flags)!=4:
                return hold(f'{x}: 가격 추세 4개 조건을 검증하지 못했습니다')
            # In the live app the four flags come from Python float comparisons.
            if any(type(f) is not bool for f in flags):
                return hold(f'{x}: 가격 조건 형식이 불명확합니다')
            score += sum(flags)
            q=audits[x]
            if not isinstance(q,dict) or q.get('status')!='verified':
                return hold(f'{x}: DD·FTD 독립검증 보류 — {q.get("reason", "근거 부족") if isinstance(q,dict) else "근거 부족"}')
            if q.get('date') != str(price_date):
                return hold(f'{x}: 독립검증 기준일과 가격 기준일이 다릅니다')
            dd=q.get('dd_count')
            if type(dd) is not int or dd<0 or dd>25:
                return hold(f'{x}: 검증된 DD 개수가 유효하지 않습니다')
            dd_counts[x]=dd
            ftd=q.get('ftd')
            if ftd is not None and (_date(ftd)>price_date or (price_date-_date(ftd)).days > 370):
                return hold(f'{x}: FTD 날짜가 비정상입니다')
            if ftd is not None:
                ftd_count += 1
            statuses[x]=q.get('market_status')
            if statuses[x] not in {'관찰','조정','랠리 시도','상승 확인','상승 압박'}:
                return hold(f'{x}: 시장 상태 코드 미확인')
        adr,why=verified_adr20(adr_obj,as_of=price_date)
        if why:
            return hold(why)
        base.update(price_flags=score,dd_counts=dd_counts,ftd_count=ftd_count,adr20=adr)
        value=adr['value']
        highdd=max(dd_counts.values())
        # Precedence: risk overrides all positive labels.
        if highdd>=4 or (score<=3 and value<80) or (score<=2 and value<100):
            code,status='defensive','방어 우선'
            reasons=['유효 DD 과다 또는 가격 추세 약세와 시장 폭 위축이 겹칩니다',
                     f'추세 {score}/8, 최대 유효 DD {highdd}회, ADR20 {value:.2f}%']
        elif (ftd_count==2 and score>=6 and highdd<=2 and value>=110
              and all(statuses[x]=='상승 확인' for x in statuses)):
            code,status='expansion','매수 확대 조건 검토'
            reasons=['두 지수 모두 검증된 FTD 이후 상승 확인, 유효 DD≤2, 추세≥6/8, ADR20≥110% 조건',
                     '종목별 이익 증가·RS·DI/ADX·ATR 통과를 별도로 요구합니다']
        elif ftd_count>=1 and score>=4 and highdd<=2 and value>=90:
            code,status='conditional','조건부 시험 진입 환경'
            reasons=['검증된 FTD와 일부 가격·시장 폭 회복 신호가 함께 있습니다',
                     '종목 단위 검증이 없으면 실제 매수로 연결하지 않습니다']
        else:
            code,status='watch','반등 관찰 · 신규 매수 신중'
            reasons=['반등이나 지수 개선만으로 추세 회복을 확정하기 어렵습니다',
                     f'추세 {score}/8, 최대 DD {highdd}회, FTD {ftd_count}개 지수, ADR20 {value:.2f}%']
        base.update(code=code,status=status,reasons=reasons)
        return base
    except (KeyError,ValueError,TypeError,AttributeError,OverflowError) as exc:
        return hold(f'입력 데이터 검증 중 오류: {type(exc).__name__}')
