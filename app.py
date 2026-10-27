"""Fear & Greed investment research dashboard. Run: streamlit run app.py"""
import io
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from fear_greed_engine import load_kr, load_us, metrics, FEE_BPS

st.set_page_config(page_title='Fear & Greed 투자 대시보드', page_icon='📈', layout='wide')
st.title('📈 Fear & Greed | 글로벌 마켓 레이더')
st.markdown('''<style>
.block-container {padding-top: 1.5rem; max-width: 1450px}
[data-testid="stMetric"] {border:1px solid rgba(120,130,150,.24);border-radius:12px;padding:12px}
@media(max-width:720px){.block-container{padding-left:.75rem;padding-right:.75rem}}
</style>''', unsafe_allow_html=True)
st.caption('사용자 제공 지표를 개선한 연구 모델 · 공식 CNN Fear & Greed Index와 다른 자체 산출 지표')

with st.sidebar:
    st.header('데이터 설정')
    region = st.radio('시장', ['미국 (Yahoo Finance)', '한국 (엑셀 업로드)'])
    us_file = None
    kr_file = None
    if region.startswith('미국'):
        method = st.radio('데이터 소스', ['Yahoo Finance 자동 조회', '미국 CSV 업로드'])
        if method.startswith('Yahoo'):
            start = st.date_input('수집 시작일', value=pd.Timestamp('2020-01-01').date(), max_value=pd.Timestamp.today().date())
        else:
            us_file = st.file_uploader('CSV 업로드', type=['csv'], key='us')
            st.caption('필수 열: Date, S&P500, NASDAQ, VIX, HYG, IEF')
    else:
        kr_file = st.file_uploader('원본 한국 시장 엑셀 업로드', type=['xlsx','xls'], key='kr')
        st.caption('필수 시트: KOSPI, KOSDAQ. 원래 코드에서 쓰던 6개 시장 데이터 열 필요.')
    st.divider()
    fee_bps = st.slider('편도 거래비용 (bp)', 0, 50, 5, 1, help='1bp = 0.01%. 포지션 전환마다 차감')
    duration = st.select_slider('차트 표시 기간 (거래일)', options=[60,126,252,504,756], value=252)
    st.caption('전략: 추세 + 심리 + Elder 확인 후 진입, 추세 이탈 등에 청산')

@st.cache_data(ttl=3600, show_spinner='시장 데이터를 가져와 계산하고 있습니다…')
def us_auto(s):
    return load_us(start=s)

@st.cache_data(show_spinner='업로드 데이터를 분석하고 있습니다…')
def us_uploaded(content):
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/'input.csv'; p.write_bytes(content)
        return load_us(csv=str(p))

@st.cache_data(show_spinner='엑셀 파일을 분석하고 있습니다…')
def kr_uploaded(content):
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/'input.xlsx'; p.write_bytes(content)
        return load_kr(str(p))

results = None
try:
    if region.startswith('미국'):
        if method.startswith('Yahoo'):
            if st.button('🔄 최신 데이터 조회 / 갱신', type='primary'):
                us_auto.clear()
            results = us_auto(str(start))
        elif us_file is not None:
            results = us_uploaded(us_file.getvalue())
    elif kr_file is not None:
        results = kr_uploaded(kr_file.getvalue())
except Exception as e:
    st.error(f'데이터를 불러올 수 없습니다: {e}')
    st.info('미국 조회 실패 시 잠시 후 재시도하거나 CSV를 업로드해 주세요. 한국은 원본 엑셀 파일을 올려야 합니다.')
    st.stop()

if not results:
    st.info('왼쪽에서 한국 시장 엑셀을 올리거나, 미국 시장 조회를 선택해 주세요. 실제 데이터가 없으면 임의 수치로 채우지 않습니다.')
    st.stop()

