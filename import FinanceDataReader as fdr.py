import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from alpha_library import AlphaFactory # 🚀 추가: 알파 무기고 불러오기

# VADER 감성 분석 사전 다운로드 (최초 1회 실행 시 자동 다운로드)
try:
    nltk.data.find('sentiment/vader_lexicon')
except LookupError:
    nltk.download('vader_lexicon', quiet=True)

FINBERT_PIPELINE = None # FinBERT 모델 로딩 캐시용 변수

def fetch_market_data(start_date='2020-01-01'): # 수정: 백테스트를 위해 2020년부터 수집
    """
    시장 가격 및 거시경제 지표를 수집하는 함수
    """
    print("데이터 수집을 시작합니다...")
    
    try:
        # 1. 미국 10년물 국채 금리 (야후 파이낸스 ^TNX 활용 - 안정성 높음)
        rates = yf.download('^TNX', start=start_date)
        
        # 2. S&P 500 지수 (시장 전체 흐름 확인용)
        sp500 = yf.download('^GSPC', start=start_date)
        
        # 3. 공포지수 VIX (투자 심리 확인용)
        vix = yf.download('^VIX', start=start_date)
        
        print("데이터 수집 완료!\n")
        return rates, sp500, vix
        
    except Exception as e:
        print(f"데이터 수집 중 오류가 발생했습니다: {e}")
        return None, None, None

def classify_market_regime(df):
    """
    수집된 데이터를 바탕으로 현재 시장의 '계절(국면)'을 판단하는 함수
    """
    # 1. 지표 계산
    df['MA200'] = df['S&P500_Close'].rolling(window=200).mean() # 200일 장기 추세선
    df['Rate_MA20'] = df['US10Y_Rate'].rolling(window=20).mean() # 금리 추세
    
    # 2. 전체 기간에 대한 국면 결정 (백테스트용)
    def get_regime(row):
        if pd.isna(row['MA200']) or pd.isna(row['Rate_MA20']):
            return "UNKNOWN (데이터 부족)" # 200일이 채워지지 않은 초기 데이터
        
        if row['S&P500_Close'] > row['MA200']:
            if row['VIX_Close'] < 20:
                return "SPRING (적극 매수)"
            else:
                return "SUMMER (선별 매수)"
        else:
            if row['US10Y_Rate'] < row['Rate_MA20']:
                return "AUTUMN (방어 및 관망)"
            else:
                return "WINTER (현금화/숏)"
                
    # DataFrame 전체에 로직 적용하여 'Regime' 컬럼 추가
    df['Regime'] = df.apply(get_regime, axis=1)
    
    # 3. 최근 국면 반환
    return df['Regime'].iloc[-1]

