"""Deterministic regression tests; no network, no future information."""
import copy
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from market_regime_journal import (JournalError, SCHEMA, date_key, validate_prices,
                                    merge_closes, record_journal, evaluate)


D0=date(2026,1,5)  # Monday, synthetic observations, never used as actual market returns.

def rows(days=85, *, movement=True):
    d=D0;dates=[]
    while len(dates)<days:
        if d.weekday()<5:dates.append(d.isoformat())
        d+=timedelta(days=1)
    base={'KOSPI':100.,'KOSDAQ':200.}
    return {market:[{'date':day,'close':base[market]*(1+(i*.01 if movement else 0))}
                    for i,day in enumerate(dates)] for market in base}

def signal(d,code='defensive'):
    return dict(date=d,code=code,reasons=['synthetic test only'],environment='방어 우선')

def observed(d):
    return d+'T20:00:00+09:00'


class TestJournal(unittest.TestCase):
    def test_first_seen_record_frozen(self):
        p=rows(6);d=p['KOSPI'][-1]['date']
        j=record_journal(None,incoming_prices=p,signal=signal(d),observed_at=observed(p['KOSPI'][-1]['date']),through=p['KOSPI'][-1]['date'])
        self.assertEqual(j['schema'],SCHEMA)
        self.assertEqual(len(j['records']),1)
        self.assertEqual(j['records'][0]['code'],'defensive')
        self.assertEqual(j['records'][0]['observed_at_kst'],observed(p['KOSPI'][-1]['date']))
        again=record_journal(j,incoming_prices=p,signal=signal(d,'expansion'),observed_at=observed(p['KOSPI'][-1]['date']),through=p['KOSPI'][-1]['date'])
        self.assertEqual(j,again)
        self.assertEqual(again['records'][0]['code'],'defensive')

    def test_start_no_future_return_before_five(self):
        p=rows(5);d=p['KOSPI'][-1]['date']
        j=record_journal(None,incoming_prices=p,signal=signal(d),observed_at=observed(p['KOSPI'][-1]['date']),through=p['KOSPI'][-1]['date'])
        self.assertEqual(j['records'][0]['forward']['5']['status'],'pending')
        self.assertEqual(j['records'][0]['forward']['5']['completed_sessions'],0)

    def test_returns_mature_only_after_exact_five(self):
        initial=rows(1);p=rows(6);d=initial['KOSPI'][-1]['date']
        j=record_journal(None,incoming_prices=initial,signal=signal(d),observed_at=observed(d),through=d)
        self.assertEqual(j['records'][0]['forward']['5']['status'],'pending')
        j=record_journal(j,incoming_prices=p,signal=None,observed_at=observed(p['KOSPI'][-1]['date']),through=p['KOSPI'][-1]['date'])
        o=j['records'][0]['forward']['5']
        self.assertEqual(o['status'],'mature')
        self.assertEqual(o['sessions'],5)
        self.assertAlmostEqual(o['KOSPI']['return_pct'],5,places=4)
        self.assertEqual(j['records'][0]['forward']['20']['status'],'pending')

    def test_twenty_and_sixty_sessions(self):
        p=rows(61);d=p['KOSPI'][0]['date']
        o=evaluate(p,signal_date=d)
        self.assertEqual(set(o),{'5','20','60'})
        self.assertEqual(o['60']['status'],'mature')
        self.assertAlmostEqual(o['60']['KOSDAQ']['return_pct'],60,places=4)
        self.assertEqual(o['60']['exit_date'],p['KOSDAQ'][60]['date'])

    def test_max_drawdown_from_closed_price_peaks(self):
        p=rows(7,movement=False)
        for market in p:
            for i,v in enumerate([100,110,99,105,80,120,90]):p[market][i]['close']=v
        o=evaluate(p,signal_date=p['KOSPI'][0]['date'])['5']
        self.assertAlmostEqual(o['KOSPI']['max_drawdown_pct'],-27.2727,places=3)
        self.assertAlmostEqual(o['KOSPI']['return_pct'],20)

    def test_withheld_label_kept_but_not_automatically_upgraded(self):
        p=rows(6);d=p['KOSPI'][-1]['date'];today=p['KOSPI'][-1]['date']
        a=record_journal(None,incoming_prices=p,signal=signal(d,'withheld'),observed_at=observed(today),through=today)
        b=record_journal(a,incoming_prices=p,signal=signal(d,'conditional'),observed_at=observed(today),through=today)
        self.assertEqual(b['records'][0]['code'],'withheld')

    def test_price_series_must_be_real_sorted_positive(self):
        p=rows(6)
        p['KOSPI'][1]['date']=p['KOSPI'][0]['date']
        with self.assertRaises(JournalError):validate_prices(p,through=date(2026,2,1))
        p=rows(6);p['KOSPI'][1]['close']=float('nan')
        with self.assertRaises(JournalError):validate_prices(p,through=date(2026,2,1))
        p=rows(6);p['KOSPI'][1]['close']=0
        with self.assertRaises(JournalError):validate_prices(p,through=date(2026,2,1))

    def test_future_close_never_accepted(self):
        with self.assertRaises(JournalError):validate_prices(rows(6),through=date(2026,1,5))

    def test_price_revision_aborts_instead_of_rewriting_history(self):
        p=rows(6);q=copy.deepcopy(p)
        q['KOSPI'][0]['close']*=1.1
        with self.assertRaises(JournalError):merge_closes(p,q,through=date(2026,3,1))

    def test_duplicate_record_date_rejected(self):
        p=rows(6);d=p['KOSPI'][-1]['date'];today=p['KOSPI'][-1]['date']
        old=record_journal(None,incoming_prices=p,signal=signal(d),observed_at=observed(today),through=today)
        old['records'].append(copy.deepcopy(old['records'][0]))
        with self.assertRaises(JournalError):record_journal(old,incoming_prices=p,signal=None,observed_at=observed(today),through=today)

    def test_unmatched_index_day_cannot_complete_forward(self):
        p=rows(7)
        p['KOSDAQ'].pop(3)
        v=evaluate(p,signal_date=p['KOSPI'][0]['date'])
        self.assertEqual(v['5']['status'],'pending')

    def test_wide_calendar_gap_blocks_horizon(self):
        p=rows(6)
        for market in p:
            for row in p[market][3:]:
                row['date']=(date.fromisoformat(row['date'])+timedelta(days=15)).isoformat()
        self.assertEqual(evaluate(p,signal_date=p['KOSPI'][0]['date'])['5']['status'],'pending')

    def test_missing_signal_date_no_outcome(self):
        p=rows(7)
        self.assertEqual(evaluate(p,signal_date='2025-12-25')['5']['status'],'pending')

    def test_timezone_required(self):
        p=rows(6)
        with self.assertRaises(JournalError):record_journal(None,incoming_prices=p,signal=signal(p['KOSPI'][-1]['date']),observed_at='2026-01-12T20:00:00',through='2026-01-12')

    def test_no_retro_future_signal(self):
        p=rows(6);today=p['KOSPI'][-1]['date']
        with self.assertRaises(JournalError):record_journal(None,incoming_prices=p,signal=signal('2030-01-01'),observed_at=observed(today),through=today)

    def test_backdated_label_not_permitted(self):
        p=rows(7);old_date=p['KOSPI'][0]['date'];today=p['KOSPI'][-1]['date']
        with self.assertRaises(JournalError):
            record_journal(None,incoming_prices=p,signal=signal(old_date),observed_at=observed(today),through=today)

    def test_invalid_schema_fails_closed(self):
        p=rows(6);today=p['KOSPI'][-1]['date']
        with self.assertRaises(JournalError):record_journal({'schema':'not-ours'},incoming_prices=p,signal=None,observed_at=observed(today),through=today)

    def test_installer_is_idempotent_with_synthetic_repo(self):
        import importlib.util
        p=ROOT/'scripts/activate_market_regime_journal.py'
        spec=importlib.util.spec_from_file_location('activator',p)
        a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ['scripts','.github/workflows']:
                (root/name).mkdir(parents=True,exist_ok=True)
            # Real marker strings from the deployed repository, minimal mock anchors.
            runner=("ADR=('시장 폭 ADR20 (매동 비공식)','collect_adr_breadth.py','kr_market_adr20.json',False)\n"
                    "def main():\n    active=SOURCES+([KOFIA] if has_official_seed() else [])+[ADR]\n")
            yml=("on:\n  schedule:\n    - cron: '35 9 * * 1-5'\n"
                 "run: python -m pip install --disable-pip-version-check requests pandas numpy\n"
                 "      - name: Collect existing market sources and bounded dated ADR20 in sequence\n"
                 "if: always()\n"
                 "files: data/kr_market_adr20.json miner_breadth.py;\n")
            ui=("def render():\n    with st.expander('실험적 판정 규칙 · 기준값과 독립 보조근거',expanded=False):\n        pass\n")
            (root/'scripts/run_kr_eod_batch.py').write_text(runner)
            (root/'.github/workflows/collect_kr_eod_batch.yml').write_text(yml)
            (root/'market_regime_ui.py').write_text(ui)
            for name in ('market_regime_journal.py','market_regime_journal_ui.py','scripts/collect_market_regime_journal.py'):
                source=ROOT/name
                (root/name).write_text(source.read_text())
            self.assertEqual(a.activate(root),3)
            self.assertEqual(a.activate(root),0)
            self.assertIn('data/kr_market_regime_journal.json',(root/'.github/workflows/collect_kr_eod_batch.yml').read_text())
            self.assertIn('continue-on-error: true',(root/'.github/workflows/collect_kr_eod_batch.yml').read_text())
            self.assertIn('render_journal_history()', (root/'market_regime_ui.py').read_text())
            self.assertNotIn('collect_market_liquidity', (root/'scripts/run_kr_eod_batch.py').read_text())

    def test_activation_missing_anchor_does_not_write(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('activator',ROOT/'scripts/activate_market_regime_journal.py')
        a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'scripts').mkdir();(root/'.github/workflows').mkdir(parents=True)
            old='def main():\n    pass\n'
            (root/'scripts/run_kr_eod_batch.py').write_text(old)
            (root/'.github/workflows/collect_kr_eod_batch.yml').write_text('schedule: no')
            (root/'market_regime_ui.py').write_text('def render():pass')
            for name in ('market_regime_journal.py','market_regime_journal_ui.py','scripts/collect_market_regime_journal.py'):
                (root/name).write_text((ROOT/name).read_text())
            with self.assertRaises(ValueError):a.activate(root)
            self.assertEqual((root/'scripts/run_kr_eod_batch.py').read_text(),old)

if __name__=='__main__':unittest.main()