name = st.selectbox('분석 시장', list(results))
df = results[name]
valid = df.dropna(subset=['fg_score','superma']).copy()
if len(valid)<30:
    st.warning('과거 데이터가 부족합니다. 약 200거래일 이상의 일별 데이터와 위험 지표가 필요합니다.')
    st.stop()

latest = valid.iloc[-1]
lastdate = valid.index[-1].strftime('%Y-%m-%d')
signal = '🟢 진입 / 보유' if int(latest['target']) else '⚪ 현금 대기'
fgdelta = float(latest['fg_score']-latest['fg_ema20'])
trend = '상승 추세' if bool(latest['trend_up']) else '추세 미충족'
c1,c2,c3,c4,c5 = st.columns(5)
c1.metric('기준일',lastdate)
c2.metric('Fear & Greed',f"{latest['fg_score']:.1f} / 100",f'EMA 차이 {fgdelta:+.1f}')
c3.metric('EMA20',f"{latest['fg_ema20']:.1f}")
c4.metric('시장 추세',trend)
c5.metric('모델 신호',signal)
st.caption('점수는 국가별 자체 구성·정규화 방식이 달라 시장 간 절대값 직접 비교는 주의해야 합니다.')
if len(valid) and (pd.Timestamp.today().normalize() - valid.index[-1].normalize()).days > 7:
    st.warning('⚠️ 최근 유효한 데이터 기준일이 7일 이상 오래됐습니다. 최신 매매 신호로 사용하지 마세요.')
with st.expander('🔎 오늘 신호가 이렇게 나온 이유', expanded=False):
    checks = pd.DataFrame([
        {'조건':'종가 > 200일선, 20일선 > 60일선','현재':'충족' if bool(latest['trend_up']) else '미충족'},
        {'조건':'F&G > EMA20 및 오실레이터 양수','현재':'충족' if bool(latest['fg_rising']) else '미충족'},
        {'조건':'Elder가 적색이 아님','현재':'충족' if latest['elder'] != 'red' else '미충족'},
        {'조건':'F&G 악화 + Elder 적색 (청산 트리거)','현재':'발생' if bool(latest['fg_falling']) and latest['elder']=='red' else '미발생'},
    ])
    st.dataframe(checks,hide_index=True,use_container_width=True)
    st.caption('신호는 장 마감 이후 확정됩니다. 신호가 없다는 것이 시장 하락을 뜻하지는 않습니다.')


show = valid.tail(duration)
price_col = {'KOSPI':'코스피','KOSDAQ':'코스닥','SP500':'S&P500','NASDAQ':'NASDAQ'}[name]
fig = make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.055,row_heights=[.50,.32,.18],subplot_titles=[f'{name} 가격 · 200일선 · 신호','Fear & Greed · EMA20','F&G 오실레이터 / 포지션'])
fig.add_trace(go.Scatter(x=show.index,y=show[price_col],name='시장 가격',line=dict(color='#94A3B8',width=2)),row=1,col=1)
fig.add_trace(go.Scatter(x=show.index,y=show['ma200'],name='200일선',line=dict(color='#EAB308',width=1.7)),row=1,col=1)
entries=(show['target'].eq(1)&show['target'].shift(1).fillna(0).eq(0))
exits=(show['target'].eq(0)&show['target'].shift(1).fillna(0).eq(1))
fig.add_trace(go.Scatter(x=show.index[entries],y=show.loc[entries,price_col],name='진입 신호(종가)',mode='markers',marker=dict(symbol='triangle-up',size=12,color='#16A34A')),row=1,col=1)
fig.add_trace(go.Scatter(x=show.index[exits],y=show.loc[exits,price_col],name='청산 신호(종가)',mode='markers',marker=dict(symbol='triangle-down',size=12,color='#DC2626')),row=1,col=1)
fig.add_trace(go.Scatter(x=show.index,y=show['fg_score'],name='F&G',line=dict(color='#2563EB',width=2.5)),row=2,col=1)
fig.add_trace(go.Scatter(x=show.index,y=show['fg_ema20'],name='F&G EMA20',line=dict(color='#F97316',width=2)),row=2,col=1)
for level in (20,50,80): fig.add_hline(y=level,line_dash='dot',line_color='gray',opacity=.4,row=2,col=1)
fig.add_trace(go.Bar(x=show.index,y=show['fg_hist']*100,name='오실레이터 ×100',marker_color=np.where(show['fg_hist']>=0,'#22C55E','#EF4444')),row=3,col=1)
fig.update_layout(height=820,hovermode='x unified',legend=dict(orientation='h',y=-.10),margin=dict(l=30,r=30,t=65,b=60))
fig.update_yaxes(range=[0,100],row=2,col=1)
st.plotly_chart(fig,use_container_width=True)
st.caption('▲▼ 신호는 해당 날짜 종가 이후 확정됩니다. 백테스트 포지션은 다음 거래일 수익률부터 적용합니다.')