def get_neutralized_alpha(market='SP500'):
    """
    알파 라이브러리의 31개 핵심 지표들을 결합하여 종목을 평가하고,
    업종 평균을 빼서 '순수 실력(Pure Alpha)'을 계산합니다.
    """
    print(f"\n=== [알파 엔진] 31개 멀티 팩터 기반 업종 중립화 데이터 수집 중 ({market}) ===")
    
    benchmark_ticker = '^GSPC' # 기본 벤치마크: S&P 500
    
    if market == 'SP500':
        print("S&P 500 전체 종목을 불러옵니다. (시간이 조금 걸릴 수 있습니다...)")
        sp500_df = fdr.StockListing('S&P500')
        # yfinance 호환을 위해 종목 기호 중 점(.)을 대시(-)로 변경 (예: BRK.B -> BRK-B)
        sp500_df['Symbol'] = sp500_df['Symbol'].str.replace('.', '-', regex=False)
        # 특수기호 없이 BFB, BRKB로 들어오는 경우를 위한 하드코딩 예외 처리 추가
        sp500_df['Symbol'] = sp500_df['Symbol'].replace({'BRKB': 'BRK-B', 'BFB': 'BF-B'})
        stocks = dict(zip(sp500_df['Symbol'], sp500_df['Sector']))
    elif market == 'KRX':
        print("한국 코스피/코스닥 시가총액 상위 100개 종목을 불러옵니다...")
        krx_df = fdr.StockListing('KRX')
        # 섹터(Industry) 정보가 있는 종목 중 상위 100개 추출
        krx_df = krx_df.dropna(subset=['Sector']).head(100)
        
        stocks = {}
        for _, row in krx_df.iterrows():
            code = row['Code']
            market_type = row['Market']
            # 야후 파이낸스 호환성을 위해 코스피는 .KS, 코스닥은 .KQ를 붙여줍니다.
            if 'KOSDAQ' in str(market_type):
                stocks[f"{code}.KQ"] = row['Sector']
            else:
                stocks[f"{code}.KS"] = row['Sector']
        benchmark_ticker = '^KS11' # 한국 벤치마크: 코스피 지수
    else:
        # 1. 테스트용 종목 리스트와 업종 정보
        stocks = {
            'NVDA': 'Technology', 'AAPL': 'Technology', 'MSFT': 'Technology', 'AMD': 'Technology',
            'JPM': 'Financials', 'GS': 'Financials', 'BAC': 'Financials', 'WFC': 'Financials',
            'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy'
        }
    
    tickers = list(stocks.keys())    
    print(f"{len(tickers)}개 종목의 시세 데이터를 다운로드 중...")
    # 시세 데이터 및 벤치마크 일괄 다운로드 (장기 이평선 계산을 위해 2년치)
    # group_by='ticker'는 각 티커별로 DataFrame을 생성하여 딕셔너리 형태로 반환
    # yfinance는 최대 700-800개 티커까지 한 번에 다운로드 가능하지만, 너무 많으면 오류 발생 가능
    # S&P500 전체는 약 500개이므로 가능
    data_ohlcv = yf.download(tickers, period='2y', group_by='ticker', progress=False)
    benchmark_df = yf.download(benchmark_ticker, period='2y', progress=False)
    
    alpha_results = []
    for ticker in tickers:
        try:
            # 종목별 OHLCV 데이터 분리
            # 단일 티커일 경우 data_ohlcv는 DataFrame, 여러 티커일 경우 data_ohlcv[ticker]가 DataFrame
            df_ticker_ohlcv = data_ohlcv[ticker].dropna() if len(tickers) > 1 else data_ohlcv.dropna()

            # 최소 데이터 길이 확인 (가장 긴 250일 이동평균선 계산을 위해)
            if len(df_ticker_ohlcv) < 250:
                # print(f"경고: {ticker}는 250일치 데이터가 부족하여 건너뜁니다.")
                continue
            
            # 기업 재무 정보 (PBR, ROE 등 가치 지표용)
            info = yf.Ticker(ticker).info
            
            # 모든 31개 알파 지표 계산 (Alpha 32는 최종 포트폴리오 선정 후 적용)
            alpha_scores = {
                'Ticker': ticker,
                'Industry': stocks.get(ticker, 'Unknown'),
                'alpha_1': AlphaFactory.alpha_1_return_5d(df_ticker_ohlcv),
                'alpha_2': AlphaFactory.alpha_2_return_20d(df_ticker_ohlcv),
                'alpha_3': AlphaFactory.alpha_3_return_60d(df_ticker_ohlcv),
                'alpha_4': AlphaFactory.alpha_4_return_250d(df_ticker_ohlcv),
                'alpha_5': AlphaFactory.alpha_5_disparity_20d(df_ticker_ohlcv),
                'alpha_6': AlphaFactory.alpha_6_moving_average_alignment(df_ticker_ohlcv),
                'alpha_7': AlphaFactory.alpha_7_52w_high_position(df_ticker_ohlcv),
                'alpha_8': AlphaFactory.alpha_8_relative_strength(df_ticker_ohlcv, benchmark_df),
                'alpha_9': AlphaFactory.alpha_9_rsi(df_ticker_ohlcv),
                'alpha_10': AlphaFactory.alpha_10_bollinger_position(df_ticker_ohlcv),
                'alpha_11': AlphaFactory.alpha_11_stochastic_k(df_ticker_ohlcv),
                'alpha_12': AlphaFactory.alpha_12_williams_r(df_ticker_ohlcv),
                'alpha_13': AlphaFactory.alpha_13_volatility_contraction(df_ticker_ohlcv),
                'alpha_14': AlphaFactory.alpha_14_oversold_5d(df_ticker_ohlcv),
                'alpha_15': AlphaFactory.alpha_15_gap_up_retention(df_ticker_ohlcv),
                'alpha_16': AlphaFactory.alpha_16_macd_osc(df_ticker_ohlcv),
                'alpha_17': AlphaFactory.alpha_17_volume_surge(df_ticker_ohlcv),
                'alpha_18': AlphaFactory.alpha_18_obv(df_ticker_ohlcv),
                'alpha_19': AlphaFactory.alpha_19_up_down_volume_ratio(df_ticker_ohlcv),
                'alpha_20': AlphaFactory.alpha_20_vwap_ratio(df_ticker_ohlcv),
                'alpha_21': AlphaFactory.alpha_21_volume_golden_cross(df_ticker_ohlcv),
                'alpha_22': AlphaFactory.alpha_22_intraday_intensity(df_ticker_ohlcv),
                'alpha_23': AlphaFactory.alpha_23_money_flow_index(df_ticker_ohlcv),
                'alpha_24': AlphaFactory.alpha_24_turnover_proxy(df_ticker_ohlcv),
                'alpha_25': AlphaFactory.alpha_25_pbr(info),
                'alpha_26': AlphaFactory.alpha_26_per(info),
                'alpha_27': AlphaFactory.alpha_27_psr(info),
                'alpha_28': AlphaFactory.alpha_28_roe(info),
                'alpha_29': AlphaFactory.alpha_29_operating_margin(info),
                'alpha_30': AlphaFactory.alpha_30_debt_to_equity(info),
                'alpha_31': AlphaFactory.alpha_31_dividend_yield(info),
            }
            alpha_results.append(alpha_scores)
        except Exception as e:
            # print(f"경고: {ticker} 종목의 알파 계산 중 오류 발생: {e}")
            continue

    df_alpha = pd.DataFrame(alpha_results)
    if df_alpha.empty:
        print("알파 계산을 위한 유효한 종목 데이터가 없습니다.")
        return df_alpha
    df_alpha.set_index('Ticker', inplace=True)
    
    # 결측치(데이터 부족 종목) 제거
    df_alpha.dropna(inplace=True)
    if df_alpha.empty:
        print("결측치 제거 후 유효한 종목 데이터가 없습니다.")
        return df_alpha
    # 3. Z-Score 표준화 (단위가 다른 지표들을 더하기 위해 변환)
    alpha_cols_to_standardize = [f'alpha_{i}' for i in range(1, 32)] # 32번 제외
    
    # 모든 알파 컬럼이 DataFrame에 있는지 확인
    existing_alpha_cols = [col for col in alpha_cols_to_standardize if col in df_alpha.columns]
    
    for col in existing_alpha_cols:
        # std()가 0인 경우 (모든 값이 동일) Z-score 계산 시 NaN이 되므로 예외 처리
        if df_alpha[col].std() == 0:
            df_alpha[f'{col}_Z'] = 0 # 모든 값이 같으면 Z-score는 0
        else:
            df_alpha[f'{col}_Z'] = (df_alpha[col] - df_alpha[col].mean()) / df_alpha[col].std()
        
    # 4. 모든 지표 총합 계산 (멀티 팩터 스코어)
    z_cols = [f'{col}_Z' for col in existing_alpha_cols]
    df_alpha['Total_Score'] = df_alpha[z_cols].sum(axis=1)
    
    # 4. 🔥 핵심: 업종 중립화 (업종 거품 깎아내기)
    # Industry 컬럼이 없는 경우 (예: 단일 종목 테스트) 예외 처리
    if 'Industry' in df_alpha.columns and len(df_alpha['Industry'].unique()) > 1:
        df_alpha['Industry_Mean_Score'] = df_alpha.groupby('Industry')['Total_Score'].transform('mean')
        df_alpha['Pure_Alpha(%)'] = df_alpha['Total_Score'] - df_alpha['Industry_Mean_Score']
    else:
        # 업종 중립화가 불가능하거나 의미 없는 경우 Total_Score를 Pure_Alpha로 사용
        df_alpha['Pure_Alpha(%)'] = df_alpha['Total_Score']
        print("경고: 업종 중립화를 적용할 수 없거나 의미가 없습니다 (단일 업종 또는 Industry 정보 부족).")

    return df_alpha.sort_values(by='Pure_Alpha(%)', ascending=False)

