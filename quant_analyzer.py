import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import numpy as np
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from alpha_library import AlphaFactory
import concurrent.futures
import time
import random
import tkinter as tk
from tkinter import filedialog
import os
import json
import threading
import argparse
import sys
from portfolio_state import load_portfolio_state, sync_portfolio_state, save_portfolio_state

# Windows 콘솔 인코딩(CP949 등)으로 인한 출력 오류(UnicodeEncodeError) 방지를 위해 print 함수 오버라이딩
_original_print = print
def print(*args, **kwargs):
    sep = kwargs.get('sep', ' ')
    text = sep.join(str(arg) for arg in args)
    try:
        _original_print(text, **{k: v for k, v in kwargs.items() if k != 'sep'})
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or 'utf-8'
        safe_text = text.encode(encoding, errors='replace').decode(encoding)
        _original_print(safe_text, **{k: v for k, v in kwargs.items() if k != 'sep'})

# VADER 감성 분석 사전 다운로드 (최초 1회 실행 시 자동 다운로드)
try:
    nltk.data.find('sentiment/vader_lexicon')
except LookupError:
    nltk.download('vader_lexicon', quiet=True)

FINBERT_PIPELINE = None # FinBERT 모델 로딩 캐시용 변수

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

try:
    import colorama
    colorama.init()
except ImportError:
    pass

def log_info(msg): print(f"{Colors.CYAN}[INFO] {msg}{Colors.RESET}")
def log_success(msg): print(f"{Colors.GREEN}[SUCCESS] {msg}{Colors.RESET}")
def log_warn(msg): print(f"{Colors.YELLOW}[WARNING] {msg}{Colors.RESET}")
def log_error(msg): print(f"{Colors.RED}[ERROR] {msg}{Colors.RESET}")

# 의존성 없이 로컬 .env 파일을 파싱하는 헬퍼 함수
def load_dotenv(dotenv_path=".env"):
    if os.path.exists(dotenv_path):
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()
        except Exception as e:
            log_warn(f".env 파일을 읽는 중 오류가 발생했습니다: {e}")

CACHE_FILE = '.financials_cache.json'
cache_lock = threading.Lock()

def load_financials_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log_warn(f"캐시 파일을 읽는 중 오류가 발생했습니다: {e}")
        return {}

def save_financials_cache(cache):
    with cache_lock:
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=4)
        except Exception as e:
            log_warn(f"캐시 파일을 저장하는 중 오류가 발생했습니다: {e}")

def get_cached_financials(ticker, cache, ttl_days=7):
    if ticker not in cache:
        return None
    data = cache[ticker]
    timestamp = data.get('timestamp', 0)
    # TTL(기본 7일) 이내 데이터인지 확인
    if time.time() - timestamp < ttl_days * 86400:
        return data.get('info', {})
    return None

def update_cached_financials(ticker, info, cache):
    with cache_lock:
        cache[ticker] = {
            'timestamp': time.time(),
            'info': info
        }
    save_financials_cache(cache)

def print_banner():
    # CP949 인코딩 호환성을 위해 표준 ASCII 문자만 사용하는 안전한 배너 디자인
    banner = fr"""
{Colors.BLUE}================================================================
  ___                 _       ___   ___
 / _ \ _  _ __ _ _ _ | |_    |_  ) / _ \\
| (_) | || / _` | ' \|  _|    / / | (_) |
 \__\_\\_,_\__,_|_||_|\__|   /___(_)___/
         Global Quant & Portfolio Engine
================================================================{Colors.RESET}
    """
    print(banner)

def fetch_market_data(start_date='2020-01-01'):
    log_info("시장 거시경제 지표 데이터를 수집 중...")
    try:
        rates = yf.download('^TNX', start=start_date, progress=False)
        sp500 = yf.download('^GSPC', start=start_date, progress=False)
        vix = yf.download('^VIX', start=start_date, progress=False)
        log_success("거시경제 데이터 수집 완료!")
        return rates, sp500, vix
    except Exception as e:
        log_error(f"거시경제 데이터 수집 중 오류가 발생했습니다: {e}")
        return None, None, None

def classify_market_regime(df):
    df['MA200'] = df['S&P500_Close'].rolling(window=200).mean()
    df['Rate_MA20'] = df['US10Y_Rate'].rolling(window=20).mean()
    
    def get_regime(row):
        if pd.isna(row['MA200']) or pd.isna(row['Rate_MA20']):
            return "UNKNOWN"
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
                
    df['Regime'] = df.apply(get_regime, axis=1)
    return df['Regime'].iloc[-1]

