"""Offline tests: pure rules, no personal data or real API calls."""
import sys
from datetime import date, timedelta, datetime
from pathlib import Path
import unittest
import tempfile
import ast
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market_regime import verified_adr20, classify_environment

TODAY=date(2026,11,1)
DAY=date(2026,10,30)
SOURCE='maedong.kr public market breadth (KOSPI+KOSDAQ combined)'

def adr(up=1200, down=1000):
    dates=[]
    t=DAY
    while len(dates)<25:
        if t.weekday()<5:dates.append(t)
        t-=timedelta(days=1)
    dates.sort()
    hist=[dict(date=str(d),up=up,down=down,flat=400,universe_total=up+down+400) for d in dates]
    return dict(status='verified',source=SOURCE,unit='stocks',history=hist,latest_date=str(hist[-1]['date']),
                adr20=dict(days=20,start_date=hist[-20]['date'],end_date=hist[-1]['date'],
                           up_sum=up*20,down_sum=down*20,value_pct=round(up/down*100,2)))

def states(score=8,date_value=DAY):
    ks=[True]*min(4,score)+[False]*(4-min(4,score))
    kq=[True]*max(0,score-4)+[False]*(4-max(0,score-4))
    return {'KOSPI':{'date':date_value,'flags':ks},'KOSDAQ':{'date':date_value,'flags':kq}}

def audits(dd=(0,0),ftd=(True,True),state=('상승 확인','상승 확인')):
    return {k:{'status':'verified','date':str(DAY),'dd_count':dd[i],
               'ftd':str(DAY-timedelta(days=5)) if ftd[i] else None,
               'market_status':state[i]} for i,k in enumerate(('KOSPI','KOSDAQ'))}

class TestMarketRegime(unittest.TestCase):
    def test_recompute_adr(self):
        a,e=verified_adr20(adr(),as_of=DAY)
        self.assertFalse(e)
        self.assertEqual(a['value'],120)
    def test_reject_forged_adr(self):
        x=adr();x['adr20']['value_pct']=99
        a,e=verified_adr20(x,as_of=DAY)
        self.assertIsNone(a);self.assertIn('다릅니다',e)
    def test_reject_future_adr(self):
        self.assertIsNone(verified_adr20(adr(),as_of=DAY-timedelta(days=1))[0])
    def test_expansion(self):
        x=classify_environment(states(),audits(),adr(),today=TODAY)
        self.assertEqual(x['code'],'expansion')
    def test_defensive_overrides_ftd(self):
        x=classify_environment(states(),audits(dd=(4,0)),adr(),today=TODAY)
        self.assertEqual(x['code'],'defensive')
    def test_weak_adr_and_trend(self):
        x=classify_environment(states(3),audits(),adr(692,1000),today=TODAY)
        self.assertEqual(x['code'],'defensive')
    def test_weak_adr_strong_trend_still_watch(self):
        x=classify_environment(states(7),audits(),adr(692,1000),today=TODAY)
        self.assertEqual(x['code'],'watch')
    def test_conditional(self):
        x=classify_environment(states(5),audits(ftd=(True,False)),adr(1000,1000),today=TODAY)
        self.assertEqual(x['code'],'conditional')
    def test_no_ftd_not_bullish(self):
        x=classify_environment(states(),audits(ftd=(False,False)),adr(),today=TODAY)
        self.assertEqual(x['code'],'watch')
    def test_missing_qa_withheld(self):
        q=audits();q['KOSPI']['status']='withheld';q['KOSPI']['reason']='source missing'
        self.assertEqual(classify_environment(states(),q,adr(),today=TODAY)['code'],'withheld')
    def test_stale_adr_withheld(self):
        x=adr();shift=timedelta(days=18)
        for row in x['history']:row['date']=str(date.fromisoformat(row['date'])-shift)
        x['latest_date']=x['history'][-1]['date'];x['adr20']['start_date']=x['history'][-20]['date'];x['adr20']['end_date']=x['latest_date']
        self.assertEqual(classify_environment(states(),audits(),x,today=TODAY)['code'],'withheld')
    def test_qa_date_mismatch_withheld(self):
        q=audits();q['KOSPI']['date']='2026-10-29'
        self.assertEqual(classify_environment(states(),q,adr(),today=TODAY)['code'],'withheld')
    def test_index_date_mismatch_withheld(self):
        s=states();s['KOSPI']['date']=DAY-timedelta(days=1)
        self.assertEqual(classify_environment(s,audits(),adr(),today=TODAY)['code'],'withheld')
    def test_datetime_index_dates_are_supported(self):
        s=states();s['KOSPI']['date']=datetime(2026,10,30,0,0)
        self.assertEqual(classify_environment(s,audits(),adr(),today=TODAY)['code'],'expansion')
    def test_gate_script_repeatable_and_fails_closed(self):
        from scripts.activate_market_regime import activate,OLD,NEW
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            summ=tmp/'market_signal_summary.py';summ.write_text('def render():\n'+OLD+'\n    show_official_liquidity()\n    show_flows()\n    show_adr_history(compact=True)\n',encoding='utf8')
            core=tmp/'market_regime.py';core.write_text((root/'market_regime.py').read_text(),encoding='utf8')
            ui=tmp/'market_regime_ui.py';ui.write_text((root/'market_regime_ui.py').read_text(),encoding='utf8')
            self.assertTrue(activate(summ,core,ui))
            self.assertFalse(activate(summ,core,ui))
            self.assertEqual(summ.read_text().count('render_market_environment(states, datasets, oneil_market_state)'),1)
            summ.write_text('def different():\n    pass\n')
            with self.assertRaises(RuntimeError):activate(summ,core,ui)
            self.assertEqual(summ.read_text(),'def different():\n    pass\n')

if __name__=='__main__':unittest.main()
