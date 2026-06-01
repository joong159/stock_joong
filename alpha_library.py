import pandas as pd
import numpy as np
import yfinance as yf
from nltk.sentiment.vader import SentimentIntensityAnalyzer

class AlphaFactory:
    """
    김민겸 전략 기반 32개 퀀트 알파(투자 지표) 계산 팩토리
    - df: yfinance에서 다운받은 OHLCV (Open, High, Low, Close, Volume) 데이터프레임
    - info: yfinance에서 다운받은 기업 재무(info) 딕셔너리
    """
    
    # ==========================================
    # [카테고리 1] 추세 추종 및 모멘텀 (1~8)
    # ==========================================
    @staticmethod
    def alpha_1_return_5d(df): 
        return df['Close'].pct_change(5).iloc[-1] * 100
    
    @staticmethod
    def alpha_2_return_20d(df): 
        return df['Close'].pct_change(20).iloc[-1] * 100
    
    @staticmethod
    def alpha_3_return_60d(df): 
        return df['Close'].pct_change(60).iloc[-1] * 100
    
    @staticmethod
    def alpha_4_return_250d(df): 
        return df['Close'].pct_change(250).iloc[-1] * 100
    
    @staticmethod
    def alpha_5_disparity_20d(df): 
        return (df['Close'] / df['Close'].rolling(20).mean()).iloc[-1]
        
    @staticmethod
    def alpha_6_moving_average_alignment(df):
        ma5 = df['Close'].rolling(5).mean().iloc[-1]
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        ma60 = df['Close'].rolling(60).mean().iloc[-1]
        return 1 if (ma5 > ma20 > ma60) else 0
        
    @staticmethod
    def alpha_7_52w_high_position(df): 
        return (df['Close'] / df['High'].rolling(250).max()).iloc[-1]
        
    @staticmethod
    def alpha_8_relative_strength(df, benchmark_df):
        df_val = df['Close'].pct_change(20).iloc[-1]
        bench_val = benchmark_df['Close'].pct_change(20).iloc[-1]
        
        # yfinance 최신 버전의 MultiIndex(Series) 반환 이슈 해결 (단일 스칼라 값으로 추출)
        if isinstance(df_val, pd.Series): df_val = df_val.iloc[0]
        if isinstance(bench_val, pd.Series): bench_val = bench_val.iloc[0]
        return float((df_val - bench_val) * 100)

    # ==========================================
    # [카테고리 2] 가격 반전 및 기술적 지표 (9~16)
    # ==========================================
    @staticmethod
    def alpha_9_rsi(df, period=14):
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean().iloc[-1]
        loss = -delta.where(delta < 0, 0).rolling(window=period).mean().iloc[-1]
        rs = gain / (loss + 1e-8)
        return 100 - (100 / (1 + rs))
        
    @staticmethod
    def alpha_10_bollinger_position(df, period=20):
        ma = df['Close'].rolling(period).mean().iloc[-1]
        std = df['Close'].rolling(period).std().iloc[-1]
        upper, lower = ma + (std * 2), ma - (std * 2)
        return (df['Close'].iloc[-1] - lower) / (upper - lower + 1e-8)
        
    @staticmethod
    def alpha_11_stochastic_k(df, period=14):
        low_min = df['Low'].rolling(period).min().iloc[-1]
        high_max = df['High'].rolling(period).max().iloc[-1]
        return ((df['Close'].iloc[-1] - low_min) / (high_max - low_min + 1e-8)) * 100
        
    @staticmethod
    def alpha_12_williams_r(df, period=14):
        low_min = df['Low'].rolling(period).min().iloc[-1]
        high_max = df['High'].rolling(period).max().iloc[-1]
        return ((high_max - df['Close'].iloc[-1]) / (high_max - low_min + 1e-8)) * -100
        
    @staticmethod
    def alpha_13_volatility_contraction(df, period=20):
        return -1 * df['Close'].pct_change().rolling(period).std().iloc[-1] # 변동성이 작을수록 점수 높음
        
    @staticmethod
    def alpha_14_oversold_5d(df):
        return -1 * df['Close'].pct_change(5).iloc[-1] # 하락폭이 클수록 반등 점수 높음
        
    @staticmethod
    def alpha_15_gap_up_retention(df):
        return ((df['Close'] - df['Open']) / (df['Open'] + 1e-8)).iloc[-1]
        
    @staticmethod
    def alpha_16_macd_osc(df):
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        return (macd - signal).iloc[-1]

    # ==========================================
    # [카테고리 3] 거래량 및 수급 (17~24)
    # ==========================================
    @staticmethod
    def alpha_17_volume_surge(df, period=20):
        return (df['Volume'] / (df['Volume'].rolling(period).mean() + 1e-8)).iloc[-1]
        
    @staticmethod
    def alpha_18_obv(df):
        direction = np.sign(df['Close'].diff())
        return (df['Volume'] * direction).cumsum().iloc[-1]
        
    @staticmethod
    def alpha_19_up_down_volume_ratio(df, period=20):
        direction = np.sign(df['Close'].diff())
        up_vol = np.where(direction > 0, df['Volume'], 0)
        down_vol = np.where(direction < 0, df['Volume'], 0)
        up_sum = pd.Series(up_vol).rolling(period).sum().iloc[-1]
        down_sum = pd.Series(down_vol).rolling(period).sum().iloc[-1]
        return up_sum / (down_sum + 1e-8)
        
    @staticmethod
    def alpha_20_vwap_ratio(df, period=20):
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        vwap = ((typical_price * df['Volume']).rolling(period).sum() / (df['Volume'].rolling(period).sum() + 1e-8)).iloc[-1]
        return df['Close'].iloc[-1] / (vwap + 1e-8)
        
    @staticmethod
    def alpha_21_volume_golden_cross(df):
        return (df['Volume'].rolling(5).mean() / (df['Volume'].rolling(20).mean() + 1e-8)).iloc[-1]
        
    @staticmethod
    def alpha_22_intraday_intensity(df):
        return ((df['Close'] - df['Open']) / (df['High'] - df['Low'] + 1e-8)).iloc[-1]
        
    @staticmethod
    def alpha_23_money_flow_index(df, period=14):
        tp = (df['High'] + df['Low'] + df['Close']) / 3
        rmf = tp * df['Volume']
        pos_sum = pd.Series(np.where(tp.diff() > 0, rmf, 0)).rolling(period).sum().iloc[-1]
        neg_sum = pd.Series(np.where(tp.diff() < 0, rmf, 0)).rolling(period).sum().iloc[-1]
        mfr = pos_sum / (neg_sum + 1e-8)
        return 100 - (100 / (1 + mfr))
        
    @staticmethod
    def alpha_24_turnover_proxy(df, period=20):
        return (df['Volume'].rolling(period).std() / (df['Volume'].rolling(period).mean() + 1e-8)).iloc[-1]

    # ==========================================
    # [카테고리 4] 가치, 배당 및 뉴스 심리 (25~32)
    # ==========================================
    @staticmethod
    def alpha_25_pbr(info): v = info.get('priceToBook'); return -1 * v if v else 0 # 가치 평가는 낮을수록 점수가 높게 음수 처리
    @staticmethod
    def alpha_26_per(info): v = info.get('trailingPE'); return -1 * v if v else 0
    @staticmethod
    def alpha_27_psr(info): v = info.get('priceToSalesTrailing12Months'); return -1 * v if v else 0
    @staticmethod
    def alpha_28_roe(info): return info.get('returnOnEquity', 0)
    @staticmethod
    def alpha_29_operating_margin(info): return info.get('operatingMargins', 0)
    @staticmethod
    def alpha_30_debt_to_equity(info): v = info.get('debtToEquity'); return -1 * v if v else 0
    @staticmethod
    def alpha_31_dividend_yield(info): return info.get('dividendYield', 0)
    
    @staticmethod
    def alpha_32_news_sentiment(ticker_str):
        try:
            news = yf.Ticker(ticker_str).news
            if not news: return 0.0
            sia = SentimentIntensityAnalyzer()
            scores = [sia.polarity_scores(a.get('title', ''))['compound'] for a in news if a.get('title')]
            return sum(scores) / len(scores) if scores else 0.0
        except Exception: return 0.0