def get_neutralized_alpha(market='SP500', is_test=False, cache=None):
    log_info(f"[알파 엔진] 업종 중립화 분석 중... (Market: {market})")
    
    benchmark_ticker = '^GSPC'
    
    names = {}
    if is_test:
        log_info("테스트용 소형 유니버스를 분석합니다.")
        stocks = {
            'NVDA': 'Technology', 'AAPL': 'Technology', 'MSFT': 'Technology', 'AMD': 'Technology',
            'JPM': 'Financials', 'GS': 'Financials', 'BAC': 'Financials', 'WFC': 'Financials',
            'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy'
        }
        names = {
            'NVDA': '엔비디아', 'AAPL': '애플', 'MSFT': '마이크로소프트', 'AMD': 'AMD',
            'JPM': 'JP모건 체이스', 'GS': '골드만삭스', 'BAC': '뱅크오브아메리카', 'WFC': '웰스파고',
            'XOM': '엑슨모빌', 'CVX': '쉐브론', 'COP': '코노코필립스'
        }
        benchmark_ticker = '^GSPC'
    elif market == 'SP500':
        log_info("S&P 500 전체 종목 정보를 수집합니다.")
        try:
            sp500_df = fdr.StockListing('S&P500')
            sp500_df['Symbol'] = sp500_df['Symbol'].str.replace('.', '-', regex=False)
            sp500_df['Symbol'] = sp500_df['Symbol'].replace({'BRKB': 'BRK-B', 'BFB': 'BF-B'})
            stocks = dict(zip(sp500_df['Symbol'], sp500_df['Sector']))
            names = dict(zip(sp500_df['Symbol'], sp500_df['Name']))
        except Exception as e:
            log_error(f"S&P 500 목록 조회 실패: {e}")
            return pd.DataFrame()
    elif market == 'KRX':
        log_info("KRX 상위 100개 종목 정보를 수집합니다.")
        try:
            krx_df = fdr.StockListing('KRX')
            krx_df = krx_df.dropna(subset=['Sector']).head(100)
            stocks = {}
            names = {}
            for _, row in krx_df.iterrows():
                code = row['Code']
                market_type = row['Market']
                ticker_key = f"{code}.KQ" if 'KOSDAQ' in str(market_type) else f"{code}.KS"
                stocks[ticker_key] = row['Sector']
                names[ticker_key] = row['Name']
            benchmark_ticker = '^KS11'
        except Exception as e:
            log_warn(f"KRX 데이터 수집 실패: {e}. 우량주 20개로 대체합니다.")
            stocks = {
                '005930.KS': 'Technology', '000660.KS': 'Technology', '373220.KS': 'Technology',
                '207940.KS': 'Health Care', '005380.KS': 'Consumer Durables', '000270.KS': 'Consumer Durables',
                '068270.KS': 'Health Care', '051910.KS': 'Basic Materials', '035420.KS': 'Technology',
                '006400.KS': 'Technology', '105560.KS': 'Financials', '055550.KS': 'Financials',
                '028260.KS': 'Financials', '012330.KS': 'Industrials', '066570.KS': 'Consumer Durables',
                '032830.KS': 'Financials', '003670.KS': 'Technology', '033780.KS': 'Technology',
                '011200.KS': 'Industrials', '035720.KS': 'Technology'
            }
            names = {
                '005930.KS': '삼성전자', '000660.KS': 'SK하이닉스', '373220.KS': 'LG에너지솔루션',
                '207940.KS': '삼성바이오로직스', '005380.KS': '현대차', '000270.KS': '기아',
                '068270.KS': '셀트리온', '051910.KS': 'LG화학', '035420.KS': 'NAVER',
                '006400.KS': '삼성SDI', '105560.KS': 'KB금융', '055550.KS': '신한지주',
                '028260.KS': '삼성물산', '012330.KS': '현대모비스', '066570.KS': 'LG전자',
                '032830.KS': '삼성생명', '003670.KS': '포스코퓨처엠', '033780.KS': 'KT&G',
                '011200.KS': 'HMM', '035720.KS': '카카오'
            }
            benchmark_ticker = '^KS11'
    else:
        stocks = {}
        names = {}

    tickers = list(stocks.keys())
    
    log_info(f"유니버스 주가 시세 데이터 다운로드 중 (티커 수: {len(tickers)})...")
    # 중복 다운로드 코드 해결 (단일 호출로 변경)
    data_ohlcv = yf.download(tickers, period='2y', group_by='ticker', progress=True)
    benchmark_df = yf.download(benchmark_ticker, period='2y', progress=False)
    
    if cache is None:
        cache = {}

    def process_ticker(ticker):
        try:
            # 1. 시세 데이터 분할 추출
            if len(tickers) == 1:
                if isinstance(data_ohlcv.columns, pd.MultiIndex):
                    df_ticker_ohlcv = data_ohlcv[ticker].dropna()
                else:
                    df_ticker_ohlcv = data_ohlcv.dropna()
            else:
                if ticker in data_ohlcv.columns.levels[0]:
                    df_ticker_ohlcv = data_ohlcv[ticker].dropna()
                else:
                    return None

            if len(df_ticker_ohlcv) < 250:
                return None
            
            # 2. 기업 재무 정보 획득 (캐시 우선 확인)
            info = get_cached_financials(ticker, cache)
            if info is None:
                # API 부하 방지 및 Rate Limit 대응
                time.sleep(random.uniform(0.1, 0.3))
                raw_info = None
                for attempt in range(3):
                    try:
                        raw_info = yf.Ticker(ticker).info
                        if raw_info:
                            break
                    except Exception:
                        if attempt < 2:
                            time.sleep(2 + attempt * 2)
                if raw_info:
                    info = {
                        'priceToBook': raw_info.get('priceToBook'),
                        'trailingPE': raw_info.get('trailingPE'),
                        'priceToSalesTrailing12Months': raw_info.get('priceToSalesTrailing12Months'),
                        'returnOnEquity': raw_info.get('returnOnEquity'),
                        'operatingMargins': raw_info.get('operatingMargins'),
                        'debtToEquity': raw_info.get('debtToEquity'),
                        'dividendYield': raw_info.get('dividendYield'),
                    }
                    update_cached_financials(ticker, info, cache)
                else:
                    info = {}

            # 3. 알파 지표 계산
            alpha_scores = {
                'Ticker': ticker,
                'Name': names.get(ticker, 'Unknown'),
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
            return alpha_scores
        except Exception:
            return None

    alpha_results = []
    log_info(f"병렬 분석 처리 실행 중 (워커: 3)...")
    completed_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_ticker, t): t for t in tickers}
        for future in concurrent.futures.as_completed(futures):
            completed_count += 1
            if completed_count % 10 == 0 or completed_count == len(tickers):
                log_info(f"진행 상태: {completed_count} / {len(tickers)} 완료")
            res = future.result()
            if res is not None:
                alpha_results.append(res)

    df_alpha = pd.DataFrame(alpha_results)
    if df_alpha.empty:
        log_warn("분석 결과 데이터가 비어 있습니다.")
        return df_alpha
        
    df_alpha.set_index('Ticker', inplace=True)
    
    # 3. 데이터 정제: 가격 데이터가 불충분한 종목만 탈락시키고,
    # 재무 데이터 결측치(PBR, 배당 등)는 전체 평균값으로 대체(Imputation)하여 종목 누락 방지
    price_cols = [f'alpha_{i}' for i in range(1, 25)]
    df_alpha.dropna(subset=price_cols, inplace=True)
    
    if df_alpha.empty:
        log_warn("필수 주가 데이터가 존재하는 주식이 없습니다.")
        return df_alpha
        
    financial_cols = [f'alpha_{i}' for i in range(25, 32)]
    for col in financial_cols:
        if col in df_alpha.columns:
            mean_val = df_alpha[col].mean()
            if pd.isna(mean_val) or mean_val == 0:
                df_alpha[col] = df_alpha[col].fillna(0)
            else:
                df_alpha[col] = df_alpha[col].fillna(mean_val)
                
    # Z-Score 표준화
    alpha_cols_to_standardize = [f'alpha_{i}' for i in range(1, 32)]
    existing_alpha_cols = [c for c in alpha_cols_to_standardize if c in df_alpha.columns]
    
    for col in existing_alpha_cols:
        std_val = df_alpha[col].std()
        if std_val == 0 or pd.isna(std_val):
            df_alpha[f'{col}_Z'] = 0
        else:
            df_alpha[f'{col}_Z'] = (df_alpha[col] - df_alpha[col].mean()) / std_val
            
    z_cols = [f'{col}_Z' for col in existing_alpha_cols]
    df_alpha['Total_Score'] = df_alpha[z_cols].sum(axis=1)
    
    # 업종 중립화 (Pure Alpha 도출)
    if 'Industry' in df_alpha.columns and len(df_alpha['Industry'].unique()) > 1:
        df_alpha['Industry_Mean_Score'] = df_alpha.groupby('Industry')['Total_Score'].transform('mean')
        df_alpha['Pure_Alpha(%)'] = df_alpha['Total_Score'] - df_alpha['Industry_Mean_Score']
    else:
        df_alpha['Pure_Alpha(%)'] = df_alpha['Total_Score']
        log_warn("단일 업종이거나 업종 정보가 없어 중립화를 건너뜁니다.")

    df_alpha['Market'] = 'TEST' if is_test else market
    return df_alpha.sort_values(by='Pure_Alpha(%)', ascending=False)

def get_news_sentiment(ticker):
    try:
        news = yf.Ticker(ticker).news
        if not news: 
            return 0.0
            
        try:
            from transformers import pipeline
            global FINBERT_PIPELINE
            if FINBERT_PIPELINE is None:
                log_info(f"[{ticker}] 🧠 금융 특화 AI (FinBERT) 모델 로딩 중...")
                FINBERT_PIPELINE = pipeline("sentiment-analysis", model="ProsusAI/finbert")
            
            scores = []
            for article in news:
                title = article.get('title', '')
                if title:
                    res = FINBERT_PIPELINE(title)[0]
                    if res['label'] == 'positive':
                        scores.append(res['score'])
                    elif res['label'] == 'negative':
                        scores.append(-res['score'])
                    else:
                        scores.append(0.0)
            return sum(scores) / len(scores) if scores else 0.0
        except ImportError:
            sia = SentimentIntensityAnalyzer()
            scores = []
            for article in news:
                title = article.get('title', '')
                if title:
                    scores.append(sia.polarity_scores(title)['compound'])
            return sum(scores) / len(scores) if scores else 0.0
    except Exception:
        return 0.0

def generate_portfolio(df_alpha, capital=5000000):
    """
    개별 풀(미국/한국) 기준 포트폴리오 비중 배분 및 최고 순위 5개 선정
    """
    positive_alpha = df_alpha[df_alpha['Pure_Alpha(%)'] > 0]
    if positive_alpha.empty:
        log_warn("Pure Alpha가 양수인 종목이 없어 포트폴리오를 구성할 수 없습니다.")
        return positive_alpha
        
    top_picks = positive_alpha.head(5).copy()
    top_picks = top_picks.sort_values(by='Pure_Alpha(%)', ascending=False)
    
    weights = (top_picks['Pure_Alpha(%)'] / top_picks['Pure_Alpha(%)'].sum()) * 100
    
    # 단일 종목 최대 비중 30% 상한 제한
    max_weight = 30.0
    while weights.max() > max_weight:
        capped_mask = weights >= max_weight
        weights[capped_mask] = max_weight
        non_capped_sum = weights[~capped_mask].sum()
        if non_capped_sum == 0: 
            break
        excess = 100.0 - weights.sum()
        weights[~capped_mask] += excess * (weights[~capped_mask] / non_capped_sum)
        
    # 총합 비중을 전체의 50%로 세팅하기 전 임시 100% 분배
    top_picks['Weight(%)'] = weights
    top_picks['Invest_Amount(KRW)'] = capital * (top_picks['Weight(%)'] / 100)
    return top_picks