def get_news_sentiment(ticker):
    """
    [Alpha 32] 특정 종목의 최근 뉴스 헤드라인을 수집하여 AI 감성(Sentiment) 점수를 계산합니다.
    점수는 -1(매우 부정적) ~ 1(매우 긍정적) 사이를 반환합니다.
    """
    try:
        news = yf.Ticker(ticker).news
        if not news: 
            return 0.0
            
        try:
            # [딥러닝 AI 적용] transformers 라이브러리가 있다면 금융 특화 AI(FinBERT) 사용
            from transformers import pipeline
            global FINBERT_PIPELINE
            if FINBERT_PIPELINE is None:
                print(f"\n[{ticker}] 🧠 금융 특화 딥러닝 AI (FinBERT) 로드 중... (최초 1회만 소요)")
                FINBERT_PIPELINE = pipeline("sentiment-analysis", model="ProsusAI/finbert")
            
            scores = []
            for article in news:
                title = article.get('title', '')
                if title:
                    result = FINBERT_PIPELINE(title)[0]
                    # FinBERT는 문맥을 이해하고 positive, negative, neutral로 반환합니다.
                    if result['label'] == 'positive':
                        scores.append(result['score'])     # 긍정이면 + 점수
                    elif result['label'] == 'negative':
                        scores.append(-result['score'])    # 부정이면 - 점수
                    else:
                        scores.append(0.0)                 # 중립이면 0 점수
            return sum(scores) / len(scores) if scores else 0.0
            
        except ImportError:
            # 라이브러리가 없다면 기존의 VADER(단어 사전 기반 NLP) 사용
            sia = SentimentIntensityAnalyzer()
            scores = []
            for article in news:
                title = article.get('title', '')
                if title:
                    score = sia.polarity_scores(title)['compound']
                    scores.append(score)
            return sum(scores) / len(scores) if scores else 0.0
    except Exception:
        return 0.0

