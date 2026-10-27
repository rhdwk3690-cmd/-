# Fear & Greed 글로벌 마켓 레이더 v3

## 핵심
- 미국 S&P500 / NASDAQ: Yahoo Finance 데이터 자동 조회 (외부 서비스 접속 실패 가능)
- 한국 KOSPI / KOSDAQ: 사용자가 원본 Excel 업로드. 한국 실시간 자동 업데이트 **아님**
- 시장 심리, 추세 조건, Elder, TD custom setup, 비용 민감도, 전략 vs 매수후보유
- Fear & Greed 구간별 미래 수익률 탐색 및 전반/후반 구간별 성과
- 공식 CNN Fear & Greed 지표가 아닌 사용자 정의 지표

## 웹사이트 배포 (GitHub + Streamlit Community Cloud)
1. GitHub 계정을 만들고 **새 GitHub 저장소**를 생성합니다. 처음에는 비공개 repo 사용 가능 여부 등 Streamlit Cloud의 당시 지원 정책을 확인하세요. 민감 자료 업로드 금지.
2. 이 폴더의 `app.py`, `fear_greed_engine.py`, `requirements.txt`, `.streamlit/config.toml` 파일을 **폴더 구조 그대로** 저장소 루트에 업로드합니다. 나머지 README는 선택 사항입니다.
3. https://share.streamlit.io/ 에 로그인 후 **Create app → Deploy a public app from GitHub** (화면 문구는 달라질 수 있음).
4. Repository와 branch 선택, Main file path는 `app.py` 지정 후 Deploy.
5. 생성된 Streamlit URL을 휴대폰에서 열고 즐겨찾기. **이 패키지 자체는 배포를 수행하지 않습니다.**
6. 미국 데이터가 Yahoo Finance의 접속 제한 등으로 조회되지 않으면 미국 CSV 업로드를 사용하세요.

## 로컬 실행
```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## 데이터 규격
- 미국 CSV: `Date,S&P500,NASDAQ,VIX,HYG,IEF` (QQQ,SPY 등 추가 열 있어도 됨)
- 한국 Excel: `KOSPI`, `KOSDAQ` 두 시트와 기존 소스가 요구하던 지표 열. 개인 수급 시트는 선택.
- 외부 서버에 업로드하는 한국 Excel은 서버에서 처리됩니다. 비공개 자료·개인정보를 제거하세요.

## 주의/한계
- F&G는 252거래일 롤링 MinMax(최소 126개 관측치)로 산정하며 종가 기준 신호.
- 계산을 위해 충분한 과거 데이터 필요. 코드는 200일 이동평균 확보 이후 비교.
- 수익률은 종가부터 종가 기반 근사이며 진짜 익일 시가 체결 검증은 아닙니다.
- 70/30 시계열 분리는 동일한 규칙을 비교하는 용도일 뿐, 독립적인 최적화/검증 과정을 의미하지 않습니다.
- 미래 수익률 구간 분석은 관측 기간이 겹치므로 독립 표본이 아닙니다.
- 편도 거래비용은 선택 가능. 슬리피지·세금·환율·추적오차는 별도 반영 필요.
- 공개 클라우드 호스팅 시 앱과 코드가 외부로 공개될 수 있으므로, 본인 계정/정보·API 키는 코드에 절대 기입하지 마세요.