def export_to_excel(output_filename, df_portfolio, df_alpha, df_market, df_dict, df_rebal=None):
    log_info("엑셀 결과 리포트 저장 중 (스타일링 레이아웃 적용)...")
    try:
        with pd.ExcelWriter(output_filename, engine='xlsxwriter') as writer:
            workbook = writer.book
            
            # 프리미엄 테마 스타일 포맷 정의
            header_format = workbook.add_format({
                'bold': True,
                'font_name': 'Malgun Gothic',
                'font_size': 10,
                'font_color': '#FFFFFF',
                'bg_color': '#1B365D',  # Premium Dark Navy
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'border_color': '#D9D9D9'
            })
            
            cell_format = workbook.add_format({
                'font_name': 'Malgun Gothic',
                'font_size': 10,
                'valign': 'vcenter',
                'border': 1,
                'border_color': '#E0E0E0'
            })
            
            num_format = workbook.add_format({
                'font_name': 'Malgun Gothic',
                'font_size': 10,
                'valign': 'vcenter',
                'align': 'right',
                'border': 1,
                'border_color': '#E0E0E0',
                'num_format': '0.00'
            })
            
            pct_format = workbook.add_format({
                'font_name': 'Malgun Gothic',
                'font_size': 10,
                'valign': 'vcenter',
                'align': 'right',
                'border': 1,
                'border_color': '#E0E0E0',
                'num_format': '0.00"%"'
            })
            
            krw_format = workbook.add_format({
                'font_name': 'Malgun Gothic',
                'font_size': 10,
                'valign': 'vcenter',
                'align': 'right',
                'border': 1,
                'border_color': '#E0E0E0',
                'num_format': '₩#,##0'
            })
            
            center_format = workbook.add_format({
                'font_name': 'Malgun Gothic',
                'font_size': 10,
                'valign': 'vcenter',
                'align': 'center',
                'border': 1,
                'border_color': '#E0E0E0'
            })
            
            # --- Sheet 1. Final Portfolio ---
            ws_port = workbook.add_worksheet('Final Portfolio')
            ws_port.hide_gridlines(2)
            ws_port.write(0, 0, "🚀 최종 추천 포트폴리오 (자본 배분안)", workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#1B365D'}))
            
            df_port_reset = df_portfolio.reset_index().rename(columns={'index': 'Ticker'})
            headers_port = list(df_port_reset.columns)
            ws_port.set_row(2, 25)
            for c_idx, h in enumerate(headers_port):
                ws_port.write(2, c_idx, h, header_format)
                
            for r_idx, row in enumerate(df_port_reset.values):
                ws_port.set_row(3 + r_idx, 20)
                for c_idx, val in enumerate(row):
                    col_name = headers_port[c_idx]
                    if col_name in ['Ticker', 'Name', 'Industry', 'Market']:
                        ws_port.write(3 + r_idx, c_idx, val, center_format if col_name != 'Name' else cell_format)
                    elif col_name in ['Pure_Alpha(%)', 'AI_News_Score']:
                        ws_port.write(3 + r_idx, c_idx, float(val) if pd.notna(val) else 0.0, num_format)
                    elif col_name == 'Weight(%)':
                        ws_port.write(3 + r_idx, c_idx, float(val) if pd.notna(val) else 0.0, pct_format)
                    elif col_name == 'Invest_Amount(KRW)':
                        ws_port.write(3 + r_idx, c_idx, float(val) if pd.notna(val) else 0.0, krw_format)
                    else:
                        ws_port.write(3 + r_idx, c_idx, val, cell_format)
                        
            for col_idx, col in enumerate(df_port_reset.columns):
                max_len = max(df_port_reset[col].astype(str).map(len).max(), len(col)) + 4
                ws_port.set_column(col_idx, col_idx, max(max_len, 15))
                
            # --- Sheet 2. Rebalancing Plan (선택적) ---
            if df_rebal is not None and not df_rebal.empty:
                ws_rebal = workbook.add_worksheet('Rebalancing Plan')
                ws_rebal.hide_gridlines(2)
                ws_rebal.write(0, 0, "🔄 포트폴리오 리밸런싱 주문 계획안", workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#1B365D'}))
                
                df_rebal_reset = df_rebal.reset_index().rename(columns={'index': 'Ticker'})
                headers_rebal = list(df_rebal_reset.columns)
                ws_rebal.set_row(2, 25)
                for c_idx, h in enumerate(headers_rebal):
                    ws_rebal.write(2, c_idx, h, header_format)
                    
                for r_idx, row in enumerate(df_rebal_reset.values):
                    ws_rebal.set_row(3 + r_idx, 20)
                    for c_idx, val in enumerate(row):
                        col_name = headers_rebal[c_idx]
                        if col_name in ['Ticker', 'Name', 'Toss_Symbol', 'Currency', 'Action', 'Reason']:
                            ws_rebal.write(3 + r_idx, c_idx, val, center_format if col_name not in ['Reason', 'Name'] else cell_format)
                        elif col_name in ['Target_Weight(%)']:
                            ws_rebal.write(3 + r_idx, c_idx, float(val) if pd.notna(val) else 0.0, pct_format)
                        elif col_name in ['Target_Value(KRW)', 'Current_Value(KRW)', 'Diff_Value(KRW)']:
                            ws_rebal.write(3 + r_idx, c_idx, float(val) if pd.notna(val) else 0.0, krw_format)
                        elif col_name in ['Current_Qty', 'Target_Qty', 'Diff_Qty']:
                            try:
                                num_val = float(val)
                                ws_rebal.write(3 + r_idx, c_idx, num_val, num_format)
                            except (ValueError, TypeError):
                                ws_rebal.write(3 + r_idx, c_idx, val, cell_format)
                        elif col_name == 'Current_Price':
                            ws_rebal.write(3 + r_idx, c_idx, float(val) if pd.notna(val) else 0.0, num_format)
                        else:
                            ws_rebal.write(3 + r_idx, c_idx, val, cell_format)
                            
                for col_idx, col in enumerate(df_rebal_reset.columns):
                    max_len = max(df_rebal_reset[col].astype(str).map(len).max(), len(col)) + 4
                    ws_rebal.set_column(col_idx, col_idx, max(max_len, 15))

            # --- Sheet 3. Alpha Rankings ---
            ws_rank = workbook.add_worksheet('Alpha Rankings')
            ws_rank.hide_gridlines(2)
            ws_rank.write(0, 0, "📊 전체 분석 대상 종목 알파 랭킹", workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#1B365D'}))
            
            df_rank_reset = df_alpha.reset_index().rename(columns={'index': 'Ticker'})
            df_rank_reset = df_rank_reset.rename(columns={'alpha_2': 'Return_20d(%)'})
            headers_rank = list(df_rank_reset.columns)
            ws_rank.set_row(2, 25)
            for c_idx, h in enumerate(headers_rank):
                ws_rank.write(2, c_idx, h, header_format)
                
            for r_idx, row in enumerate(df_rank_reset.values):
                ws_rank.set_row(3 + r_idx, 18)
                for c_idx, val in enumerate(row):
                    col_name = headers_rank[c_idx]
                    if col_name in ['Ticker', 'Industry', 'Market']:
                        ws_rank.write(3 + r_idx, c_idx, val, center_format)
                    else:
                        try:
                            num_val = float(val)
                            ws_rank.write(3 + r_idx, c_idx, num_val, num_format)
                        except (ValueError, TypeError):
                            ws_rank.write(3 + r_idx, c_idx, val, cell_format)
                            
            for col_idx, col in enumerate(df_rank_reset.columns):
                ws_rank.set_column(col_idx, col_idx, 15)
                
            # --- Sheet 4. Market Regime ---
            ws_market = workbook.add_worksheet('Market Regime')
            ws_market.hide_gridlines(2)
            ws_market.write(0, 0, "🌍 거시경제 시장 데이터 및 국면 (최근 100일)", workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#1B365D'}))
            
            df_m_export = df_market.tail(100).copy()
            df_m_export.index = df_m_export.index.strftime('%Y-%m-%d')
            df_m_reset = df_m_export.reset_index().rename(columns={'index': 'Date'})
            headers_m = list(df_m_reset.columns)
            ws_market.set_row(2, 25)
            for c_idx, h in enumerate(headers_m):
                ws_market.write(2, c_idx, h, header_format)
                
            for r_idx, row in enumerate(df_m_reset.values):
                ws_market.set_row(3 + r_idx, 18)
                for c_idx, val in enumerate(row):
                    col_name = headers_m[c_idx]
                    if col_name in ['Date', 'Regime']:
                        ws_market.write(3 + r_idx, c_idx, val, center_format)
                    else:
                        try:
                            num_val = float(val)
                            ws_market.write(3 + r_idx, c_idx, num_val, num_format)
                        except (ValueError, TypeError):
                            ws_market.write(3 + r_idx, c_idx, val, cell_format)
                            
            for col_idx, col in enumerate(df_m_reset.columns):
                max_len = max(df_m_reset[col].astype(str).map(len).max(), len(col)) + 4
                ws_market.set_column(col_idx, col_idx, max(max_len, 15))
                
            # --- Sheet 5. Alpha Dictionary ---
            ws_dict = workbook.add_worksheet('Alpha Dictionary')
            ws_dict.hide_gridlines(2)
            ws_dict.write(0, 0, "📚 32가지 퀀트 알파 지표 사전", workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#1B365D'}))
            
            headers_dict = list(df_dict.columns)
            ws_dict.set_row(2, 25)
            for c_idx, h in enumerate(headers_dict):
                ws_dict.write(2, c_idx, h, header_format)
                
            for r_idx, row in enumerate(df_dict.values):
                ws_dict.set_row(3 + r_idx, 20)
                for c_idx, val in enumerate(row):
                    if c_idx == 0:
                        ws_dict.write(3 + r_idx, c_idx, val, center_format)
                    else:
                        ws_dict.write(3 + r_idx, c_idx, val, cell_format)
                        
            ws_dict.set_column(0, 0, 30)
            ws_dict.set_column(1, 1, 80)
            
        log_success(f"모든 분석 결과가 프리미엄 디자인이 적용된 다중 시트 엑셀 파일 '{output_filename}'에 저장되었습니다.")
    except Exception as e:
        log_error(f"엑셀 저장 중 오류가 발생했습니다: {e}")

def get_toss_symbol(target_ticker):
    """
    yfinance 티커 코드를 토스증권 API 종목 심볼 규격으로 변환합니다.
    - 예: '005930.KS' -> '005930'
    - 예: 'AAPL' -> 'AAPL'
    """
    if '.' in target_ticker:
        return target_ticker.split('.')[0]
    return target_ticker

def check_chandelier_exit(ticker, current_price, highest_price, data_ohlcv=None):
    """
    Chandelier Exit (ATR 기반 트레일링 스톱) 조건 만족 여부를 검증합니다.
    매도조건: 현재가 < 최고가 - (3 * ATR(14))
    """
    try:
        df_ticker = None
        if data_ohlcv is not None:
            # MultiIndex 컬럼 여부에 따라 안전한 종목 분리 추출
            if isinstance(data_ohlcv.columns, pd.MultiIndex):
                if ticker in data_ohlcv.columns.levels[0]:
                    df_ticker = data_ohlcv[ticker].dropna()
            else:
                df_ticker = data_ohlcv.dropna()
                
        if df_ticker is None or len(df_ticker) < 30:
            # 데이터가 유니버스에 없거나 부족할 때 yfinance로 직접 개별 다운로드
            df_ticker = yf.download(ticker, period='2mo', progress=False).dropna()
            
        if df_ticker.empty or len(df_ticker) < 15:
            return False, 0.0
            
        # ATR(14) 연산 호출
        atr = AlphaFactory.alpha_atr(df_ticker, period=14)
        stop_price = highest_price - (3.0 * atr)
        is_stop_hit = current_price < stop_price
        return is_stop_hit, stop_price
    except Exception as e:
        log_warn(f"[{ticker}] Chandelier Exit 계산 실패: {e}")
        return False, 0.0

def is_us_market_open():
    import datetime
    now = datetime.datetime.now() # KST
    weekday = now.weekday()
    if weekday == 5 and now.hour >= 6:
        return False
    if weekday == 6:
        return False
    if weekday == 0 and now.hour < 9:
        return False
    hour = now.hour
    minute = now.minute
    if hour == 22 and minute >= 30:
        return True
    if hour >= 23:
        return True
    if hour < 6:
        return True
    return False

def is_kr_market_open():
    import datetime
    now = datetime.datetime.now()
    weekday = now.weekday()
    if weekday >= 5:
        return False
    hour = now.hour
    minute = now.minute
    if 9 <= hour < 15:
        return True
    if hour == 15 and minute <= 30:
        return True
    return False


if __name__ == "__main__":
    print_banner()
    
    # CLI 인자 파싱
    parser = argparse.ArgumentParser(description="김민겸 전략 기반 글로벌 퀀트 분석기 (토스증권 API 연동)")
    parser.add_argument('--capital', type=float, default=10000000, help="투자 자본금 (기본값: 10,000,000 KRW, 토스 연동 시 자동 갱신)")
    parser.add_argument('--output', type=str, default=None, help="결과 엑셀 파일 저장 경로 (생략 시 다이얼로그 또는 기본 경로)")
    parser.add_argument('--no-cache', action='store_true', help="캐시를 사용하지 않고 새로 고침")
    parser.add_argument('--test', action='store_true', help="테스트용 소형 유니버스(11개 종목)로 실행")
    parser.add_argument('--execute', action='store_true', help="실제 토스증권 API를 호출하여 매매 주문을 실행")
    parser.add_argument('--market-filter', choices=['KRX', 'SP500'], default=None, help="실행할 시장 필터 (KRX 또는 SP500)")
    args_cli = parser.parse_args()
    
    log_info("퀀트 분석을 시작합니다...")
    
    # .env 로드 및 TOSS API 클라이언트 초기화
    load_dotenv()
    toss_client_id = os.environ.get("TOSS_CLIENT_ID")
    toss_client_secret = os.environ.get("TOSS_CLIENT_SECRET")
    toss_base_url = os.environ.get("TOSS_BASE_URL", "https://openapi.tossinvest.com")
    
    toss_client = None
    if toss_client_id and toss_client_secret and toss_client_id != "your_client_id_here":
        try:
            from toss_api import TossinvestClient
            toss_client = TossinvestClient(toss_client_id, toss_client_secret, toss_base_url)
            log_success("토스증권 API 인증 정보 로드 완료! (자동 연동 시작)")
        except Exception as e:
            log_error(f"토스증권 API 연동 모듈 초기화 실패: {e}")
            toss_client = None
            
    rates, sp500, vix = fetch_market_data()
    
    if rates is not None and not rates.empty:
        # 종가(Close) 기준으로 데이터 병합
        market_df = pd.concat([rates['Close'], sp500['Close'], vix['Close']], axis=1)
        market_df.columns = ['US10Y_Rate', 'S&P500_Close', 'VIX_Close']
        
        # 휴장일 차이로 인해 발생한 결측치(NaN)를 이전 영업일 데이터로 채우기
        market_df.ffill(inplace=True)
        
        # 시장 국면 판단
        current_regime = classify_market_regime(market_df)
        
        print("\n" + "="*60)
        log_success(f"현재 시장의 국면은: {Colors.BOLD}{current_regime}{Colors.RESET} 입니다.")
        print("="*60 + "\n")
        
        # 캐시 로드
        cache = load_financials_cache() if not args_cli.no_cache else {}
        
        # --- 알파 엔진 실행 ---
        if args_cli.test:
            alpha_results = get_neutralized_alpha(is_test=True, cache=cache)
        else:
            log_info("미국 시장(S&P 500) 분석을 시작합니다...")
            alpha_results_sp500 = get_neutralized_alpha(market='SP500', cache=cache)
            log_info("한국 시장(KRX) 분석을 시작합니다...")
            alpha_results_krx = get_neutralized_alpha(market='KRX', cache=cache)
            
            results_to_concat = []
            if not alpha_results_sp500.empty:
                results_to_concat.append(alpha_results_sp500)
            if not alpha_results_krx.empty:
                results_to_concat.append(alpha_results_krx)
            
            if results_to_concat:
                alpha_results = pd.concat(results_to_concat).sort_values(by='Pure_Alpha(%)', ascending=False)
            else:
                alpha_results = pd.DataFrame()
            
        if not alpha_results.empty:
            # 실시간 환율 조회 (미국 주식 및 달러 예수금 계산용)
            usd_krw = 1350.0
            if toss_client:
                try:
                    usd_krw = toss_client.get_exchange_rate(base="USD", quote="KRW")
                    log_info(f"실시간 적용 환율: 1 USD = {usd_krw:,.2f} KRW")
                except Exception:
                    pass

            # --- 투자 자본금(Capital) 및 통화별 예수금 동적 연동 ---
            capital_amount = args_cli.capital
            cash_balance_krw = 0.0
            cash_balance_usd = 0.0
            
            if toss_client:
                log_info("토스증권 계좌에서 실제 예수금(원화 및 달러)을 가져옵니다...")
                try:
                    cash_balance_krw = toss_client.get_buying_power(currency="KRW")
                    log_success(f"실적용 계좌 원화 예수금: {cash_balance_krw:,.0f} KRW")
                except Exception as e:
                    log_warn(f"원화 예수금 로드 실패: {e}.")
                    cash_balance_krw = capital_amount * 0.5
                    
                try:
                    cash_balance_usd = toss_client.get_buying_power(currency="USD")
                    log_success(f"실적용 계좌 달러 예수금: $ {cash_balance_usd:,.2f} USD")
                except Exception as e:
                    log_warn(f"달러 예수금 로드 실패: {e}.")
                    cash_balance_usd = (capital_amount * 0.5) / usd_krw
            else:
                # 시뮬레이터 모드: 원화 자본금의 절반을 원화, 절반을 달러로 가상 세팅
                cash_balance_krw = capital_amount * 0.5
                cash_balance_usd = (capital_amount * 0.5) / usd_krw
                
            # 전체 가용 자본금(원화 환산 총액) 계산
            capital_amount = cash_balance_krw + (cash_balance_usd * usd_krw)
            
            # --- 미국 및 국내 주식 50/50 듀얼 포트폴리오 생성 ---
            us_capital = cash_balance_usd * usd_krw
            kr_capital = cash_balance_krw
            
            if args_cli.test:
                # 테스트 유니버스 분류 (XOM, CVX, COP를 가상 한국주식으로 매핑)
                alpha_results_us = alpha_results[~alpha_results.index.isin(['XOM', 'CVX', 'COP'])]
                alpha_results_kr = alpha_results[alpha_results.index.isin(['XOM', 'CVX', 'COP'])]
            else:
                alpha_results_us = alpha_results_sp500
                alpha_results_kr = alpha_results_krx

            log_info(f"통화별 자본금 설정: 미국 주식(USD계좌 - {cash_balance_usd:,.2f} USD = {us_capital:,.0f} KRW) / 국내 주식(KRW계좌 - {cash_balance_krw:,.0f} KRW)")
            
            portfolio_us = generate_portfolio(alpha_results_us, capital=us_capital)
            portfolio_kr = generate_portfolio(alpha_results_kr, capital=kr_capital)
            
            final_portfolio = pd.concat([portfolio_us, portfolio_kr])
            
            if not final_portfolio.empty:
                # 최종 선정된 종목들에 대해서만 AI 뉴스 심리 점수(Alpha 32) 계산
                log_info("최종 듀얼 포트폴리오 종목 AI 뉴스 감성 분석 중...")
                final_portfolio['AI_News_Score'] = [get_news_sentiment(ticker) for ticker in final_portfolio.index]
                
                # 뉴스 심리가 부정적(-점수)인 종목은 투자 비중을 절반으로 깎음 (패널티 적용)
                for ticker in final_portfolio.index:
                    if final_portfolio.at[ticker, 'AI_News_Score'] < 0:
                        log_warn(f"[{ticker}] 뉴스 감성 점수가 부정적({final_portfolio.at[ticker, 'AI_News_Score']:.2f})이므로 비중을 50% 감축합니다.")
                        final_portfolio.at[ticker, 'Weight(%)'] /= 2
                        
                # 비중 재조정 및 투자금 재계산 (미국 및 국내 자산군별로 각각 50% 내에서 정밀 스케일링)
                if args_cli.test:
                    us_mask = ~final_portfolio.index.isin(['XOM', 'CVX', 'COP'])
                    kr_mask = final_portfolio.index.isin(['XOM', 'CVX', 'COP'])
                else:
                    us_mask = final_portfolio['Market'] == 'SP500'
                    kr_mask = final_portfolio['Market'] == 'KRX'
                    
                if final_portfolio[us_mask].shape[0] > 0:
                    final_portfolio.loc[us_mask, 'Weight(%)'] = (final_portfolio.loc[us_mask, 'Weight(%)'] / final_portfolio.loc[us_mask, 'Weight(%)'].sum()) * 50.0
                if final_portfolio[kr_mask].shape[0] > 0:
                    final_portfolio.loc[kr_mask, 'Weight(%)'] = (final_portfolio.loc[kr_mask, 'Weight(%)'] / final_portfolio.loc[kr_mask, 'Weight(%)'].sum()) * 50.0
                    
                final_portfolio['Invest_Amount(KRW)'] = capital_amount * (final_portfolio['Weight(%)'] / 100)
                
                print("\n" + "="*60)
                log_success(f"🚀 [최종 타겟 듀얼 포트폴리오 (50/50)] 제안 (총 자본금: {capital_amount:,.0f} KRW)")
                print("="*60)
                output_cols = ['Name', 'Market', 'Industry', 'Pure_Alpha(%)', 'AI_News_Score', 'Weight(%)', 'Invest_Amount(KRW)']
                print(final_portfolio[output_cols].round(2).to_string())
                print("="*60 + "\n")
                
                # --- 리밸런싱 주문 수량 계산 및 TOSS API 연동 (느슨한 로테이션 + 샹들리에 에그짓) ---
                df_rebal = pd.DataFrame()
                toss_holdings = []

                if toss_client:
                    log_info("토스증권 계좌의 현재 보유 주식 잔고를 불러옵니다...")
                    try:
                        toss_holdings = toss_client.get_holdings()
                        log_success(f"보유 잔고 조회 완료! (보유 종목 수: {len(toss_holdings)}개)")
                    except Exception as e:
                        log_error(f"보유 잔고를 불러오지 못했습니다: {e}")
                else:
                    # 시뮬레이터 모드: 로컬 파일에서 가상 보유 주식 정보 불러오기
                    log_info("시뮬레이터 모드: 로컬 포트폴리오 상태에서 가상 보유 종목 정보를 불러옵니다...")
                    state = load_portfolio_state()
                    toss_holdings = []
                    for sym, info in state.items():
                        # 원래 화폐 현재가는 yfinance에서 가져옴
                        ticker_name = sym
                        for t in alpha_results.index:
                            if get_toss_symbol(t) == sym:
                                ticker_name = t
                                break
                        price_original = 0.0
                        try:
                            ticker_df = yf.download(ticker_name, period='1d', progress=False)
                            if not ticker_df.empty:
                                price_original = float(ticker_df['Close'].iloc[-1])
                        except Exception:
                            pass
                        
                        is_us = not (ticker_name.endswith('.KS') or ticker_name.endswith('.KQ'))
                        toss_holdings.append({
                            "symbol": sym,
                            "quantity": info.get("purchase_qty", 0.0),
                            "lastPrice": price_original,
                            "currency": "USD" if is_us else "KRW"
                        })
                        
                # TOSS 보유 종목 사전(Dict) 매핑
                holdings_dict = {}
                for item in toss_holdings:
                    sym = item.get("symbol")
                    qty = float(item.get("quantity", 0.0))
                    price = float(item.get("lastPrice", 0.0))
                    currency = item.get("currency", "KRW")
                    
                    price_krw = price * usd_krw if currency == "USD" else price
                    current_val_krw = qty * price_krw
                    
                    holdings_dict[sym] = {
                        "qty": qty,
                        "price_krw": price_krw,
                        "price_original": price,
                        "currency": currency,
                        "val_krw": current_val_krw
                    }
                    
                # 로컬 포트폴리오 상태 동기화 (최고가 갱신 등)
                portfolio_state = sync_portfolio_state(holdings_dict)
                
                # 리밸런싱 조정 테이블 계산
                rebal_data = []
                
                # WINTER 국면 여부 확인 (WINTER 국면일 경우 전량 매도 청산)
                is_winter = "WINTER" in current_regime
                
                # 미국 및 국내 종목별 랭킹 딕셔너리 개별 작성
                us_rank_dict = {ticker: idx + 1 for idx, ticker in enumerate(alpha_results_us.index)}
                kr_rank_dict = {ticker: idx + 1 for idx, ticker in enumerate(alpha_results_kr.index)}
                
                # 보관할 종목 목록 (미국/한국 개별 추적)
                kept_us_symbols = []
                kept_kr_symbols = []
                
                data_ohlcv = locals().get("data_ohlcv", None)
                
                # 1단계: 기존 보유 종목 청산 검토
                for sym, curr in holdings_dict.items():
                    if curr["qty"] <= 0:
                        continue
                        
                    ticker_name = None
                    is_us_stock = True
                    
                    # 미국 유니버스 및 국내 유니버스 전체 매핑 확인
                    for t in alpha_results.index:
                        if get_toss_symbol(t) == sym:
                            ticker_name = t
                            if args_cli.test:
                                is_us_stock = t not in ['XOM', 'CVX', 'COP']
                            else:
                                is_us_stock = t.endswith('.KS') == False and t.endswith('.KQ') == False
                            break
                            
                    if not ticker_name:
                        # 유니버스 외 보유 주식 -> 전량 매도
                        rebal_data.append({
                            "Ticker": f"{sym} (유니버스 외)",
                            "Name": sym,
                            "Toss_Symbol": sym,
                            "Action": "SELL",
                            "Reason": "유니버스 제외 대상 즉시 청산",
                            "Target_Weight(%)": 0.0,
                            "Target_Value(KRW)": 0.0,
                            "Current_Qty": curr["qty"],
                            "Current_Price": curr["price_original"],
                            "Currency": curr["currency"],
                            "Current_Value(KRW)": curr["val_krw"],
                            "Target_Qty": 0.0,
                            "Diff_Qty": -curr["qty"],
                            "Diff_Value(KRW)": -curr["val_krw"]
                        })
                        continue
                        
                    ticker_desc_name = alpha_results.at[ticker_name, 'Name'] if 'Name' in alpha_results.columns else ticker_name
                    
                    if is_winter:
                        # 겨울 국면일 경우 무조건 전량 현금화
                        rebal_data.append({
                            "Ticker": ticker_name,
                            "Name": ticker_desc_name,
                            "Toss_Symbol": sym,
                            "Action": "SELL",
                            "Reason": "WINTER 국면 전환 전량 청산 (Cash is King)",
                            "Target_Weight(%)": 0.0,
                            "Target_Value(KRW)": 0.0,
                            "Current_Qty": curr["qty"],
                            "Current_Price": curr["price_original"],
                            "Currency": curr["currency"],
                            "Current_Value(KRW)": curr["val_krw"],
                            "Target_Qty": 0.0,
                            "Diff_Qty": -curr["qty"],
                            "Diff_Value(KRW)": -curr["val_krw"]
                        })
                        continue
                        
                    # Chandelier Exit 검증
                    state_info = portfolio_state.get(sym, {})
                    highest_price = state_info.get("highest_price", curr["price_original"])
                    
                    is_stop_hit, stop_price = check_chandelier_exit(ticker_name, curr["price_original"], highest_price, data_ohlcv)
                    
                    if is_stop_hit:
                        rebal_data.append({
                            "Ticker": ticker_name,
                            "Name": ticker_desc_name,
                            "Toss_Symbol": sym,
                            "Action": "SELL",
                            "Reason": f"샹들리에 추적손절 청산 (손절가: {stop_price:.2f}, 최고가: {highest_price:.2f})",
                            "Target_Weight(%)": 0.0,
                            "Target_Value(KRW)": 0.0,
                            "Current_Qty": curr["qty"],
                            "Current_Price": curr["price_original"],
                            "Currency": curr["currency"],
                            "Current_Value(KRW)": curr["val_krw"],
                            "Target_Qty": 0.0,
                            "Diff_Qty": -curr["qty"],
                            "Diff_Value(KRW)": -curr["val_krw"]
                        })
                        continue
                        
                    # 느슨한 로테이션 검증
                    rank = us_rank_dict.get(ticker_name, 999) if is_us_stock else kr_rank_dict.get(ticker_name, 999)
                    if rank > 10:
                        rebal_data.append({
                            "Ticker": ticker_name,
                            "Name": ticker_desc_name,
                            "Toss_Symbol": sym,
                            "Action": "SELL",
                            "Reason": f"느슨한 로테이션 청산 (현재 풀 내 순위: {rank}위, TOP 10 밖으로 밀림)",
                            "Target_Weight(%)": 0.0,
                            "Target_Value(KRW)": 0.0,
                            "Current_Qty": curr["qty"],
                            "Current_Price": curr["price_original"],
                            "Currency": curr["currency"],
                            "Current_Value(KRW)": curr["val_krw"],
                            "Target_Qty": 0.0,
                            "Diff_Qty": -curr["qty"],
                            "Diff_Value(KRW)": -curr["val_krw"]
                        })
                        continue
                        
                    # 생존한 종목은 보유 유지
                    if is_us_stock:
                        kept_us_symbols.append(sym)
                    else:
                        kept_kr_symbols.append(sym)
                        
                    rebal_data.append({
                        "Ticker": ticker_name,
                        "Name": ticker_desc_name,
                        "Toss_Symbol": sym,
                        "Action": "HOLD",
                        "Reason": f"보유 유지 (현재 순위: {rank}위, 최고가: {highest_price:.2f})",
                        "Target_Weight(%)": 10.0,
                        "Target_Value(KRW)": curr["val_krw"],
                        "Current_Qty": curr["qty"],
                        "Current_Price": curr["price_original"],
                        "Currency": curr["currency"],
                        "Current_Value(KRW)": curr["val_krw"],
                        "Target_Qty": curr["qty"],
                        "Diff_Qty": 0.0,
                        "Diff_Value(KRW)": 0.0
                    })
                    
                # --- 통화별 실질 자금/예수금 한도 분배 ---
                # 1. 미국 주식 (USD 풀)
                current_us_value_usd = sum(item["qty"] * item["price_original"] for sym, item in holdings_dict.items() if item["currency"] == "USD")
                total_us_assets_usd = cash_balance_usd + current_us_value_usd
                target_val_per_stock_usd = total_us_assets_usd / 5.0
                
                # 2. 국내 주식 (KRW 풀)
                current_kr_value_krw = sum(item["qty"] * item["price_original"] for sym, item in holdings_dict.items() if item["currency"] == "KRW")
                total_kr_assets_krw = cash_balance_krw + current_kr_value_krw
                target_val_per_stock_krw = total_kr_assets_krw / 5.0
                
                log_info(f"📊 [통화별 실질 자금/예수금 한도 분배]")
                log_info(f"  * 미국 주식 (USD): 예수금 ${cash_balance_usd:,.2f} | 주식 ${current_us_value_usd:,.2f} | 총자산 ${total_us_assets_usd:,.2f} (종목당 목표 ${target_val_per_stock_usd:,.2f})")
                log_info(f"  * 국내 주식 (KRW): 예수금 {cash_balance_krw:,.0f}원 | 주식 {current_kr_value_krw:,.0f}원 | 총자산 {total_kr_assets_krw:,.0f}원 (종목당 목표 {target_val_per_stock_krw:,.0f}원)")
                
                # 2단계: 신규 매수 편입 종목 선정 (미국/한국 시장별로 각각 독립적으로 슬롯 충전)
                if not is_winter:
                    # 미국 주식 충전 (가용 슬롯: 5 - kept_us_symbols)
                    us_slots = 5 - len(kept_us_symbols)
                    if us_slots > 0:
                        log_info(f"[미국 포트폴리오] 신규 편입 가능 슬롯: {us_slots}개")
                        top_picks_us = alpha_results_us.head(5).index
                        buy_candidates_us = [t for t in top_picks_us if get_toss_symbol(t) not in kept_us_symbols]
                        to_buy_us = buy_candidates_us[:us_slots]
                        
                        # 실제 달러 예수금(cash_balance_usd) 범위 내에서만 매수 집행
                        per_stock_budget_usd = cash_balance_usd / us_slots if us_slots > 0 else 0.0
                        
                        for ticker in to_buy_us:
                            t_sym = get_toss_symbol(ticker)
                            ticker_desc_name = alpha_results.at[ticker, 'Name'] if 'Name' in alpha_results.columns else ticker
                            price_original = 0.0
                            price_krw = 0.0
                            try:
                                ticker_df = yf.download(ticker, period='1d', progress=False)
                                if not ticker_df.empty:
                                    price_original = float(ticker_df['Close'].iloc[-1])
                                    price_krw = price_original * usd_krw
                            except Exception:
                                pass
                                
                            if price_original > 0.0 and per_stock_budget_usd > 0.0:
                                # 미국 주식은 소수점(금액) 구매가 가능하므로 int() 제한 해제 (최소 1달러 이상 시 허용)
                                target_qty = per_stock_budget_usd / price_original
                                if target_qty > 0.0:
                                    rebal_data.append({
                                        "Ticker": ticker,
                                        "Name": ticker_desc_name,
                                        "Toss_Symbol": t_sym,
                                        "Action": "BUY",
                                        "Reason": f"미국 신규 진입 (달러 예수금 매수, 랭킹 {us_rank_dict.get(ticker, 0)}위)",
                                        "Target_Weight(%)": 10.0,
                                        "Target_Value(KRW)": per_stock_budget_usd * usd_krw,
                                        "Current_Qty": 0.0,
                                        "Current_Price": price_original,
                                        "Currency": "USD",
                                        "Current_Value(KRW)": 0.0,
                                        "Target_Qty": target_qty,
                                        "Diff_Qty": target_qty,
                                        "Diff_Value(KRW)": target_qty * price_original * usd_krw
                                    })
                                    
                    # 국내 주식 충전 (가용 슬롯: 5 - kept_kr_symbols)
                    kr_slots = 5 - len(kept_kr_symbols)
                    if kr_slots > 0:
                        log_info(f"[국내 포트폴리오] 신규 편입 가능 슬롯: {kr_slots}개")
                        top_picks_kr = alpha_results_kr.head(5).index
                        buy_candidates_kr = [t for t in top_picks_kr if get_toss_symbol(t) not in kept_kr_symbols]
                        to_buy_kr = buy_candidates_kr[:kr_slots]
                        
                        # 실제 원화 예수금(cash_balance_krw) 범위 내에서만 매수 집행
                        per_stock_budget_kr = cash_balance_krw / kr_slots if kr_slots > 0 else 0.0
                        
                        for ticker in to_buy_kr:
                            t_sym = get_toss_symbol(ticker)
                            ticker_desc_name = alpha_results.at[ticker, 'Name'] if 'Name' in alpha_results.columns else ticker
                            price_original = 0.0
                            price_krw = 0.0
                            try:
                                ticker_df = yf.download(ticker, period='1d', progress=False)
                                if not ticker_df.empty:
                                    price_original = float(ticker_df['Close'].iloc[-1])
                                    price_krw = price_original
                            except Exception:
                                pass
                                
                            if price_original > 0.0 and per_stock_budget_kr > 0.0:
                                target_qty = int(per_stock_budget_kr / price_original)
                                if target_qty > 0:
                                    rebal_data.append({
                                        "Ticker": ticker,
                                        "Name": ticker_desc_name,
                                        "Toss_Symbol": t_sym,
                                        "Action": "BUY",
                                        "Reason": f"국내 신규 진입 (원화 예수금 매수, 랭킹 {kr_rank_dict.get(ticker, 0)}위)",
                                        "Target_Weight(%)": 10.0,
                                        "Target_Value(KRW)": per_stock_budget_kr,
                                        "Current_Qty": 0.0,
                                        "Current_Price": price_original,
                                        "Currency": "KRW",
                                        "Current_Value(KRW)": 0.0,
                                        "Target_Qty": target_qty,
                                        "Diff_Qty": target_qty,
                                        "Diff_Value(KRW)": target_qty * price_original
                                    })
                                    
                if rebal_data:
                    df_rebal = pd.DataFrame(rebal_data).set_index("Ticker")
                    
                    # 리밸런싱 조정 테이블 출력
                    print("\n" + "="*60)
                    log_success("🔄 듀얼 포트폴리오 (통화별 한도 격리) 리밸런싱 주문 조정 계획안")
                    print("="*60)
                    print_df = df_rebal[['Toss_Symbol', 'Action', 'Current_Qty', 'Target_Qty', 'Diff_Qty', 'Diff_Value(KRW)', 'Reason']].copy()
                    print_df['Diff_Value(KRW)'] = print_df['Diff_Value(KRW)'].map(lambda x: f"{x:,.0f} KRW")
                    print(print_df.to_string())
                    print("="*60 + "\n")
                    
                    # 실제 TOSS 주문 실행
                    if args_cli.execute:
                        if not toss_client:
                            log_error("TOSS API 인증 정보가 구성되지 않아 실제 주문을 보낼 수 없습니다. .env 파일을 세팅해 주세요.")
                        else:
                            log_warn("🚨 토스증권 API를 통해 계좌 실주문을 전송합니다.")
                            kr_open = is_kr_market_open()
                            us_open = is_us_market_open()
                            log_info(f"⏰ 현재 시장 영업 상태: 한국 시장(KRX) - {'영업중' if kr_open else '휴장중'} | 미국 시장(S&P500) - {'영업중' if us_open else '휴장중'}")
                            
                            # 0. 기존 미체결/예약 주문 취소
                            log_info("0단계: 기존 대기 중인 예약/미체결 주문 취소 검토 중...")
                            try:
                                pending_orders = toss_client.get_orders(status="OPEN")
                                if pending_orders:
                                    log_info(f"조회된 대기 주문 수: {len(pending_orders)}개")
                                    # 리밸런싱 대상이거나 분석 대상 유니버스에 속한 종목의 대기 주문을 취소합니다.
                                    symbols_to_cancel = set(df_rebal['Toss_Symbol'].tolist())
                                    cancelled_count = 0
                                    for p_ord in pending_orders:
                                        p_symbol = p_ord.get("symbol")
                                        p_order_id = p_ord.get("orderId")
                                        
                                        is_us = not p_symbol.isdigit()
                                        
                                        # 시장 필터링 적용
                                        if args_cli.market_filter == 'KRX' and is_us:
                                            continue
                                        if args_cli.market_filter == 'SP500' and not is_us:
                                            continue
                                            
                                        if is_us and not us_open:
                                            continue
                                        if not is_us and not kr_open:
                                            continue
                                            
                                        if p_symbol in symbols_to_cancel or any(get_toss_symbol(t) == p_symbol for t in alpha_results.index):
                                            log_warn(f"[{p_symbol}] 대기 중인 기존 예약 주문(ID: {p_order_id}) 취소 요청 중...")
                                            toss_client.cancel_order(p_order_id)
                                            cancelled_count += 1
                                    if cancelled_count > 0:
                                        log_success(f"총 {cancelled_count}개의 대기 주문을 취소 완료했습니다.")
                                        time.sleep(1) # 취소 처리 지연 대기
                                    else:
                                        log_info("취소 대상인 대기 주문이 없습니다.")
                                else:
                                    log_info("대기 중인 예약/미체결 주문이 없습니다.")
                            except Exception as e:
                                log_warn(f"기존 대기 주문 자동 취소 처리 중 오류 발생 (건너뜀): {e}")

                            
                            # 1. 매도 주문 실행 (현금 예수금 확보)
                            log_info("1단계: 매도(SELL) 주문 전송 중...")
                            sell_orders = df_rebal[df_rebal['Diff_Qty'] < 0]
                            for t_name, row in sell_orders.iterrows():
                                sym = row['Toss_Symbol']
                                is_us = not (t_name.endswith('.KS') or t_name.endswith('.KQ'))
                                
                                # 시장 필터링 적용
                                if args_cli.market_filter == 'KRX' and is_us:
                                    continue
                                if args_cli.market_filter == 'SP500' and not is_us:
                                    continue
                                    
                                if is_us:
                                    # 미국 주식은 소수점 수량 매도 지원
                                    qty = abs(float(row['Diff_Qty']))
                                else:
                                    qty = int(abs(row['Diff_Qty']))
                                    
                                if qty <= 0.0: continue
                                
                                if is_us and not us_open:
                                    log_warn(f"[{t_name}] 미국 시장이 휴장 상태이므로 매도 주문을 전송하지 않고 건너뜁니다. (미국 시장 개장 시간: 한국 시간 22:30 ~ 06:00)")
                                    continue
                                if not is_us and not kr_open:
                                    log_warn(f"[{t_name}] 한국 시장이 휴장 상태이므로 매도 주문을 전송하지 않고 건너뜁니다. (한국 시장 개장 시간: 평일 09:00 ~ 15:30)")
                                    continue
                                    
                                log_info(f"[{t_name}] 매도 주문 전송: {qty}주 (사유: {row['Reason']})")
                                try:
                                    res = toss_client.create_order(symbol=sym, side="SELL", quantity=qty, order_type="MARKET")
                                    log_success(f"[{t_name}] 매도 완료! (주문번호: {res.get('orderId')})")
                                    try:
                                        from notion_sync import log_trade_to_notion
                                        val_krw = qty * float(row['Current_Price'])
                                        if is_us:
                                            val_krw *= usd_krw
                                        log_trade_to_notion(symbol=sym, name=row['Name'], side="SELL", qty=qty, price=float(row['Current_Price']), val_krw=val_krw, reason=row['Reason'])
                                    except Exception as ex:
                                        log_warn(f"노션 일지 기록 실패: {ex}")
                                except Exception as e:
                                    log_error(f"[{t_name}] 매도 실패: {e}")
                                    
                            # 2. 매수 주문 실행
                            log_info("2단계: 매수(BUY) 주문 전송 중...")
                            buy_orders = df_rebal[df_rebal['Diff_Qty'] > 0]
                            for t_name, row in buy_orders.iterrows():
                                sym = row['Toss_Symbol']
                                is_us = not (t_name.endswith('.KS') or t_name.endswith('.KQ'))
                                
                                # 시장 필터링 적용
                                if args_cli.market_filter == 'KRX' and is_us:
                                    continue
                                if args_cli.market_filter == 'SP500' and not is_us:
                                    continue
                                    
                                if is_us and not us_open:
                                    log_warn(f"[{t_name}] 미국 시장이 휴장 상태이므로 매수 주문을 전송하지 않고 건너뜁니다. (미국 시장 개장 시간: 한국 시간 22:30 ~ 06:00)")
                                    continue
                                if not is_us and not kr_open:
                                    log_warn(f"[{t_name}] 한국 시장이 휴장 상태이므로 매수 주문을 전송하지 않고 건너뜁니다. (한국 시장 개장 시간: 평일 09:00 ~ 15:30)")
                                    continue
                                    
                                try:
                                    if is_us:
                                        # 미국 주식은 달러 기준 금액 매수 주문 (소수점 구매 실행)
                                        val_usd = float(row.get('Diff_Value(KRW)', 0.0)) / usd_krw
                                        if val_usd >= 1.0:
                                            log_info(f"[{t_name}] 미국 소수점 금액 매수 주문 전송: ${val_usd:.2f} USD (사유: {row['Reason']})")
                                            res = toss_client.create_order(symbol=sym, side="BUY", order_amount=round(val_usd, 2), order_type="MARKET")
                                            log_success(f"[{t_name}] 매수 완료! (주문번호: {res.get('orderId')})")
                                            try:
                                                from notion_sync import log_trade_to_notion
                                                val_krw = float(row.get('Diff_Value(KRW)', 0.0))
                                                log_trade_to_notion(symbol=sym, name=row['Name'], side="BUY", qty=val_usd / float(row['Current_Price']), price=float(row['Current_Price']), val_krw=val_krw, reason=row['Reason'])
                                            except Exception as ex:
                                                log_warn(f"노션 일지 기록 실패: {ex}")
                                        else:
                                            log_warn(f"[{t_name}] 미국 주식 매수 예산(${val_usd:.2f})이 최소 기준인 $1.00 미만이어서 건너뜁니다.")
                                    else:
                                        qty = int(row['Diff_Qty'])
                                        if qty > 0:
                                            log_info(f"[{t_name}] 매수 주문 전송: {qty}주 (사유: {row['Reason']})")
                                            res = toss_client.create_order(symbol=sym, side="BUY", quantity=qty, order_type="MARKET")
                                            log_success(f"[{t_name}] 매수 완료! (주문번호: {res.get('orderId')})")
                                            try:
                                                from notion_sync import log_trade_to_notion
                                                val_krw = qty * float(row['Current_Price'])
                                                log_trade_to_notion(symbol=sym, name=row['Name'], side="BUY", qty=qty, price=float(row['Current_Price']), val_krw=val_krw, reason=row['Reason'])
                                            except Exception as ex:
                                                log_warn(f"노션 일지 기록 실패: {ex}")
                                except Exception as e:
                                    log_error(f"[{t_name}] 매수 실패: {e}")
                                    
                            log_success("포트폴리오 리밸런싱 주문 처리가 마무리되었습니다.")
                    else:
                        # 시뮬레이터 모드 가상 주문 업데이트
                        if not toss_client:
                            log_info("시뮬레이터 모드: 가상 포트폴리오 로컬 상태(.portfolio_state.json)를 업데이트합니다...")
                            new_state = {}
                            for ticker, row in df_rebal.iterrows():
                                act = row['Action']
                                sym = row['Toss_Symbol']
                                if act == "HOLD":
                                    new_state[sym] = portfolio_state.get(sym, {})
                                    new_state[sym]["purchase_qty"] = row['Target_Qty']
                                elif act == "BUY":
                                    new_state[sym] = {
                                        "purchase_date": time.strftime('%Y-%m-%d %H:%M:%S'),
                                        "purchase_price": row['Current_Price'],
                                        "highest_price": row['Current_Price'],
                                        "purchase_qty": row['Target_Qty']
                                    }
                            save_portfolio_state(new_state)
                            log_success("가상 포트폴리오 로컬 상태 파일이 갱신되었습니다.")
                        else:
                            log_info("참고: 실계좌로 리밸런싱 주문을 접수하려면 '--execute' 인자를 추가하세요.")
                            log_info("예: python quant_analyzer.py --execute")
                
                # 윈도우(GUI) 탐색기를 띄워 저장할 폴더 및 파일명 설정
                output_filename = args_cli.output
                if not output_filename:
                    if args_cli.execute:
                        output_filename = 'stock_analysis_results.xlsx'
                    else:
                        try:
                            root = tk.Tk()
                            root.withdraw() # 메인 창 숨기기
                            root.attributes('-topmost', True) # 창을 항상 위로 유지
                            
                            log_info("엑셀 파일을 저장할 위치를 선택해 주세요...")
                            output_filename = filedialog.asksaveasfilename(
                                initialfile='stock_analysis_results.xlsx',
                                title="분석 결과를 저장할 엑셀 파일 위치 선택",
                                defaultextension=".xlsx",
                                filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")]
                            )
                        except Exception as ex:
                            log_warn(f"GUI 환경 탐색기를 실행할 수 없으므로 기본 파일명으로 대체합니다. ({ex})")
                            output_filename = 'stock_analysis_results.xlsx'
                
                if not output_filename:
                    output_filename = 'stock_analysis_results.xlsx'
                    log_warn(f"저장 위치가 선택되지 않아 기본 경로 및 파일명으로 지정합니다: {output_filename}")
                
                # 알파 지표 설명을 담은 데이터프레임 생성
                alpha_descriptions = [
                    {"지표명": "alpha_1", "의미": "5일 수익률 (단기 모멘텀)"},
                    {"지표명": "Return_20d(%) (구 alpha_2)", "의미": "20일 수익률 (중기 모멘텀)"},
                    {"지표명": "alpha_3", "의미": "60일 수익률 (중장기 모멘텀)"},
                    {"지표명": "alpha_4", "의미": "250일 수익률 (장기 모멘텀)"},
                    {"지표명": "alpha_5", "의미": "20일 이격도 (현재가 / 20일 이동평균)"},
                    {"지표명": "alpha_6", "의미": "이동평균선 정배열 여부 (5일 > 20일 > 60일)"},
                    {"지표명": "alpha_7", "의미": "52주 신고가 대비 현재가 위치"},
                    {"지표명": "alpha_8", "의미": "벤치마크(S&P500 등) 대비 상대 강도"},
                    {"지표명": "alpha_9", "의미": "RSI(14) - 상대강도지수"},
                    {"지표명": "alpha_10", "의미": "볼린저 밴드 내 현재가 위치"},
                    {"지표명": "alpha_11", "의미": "스토캐스틱 K(14)"},
                    {"지표명": "alpha_12", "의미": "윌리엄스 %R(14)"},
                    {"지표명": "alpha_13", "의미": "변동성 축소 (20일 변동성의 역수, 낮을수록 높은 점수)"},
                    {"지표명": "alpha_14", "의미": "5일 단기 낙폭 (과매도 반등 노림, 하락폭 클수록 높은 점수)"},
                    {"지표명": "alpha_15", "의미": "갭상승 유지력 ((종가 - 시가) / 시가)"},
                    {"지표명": "alpha_16", "의미": "MACD 오실레이터"},
                    {"지표명": "alpha_17", "의미": "거래량 급증 (현재 거래량 / 20일 평균 거래량)"},
                    {"지표명": "alpha_18", "의미": "OBV (On Balance Volume) 추세"},
                    {"지표명": "alpha_19", "의미": "20일 상승/하락 거래량 비율"},
                    {"지표명": "alpha_20", "의미": "VWAP(거래량 가중 평균가) 대비 현재가 비율"},
                    {"지표명": "alpha_21", "의미": "거래량 5일 이동평균 / 20일 이동평균 골든크로스"},
                    {"지표명": "alpha_22", "의미": "일중 강도 ((종가-시가) / (고가-저가))"},
                    {"지표명": "alpha_23", "의미": "MFI(14) - 자금 흐름 지수"},
                    {"지표명": "alpha_24", "의미": "거래량 회전율 대리 지표 (거래량 변동성 / 평균 거래량)"},
                    {"지표명": "alpha_25", "의미": "PBR (주가순자산비율, 저평가일수록 높은 점수 부여 위해 역수 처리)"},
                    {"지표명": "alpha_26", "의미": "PER (주가수익비율, 저평가일수록 높은 점수 부여 위해 역수 처리)"},
                    {"지표명": "alpha_27", "의미": "PSR (주가매출비율, 저평가일수록 높은 점수 부여 위해 역수 처리)"},
                    {"지표명": "alpha_28", "의미": "ROE (자기자본이익률)"},
                    {"지표명": "alpha_29", "의미": "영업이익률"},
                    {"지표명": "alpha_30", "의미": "부채비율 (낮을수록 높은 점수 부여 위해 역수 처리)"},
                    {"지표명": "alpha_31", "의미": "배당수익률"},
                    {"지표명": "alpha_32 (AI_News_Score)", "의미": "최근 뉴스 AI 감성 분석 점수 (-1 ~ 1)"},
                    {"지표명": "Total_Score", "의미": "알파 지표(1~31)들의 Z-Score(표준화) 총합"},
                    {"지표명": "Industry_Mean_Score", "의미": "해당 종목이 속한 업종(Industry)의 Total_Score 평균"},
                    {"지표명": "Pure_Alpha(%)", "의미": "Total_Score에서 업종 평균을 차감한 순수 종목 점수 (업종 거품 제거)"},
                ]
                df_alpha_dict = pd.DataFrame(alpha_descriptions)
                
                # 프리미엄 엑셀 내보내기 호출
                export_to_excel(output_filename, final_portfolio, alpha_results, market_df, df_alpha_dict, df_rebal)
            else:
                log_warn("최종 포트폴리오를 구성하지 못했습니다.")
        else:
            log_error("알파 계산 결과 데이터가 없습니다.")
    else:
        log_error("거시경제 데이터 수집 실패로 프로그램을 종료합니다.")