def generate_portfolio(df_alpha, capital=10000000):
    """
    알파 점수를 바탕으로 투자 비중을 계산하여 최종 포트폴리오를 구성합니다.
    """
    print("\n=== [포트폴리오 구성] 자본금 배분 중 ===")
    
    # 1. 순수 실력이 플러스(+)인 종목만 필터링 후 상위 5개 선정
    top_picks = df_alpha[df_alpha['Pure_Alpha(%)'] > 0].head(5).copy()
    
    if top_picks.empty:
        print("현재 매수할 만한 (Pure Alpha > 0) 종목이 없습니다.")
        return top_picks
        
    # 2. 비중 계산: Pure_Alpha 점수에 비례해서 배분
    weights = (top_picks['Pure_Alpha(%)'] / top_picks['Pure_Alpha(%)'].sum()) * 100
    
    # [추가] 특정 종목 쏠림 방지 (Max Cap 30% 제한 로직)
    max_weight = 30.0
    while weights.max() > max_weight:
        capped_mask = weights >= max_weight
        weights[capped_mask] = max_weight
        non_capped_sum = weights[~capped_mask].sum()
        if non_capped_sum == 0: break
        excess = 100.0 - weights.sum()
        weights[~capped_mask] += excess * (weights[~capped_mask] / non_capped_sum)
        
    top_picks['Weight(%)'] = weights
    
    # 3. 투자 금액 계산 (자본금 기준)
    top_picks['Invest_Amount(KRW)'] = capital * (top_picks['Weight(%)'] / 100)
    
    return top_picks