left,right=st.columns([1.2,1])
with left:
    st.subheader('백테스트 | 전략 vs 매수 후 보유')
    test=valid.copy()
    # Reinitialize at the first fully observable date to avoid pre-test position leakage.
    test['position']=test['target'].shift(1).fillna(0)
    test['turnover']=test['position'].diff().abs().fillna(test['position'].abs())
    test['net_return']=test['position']*test['asset_return']-test['turnover']*fee_bps/10000
    test['equity']=(1+test['net_return']).cumprod()
    test['benchmark']=(1+test['asset_return']).cumprod()
    eq=go.Figure()
    eq.add_trace(go.Scatter(x=test.index,y=test.equity,name='전략(비용 반영)',line=dict(color='#2563EB',width=2.5)))
    eq.add_trace(go.Scatter(x=test.index,y=test.benchmark,name='매수 후 보유',line=dict(color='#F97316',width=2)))
    eq.update_layout(height=325,margin=dict(l=15,r=15,t=10,b=10),yaxis_title='누적 자산 (초기=1)',hovermode='x unified')
    st.plotly_chart(eq,use_container_width=True)
with right:
    st.subheader('성과 비교')
    a=metrics(test,'net_return'); b=metrics(test,'asset_return')
    tbl=pd.DataFrame({'지표':['누적수익률','CAGR','MDD','연환산 변동성','샤프(무위험=0)','포지션 변경 횟수'],
                      '전략':[f"{a.get('total_return',float('nan')):.1%}",f"{a.get('cagr',float('nan')):.1%}",f"{a.get('mdd',float('nan')):.1%}",f"{a.get('annual_vol',float('nan')):.1%}",f"{a.get('sharpe_rf0',float('nan')):.2f}",str(int(test.turnover.sum()))],
                      '단순보유':[f"{b.get('total_return',float('nan')):.1%}",f"{b.get('cagr',float('nan')):.1%}",f"{b.get('mdd',float('nan')):.1%}",f"{b.get('annual_vol',float('nan')):.1%}",f"{b.get('sharpe_rf0',float('nan')):.2f}",'—']})
    st.dataframe(tbl,hide_index=True,use_container_width=True)
    st.caption(f"검증 구간: {test.index[0]:%Y-%m-%d} ~ {test.index[-1]:%Y-%m-%d} · 거래비용 편도 {fee_bps/100:.2f}%")

st.subheader('보조 지표 및 원본 데이터')
l,r=st.columns(2)
with l:
    st.metric('SuperMA 괴리율',f"{latest['gap_pct']:+.2f}%")
    st.metric('Elder Impulse',str(latest['elder']).upper())
with r:
    st.metric('TD Sell (4봉 비교)',int(latest['td_sell4']))
    st.metric('TD Buy (2봉 비교)',int(latest['td_buy2']))
