import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd

def fetch_market_data(start_date='2024-01-01'):
    """
    시장 가격 및 거시경제 지표를 수집하는 함수
    """
    print("데이터 수집을 시작합니다...")
    
    try:
        # 1. 미국 10년물 국채 금리 (FRED 데이터 활용 - 데이터 신뢰도가 높음)
        rates = fdr.DataReader('FRED:DGS10', start_date)
        
        # 2. S&P 500 지수 (시장 전체 흐름 확인용)
        sp500 = yf.download('^GSPC', start=start_date)
        
        # 3. 공포지수 VIX (투자 심리 확인용)
        vix = yf.download('^VIX', start=start_date)
        
        print("데이터 수집 완료!\n")
        return rates, sp500, vix
        
    except Exception as e:
        print(f"데이터 수집 중 오류가 발생했습니다: {e}")
        return None, None, None

if __name__ == "__main__":
    rates, sp500, vix = fetch_market_data()
    
    if rates is not None:
        # 오늘의 숙제 1: 데이터가 잘 들어오는지 확인
        print("=== 미국 10년물 국채 금리 (최근 5일) ===")
        print(rates.tail(), "\n")
        
        # 💡 오늘의 숙제 2: 데이터를 하나의 데이터프레임으로 묶어서 엑셀로 뽑아보기
        # 종가(Close) 기준으로 데이터 병합
        market_df = pd.concat([rates, sp500['Close'], vix['Close']], axis=1)
        market_df.columns = ['US10Y_Rate', 'S&P500_Close', 'VIX_Close']
        
        # 휴장일 차이로 인해 발생한 결측치(NaN)를 이전 영업일 데이터로 채우기
        market_df.ffill(inplace=True)
        
        # 최근 5일 데이터 출력
        print("=== 병합된 시장 데이터 (최근 5일) ===")
        print(market_df.tail(), "\n")
        
        # 엑셀 및 CSV 파일로 저장
        market_df.to_excel('market_data.xlsx')
        market_df.to_csv('market_data.csv')
        print("성공적으로 market_data.xlsx 및 market_data.csv 파일이 저장되었습니다. 폴더를 확인해 보세요!")