if __name__ == "__main__":
    rates, sp500, vix = fetch_market_data()
    
    if rates is not None and not rates.empty:
        # 종가(Close) 기준으로 데이터 병합
        market_df = pd.concat([rates['Close'], sp500['Close'], vix['Close']], axis=1)
        market_df.columns = ['US10Y_Rate', 'S&P500_Close', 'VIX_Close']
        
        # 휴장일 차이로 인해 발생한 결측치(NaN)를 이전 영업일 데이터로 채우기
        market_df.ffill(inplace=True)
        
        # 시장 국면 판단 (전체 데이터에 'Regime' 컬럼 추가됨)
        current_regime = classify_market_regime(market_df)
        
        # 최근 5일 데이터 출력
        print("=== 병합된 시장 데이터 및 국면 (최근 5일) ===")
        print(market_df.tail(), "\n")
        
        # 데이터 저장
        market_df.to_excel('market_data.xlsx')
        market_df.to_csv('market_data.csv')
        print("데이터 저장 완료: market_data.xlsx, market_data.csv")
        
        print(f"\n========================================")
        print(f"현재 시장의 계절은: {current_regime} 입니다.")
        print(f"========================================\n")
        
        # 백테스트 통계 출력
        print("=== 과거 4계절 발생 일수 통계 ===")
        print(market_df['Regime'].value_counts())
        
        # 각 국면별 S&P 500 평균 일일 수익률 계산 (백테스트 결과)
        market_df['Next_Day_Return'] = market_df['S&P500_Close'].pct_change().shift(-1) * 100
        print("\n=== 4계절별 S&P 500 평균 일일 수익률 (%) ===")
        regime_returns = market_df.groupby('Regime')['Next_Day_Return'].mean()
        print(regime_returns.round(3))
        
        # --- 유니버스 종목 분석 (현재 국면이 무엇이든 테스트를 위해 실행) ---
        # analyze_stock_universe 함수는 이제 get_neutralized_alpha에 통합되므로 호출하지 않음
        
        # --- [3단계] 업종 중립화 알파 엔진 실행 ---
        # 한국 시장을 테스트하고 싶다면 market='KRX' 로 변경해보세요!
        alpha_results = get_neutralized_alpha(market='SP500')
        print("\n=== 31개 알파 기반 종목별 순수 실력(Pure Alpha) 순위 (상위 15개) ===")
        # 터미널 창이너무 길어지지 않게 15개만 출력
        print(alpha_results[['Industry', 'Return_20d(%)', 'Pure_Alpha(%)']].head(15).round(2).to_string())
        
        alpha_results.to_csv('neutralized_alpha.csv', encoding='utf-8-sig')
        print("\n데이터 저장 완료: neutralized_alpha.csv")
        
        # --- [4단계] 포트폴리오 구성 및 비중 배분 ---
        final_portfolio = generate_portfolio(alpha_results, capital=10000000) # 1,000만원 기준
        if not final_portfolio.empty:
            # 최종 선정된 종목들에 대해서만 AI 뉴스 심리 점수(Alpha 32) 계산
            print("\n=== [Alpha 32] 최종 포트폴리오 종목 AI 뉴스 감성 분석 중 ===")
            final_portfolio['AI_News_Score'] = [get_news_sentiment(ticker) for ticker in final_portfolio.index]
            
            # [추가] 뉴스 심리가 부정적(-점수)인 종목은 투자 비중을 절반으로 깎음 (패널티 적용)
            for ticker in final_portfolio.index:
                if final_portfolio.at[ticker, 'AI_News_Score'] < 0:
                    final_portfolio.at[ticker, 'Weight(%)'] /= 2
                    
            # 비중이 깎였으므로 전체 합이 100%가 되도록 비중 재조정 및 투자금 재계산
            final_portfolio['Weight(%)'] = (final_portfolio['Weight(%)'] / final_portfolio['Weight(%)'].sum()) * 100
            final_portfolio['Invest_Amount(KRW)'] = 10000000 * (final_portfolio['Weight(%)'] / 100)
            
            print("\n" + "="*50)
            print("🚀 김민겸 전략 기반 최종 포트폴리오 제안 (자본금 1,000만원)")
            print("="*50)
            
            # 컬럼 순서 및 출력 포맷 정리
            output_cols = ['Industry', 'Pure_Alpha(%)', 'AI_News_Score', 'Weight(%)', 'Invest_Amount(KRW)']
            print(final_portfolio[output_cols].round(2).to_string())
            
            final_portfolio.to_csv('final_portfolio.csv', encoding='utf-8-sig')
            print("\n데이터 저장 완료: final_portfolio.csv")