with st.expander('최근 지표와 모든 매매 신호 보기'):
    fields=[price_col,'fg_score','fg_ema20','fg_hist','gap_pct','elder','td_sell4','td_buy2','target','position']
    for k in ['individual_netbuy_trillion','capitulation_candidate']:
        if k in test.columns: fields.append(k)
    st.dataframe(test[fields].tail(120).sort_index(ascending=False),use_container_width=True)
    st.download_button('📥 전체 분석 결과 CSV 받기',test.to_csv(index_label='Date').encode('utf-8-sig'),f'{name}_signals.csv','text/csv')
st.warning('주의: 연구용 백테스트입니다. 종가 신호를 다음 기간 수익률에 적용하는 단순화된 체결 가정이며 슬리피지·시장충격·세금·ETF 추적오차는 미반영입니다. 실거래 성과를 보장하지 않습니다.')


st.divider()
st.subheader('🧪 연구실 | 신호 유효성 검증')
st.caption('현재 신호와 미래 수익률의 관련성을 관찰하는 탐색적 분석입니다. 과거에만 알려진 신호로 그룹을 나누지만 결과를 보고 규칙을 바꾸면 과최적화 위험이 있습니다.')
lookahead = st.selectbox('분석 시계 (거래일)', [5, 10, 20, 60], index=2)
st.caption('미래 수익률은 신호일 종가 이후 구간으로 측정합니다. 실제 종가 체결이 가능했다는 뜻은 아닙니다.')
study = valid.copy()
study['future_return'] = study[price_col].shift(-lookahead) / study[price_col] - 1
study['fg_bucket'] = pd.cut(study['fg_score'],bins=[-1,20,40,60,80,101],labels=['0–20','20–40','40–60','60–80','80–100'])
rows=[]
for label,g in study.dropna(subset=['future_return','fg_bucket']).groupby('fg_bucket', observed=True):
    vals=g['future_return']
    rows.append({'F&G 구간':str(label),'표본 수':len(vals),'평균 미래수익률':vals.mean(),'중앙값':vals.median(),'양(+)의 수익 확률':(vals>0).mean()})
if rows:
    statistics=pd.DataFrame(rows)
    # Convert proportions explicitly for cross-version robust rendering.
    display=statistics.copy()
    for col in ['평균 미래수익률','중앙값','양(+)의 수익 확률']:
        display[col]=display[col].map(lambda v:f'{v:.1%}')
    st.dataframe(display,hide_index=True,use_container_width=True)
else:
    st.info('해당 미래기간을 평가할 수 있는 표본이 없습니다.')
st.caption('주의: 미래 수익률 구간이 겹치는 관측치가 다수라 통계적으로 독립 표본이 아닙니다. 증거력 평가에는 별도 검정과 표본외 검증이 필요합니다.')

st.subheader('📊 표본외 기간 성과 점검')
st.caption('시작일부터 전략 규칙과 정규화 기간은 고정된 상태이며, 여기서 단순히 후반 구간 성과만 따로 봅니다. 전략 개발 데이터와 완전히 분리된 진정한 OOS 검증은 아닙니다.')
cut=int(len(test)*0.7)
segments={'전반 70%':test.iloc[:cut], '후반 30%':test.iloc[cut:]}
out=[]
for period, seg in segments.items():
    if len(seg)<2:continue
    p=metrics(seg,'net_return'); bh=metrics(seg,'asset_return')
    out.append({'구간':period,'기간':f'{seg.index[0]:%Y-%m-%d} ~ {seg.index[-1]:%Y-%m-%d}', '전략 CAGR':f'{p.get("cagr",float("nan")):.1%}', '전략 MDD':f'{p.get("mdd",float("nan")):.1%}', '단순보유 CAGR':f'{bh.get("cagr",float("nan")):.1%}'})
st.dataframe(pd.DataFrame(out),hide_index=True,use_container_width=True)
st.caption('이 앱은 연구·교육용입니다. 실시간 주문, 계좌 연동, 수익 보장을 제공하지 않습니다.')
