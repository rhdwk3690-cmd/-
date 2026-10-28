    return p.loc[~p.index.duplicated(keep='last')].sort_index()

if refresh:
    get_prices.clear()
    stock_names.clear()

try:
    df=portfolio.copy()
    df['종목']=df['종목'].fillna('').astype(str).str.strip()
    df['비중(%)']=pd.to_numeric(df['비중(%)'],errors='coerce')
    df=df[(df['종목']!='') & df['비중(%)'].notna() & (df['비중(%)']>0)].copy()
    if df.empty:
        st.info('먼저 종목과 비중을 입력하세요.'); st.stop()
    universe=stock_names()
    converted=[]; problems=[]
    for raw in df['종목']:
        ticker,error=resolve_stock(raw,universe)
        converted.append(ticker)
        if error: problems.append(error)
    if problems:
        st.error('종목 검색 오류: '+' / '.join(problems)); st.stop()
    df['티커']=converted
    if df['티커'].duplicated().any():
        st.error('같은 종목이 중복 입력되어 있습니다. 종목명과 티커는 같은 주식일 수 있습니다.'); st.stop()
    total=float(df['비중(%)'].sum())
    if not np.isclose(total,100,atol=.01):
        st.error(f'비중 합계가 {total:.2f}%입니다. 합계를 100%로 맞춰 주세요. 현금은 CASH 또는 현금으로 입력할 수 있습니다.'); st.stop()
    st.caption('인식된 종목: '+ ' · '.join(f'{r["종목"]} → {r["티커"]}' for _,r in df.iterrows()))
    names=df['티커'].tolist()
    market_names=[x for x in names if x!='CASH']
    if not market_names:
        st.info('현금만 보유한 경우 가격 위험 분석 대상이 없습니다.'); st.stop()
    series={};errors=[]
    with st.spinner('가격 자료를 확인하고 위험도를 계산합니다…'):
        for ticker in dict.fromkeys(market_names+[benchmark]):
            try: series[ticker]=get_prices(ticker,period)
            except Exception as e: errors.append(f'{ticker}: {e}')
    if errors:
        st.error('일부 시세를 가져오지 못했습니다. 계산하지 않습니다: '+'; '.join(errors)); st.stop()
    prices=pd.concat({k:series[k] for k in dict.fromkeys(market_names+[benchmark])},axis=1,join='inner').dropna()
    if len(prices)<65:
        st.warning('공통 거래일 자료가 65일 미만이어서 분석할 수 없습니다.'); st.stop()
    returns=prices.pct_change(fill_method=None).dropna()
    w=df.set_index('티커')['비중(%)'].div(100)
    portfolio_returns=sum(returns[ticker]*float(w[ticker]) for ticker in market_names)
    curve=(1+portfolio_returns).cumprod()
    bm_curve=(1+returns[benchmark]).cumprod()
    drawdown=curve/curve.cummax()-1
    maxdd=float(drawdown.min())
    annualvol=float(portfolio_returns.std()*np.sqrt(252))
    concentration=float((w**2).sum())
    latest_date=prices.index[-1].date()
    stale_days=(pd.Timestamp.now(tz='Asia/Seoul').date()-latest_date).days

    st.subheader('② 현재 포트폴리오 위험 요약')
    cols=st.columns(5)
    cols[0].metric('시세 기준일',str(latest_date))
    cols[1].metric('과거 최대 낙폭 (MDD)',f'{maxdd:.1%}')
    cols[2].metric('연환산 변동성',f'{annualvol:.1%}')
    cols[3].metric('최대 종목 비중',f'{w.max():.0%}')
    cols[4].metric('집중도 HHI',f'{concentration:.3f}')
    if stale_days>3: st.warning(f'마지막 공통 시세가 {stale_days}일 전입니다. 최신 위험 판단에 사용하지 마세요.')
    if maxdd<=-warning_limit/100:
        st.error('⚠️ 지정한 경고 낙폭보다 과거 MDD가 큽니다. 위험 예산을 재검토하세요.')
    else:
        st.info('과거 관측 MDD가 경고 수준 이내입니다. 향후 안전하다는 뜻은 아닙니다.')

    left,right=st.columns(2)
    with left:
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=curve.index,y=curve,name='포트폴리오(매일 비중 재조정)'))
        fig.add_trace(go.Scatter(x=bm_curve.index,y=bm_curve,name='비교 지수'))
        fig.update_layout(title='누적 가치 (시작=1)',height=350,margin=dict(l=15,r=15,t=45,b=20))
        st.plotly_chart(fig,use_container_width=True)
    with right:
        fig=go.Figure(go.Scatter(x=drawdown.index,y=drawdown*100,fill='tozeroy',name='포트폴리오 낙폭'))
        fig.add_hline(y=-warning_limit,line_dash='dash',line_color='red')
        fig.update_layout(title='포트폴리오 낙폭 (%)',height=350,margin=dict(l=15,r=15,t=45,b=20))
        st.plotly_chart(fig,use_container_width=True)

    st.subheader('③ 손실 확대 위험 · 동반 하락 확인')
    left,right=st.columns(2)
    with left:
        st.markdown('**종목별 최근 20/60거래일 성과**')
        stats=[]
        display_names=df.set_index('티커')['종목'].to_dict()
        for ticker in market_names:
            p=prices[ticker]
            stats.append({'종목':display_names[ticker], '티커':ticker,'비중(%)':float(w[ticker])*100,
                          '20거래일(%)':(p.iloc[-1]/p.iloc[-21]-1)*100 if len(p)>21 else np.nan,
                          '60거래일(%)':(p.iloc[-1]/p.iloc[-61]-1)*100 if len(p)>61 else np.nan,
                          '60일 실현변동성(%)':returns[ticker].tail(60).std()*np.sqrt(252)*100})
        st.dataframe(pd.DataFrame(stats).round(2),hide_index=True,use_container_width=True)
    with right:
        st.markdown('**최근 60거래일 수익률 상관관계**')
        corr=returns[market_names].tail(60).corr()
        heat=go.Figure(go.Heatmap(z=corr.values,x=corr.columns,y=corr.index,zmin=-1,zmax=1,zmid=0,
                                   colorscale='RdBu',reversescale=True,text=np.round(corr.values,2),texttemplate='%{text}'))
        heat.update_layout(height=340,margin=dict(l=20,r=20,t=10,b=20))
        st.plotly_chart(heat,use_container_width=True)
    st.subheader('④ 과거 스트레스 구간')
    rolling5=(1+portfolio_returns).rolling(5).apply(np.prod,raw=True)-1
    rolling20=(1+portfolio_returns).rolling(20).apply(np.prod,raw=True)-1
    st.write(f'관측 최악 1일: **{portfolio_returns.min():.2%}** · 최악 5거래일: **{rolling5.min():.2%}** · 최악 20거래일: **{rolling20.min():.2%}**')
    st.caption('관측 기간에 한정된 과거 위험 수치로, 미래 최대 손실 한도나 VaR가 아닙니다.')
    st.download_button('📥 위험 계산 일별 자료 CSV',
        pd.DataFrame({'portfolio_return':portfolio_returns,'benchmark_return':returns[benchmark],
                      'drawdown':drawdown}).to_csv(index_label='Date').encode('utf-8-sig'),
        'miner_portfolio_risk.csv','text/csv')
except Exception as exc:
    st.error(f'분석 중 오류가 발생했습니다: {exc}')

st.divider()
st.caption('주의: 매일 동일 비중으로 리밸런싱한 가상 포트폴리오입니다. 실제 계좌 수익률, 매입단가, 세금, 수수료, 환율효과, 실거래 체결은 반영되지 않습니다.')
