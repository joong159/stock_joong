import sys
import os
import requests
import datetime
from dotenv import load_dotenv

# Enforce global default timeout of 10s for requests to prevent hangs in yfinance/notion
orig_request = requests.Session.request
def patched_request(self, method, url, *args, **kwargs):
    if 'timeout' not in kwargs:
        kwargs['timeout'] = 10
    return orig_request(self, method, url, *args, **kwargs)
requests.Session.request = patched_request

# Ensure we import from the local folder
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from notion_sync import find_database_by_name, sync_market_news_to_notion, HEADERS
from dashboard import fetch_stock_news

def get_active_symbols_from_notion():
    """
    노션 '실시간 보유 잔고 현황' 및 '💡 퀀트 추천 포트폴리오' 데이터베이스에서 현재 모니터링할 종목 목록을 조회합니다.
    """
    holdings_db_id = find_database_by_name("실시간 보유 잔고 현황")
    portfolio_db_id = find_database_by_name("💡 퀀트 추천 포트폴리오")
    
    symbols_map = {} # {symbol: name}
    
    # 1. 실시간 보유 잔고 현황 조회
    if holdings_db_id:
        url = f"https://api.notion.com/v1/databases/{holdings_db_id}/query"
        try:
            res = requests.post(url, headers=HEADERS, json={"page_size": 100}, timeout=10)
            if res.status_code == 200:
                for page in res.json().get("results", []):
                    props = page.get("properties", {})
                    sym_list = props.get("Symbol", {}).get("rich_text", [])
                    symbol = sym_list[0].get("text", {}).get("content", "") if sym_list else ""
                    name_list = props.get("Name", {}).get("title", [])
                    name = name_list[0].get("text", {}).get("content", "") if name_list else ""
                    if symbol and name:
                        symbols_map[symbol] = name
        except Exception as e:
            print(f"실시간 보유 잔고 조회 실패: {e}", flush=True)
                    
    # 2. 퀀트 추천 포트폴리오 조회 (추가/보완)
    if portfolio_db_id:
        url = f"https://api.notion.com/v1/databases/{portfolio_db_id}/query"
        try:
            res = requests.post(url, headers=HEADERS, json={"page_size": 100}, timeout=10)
            if res.status_code == 200:
                for page in res.json().get("results", []):
                    props = page.get("properties", {})
                    sym_list = props.get("Symbol", {}).get("rich_text", [])
                    symbol = sym_list[0].get("text", {}).get("content", "") if sym_list else ""
                    name_list = props.get("Name", {}).get("title", [])
                    name = name_list[0].get("text", {}).get("content", "") if name_list else ""
                    if symbol and name:
                        symbols_map[symbol] = name
        except Exception as e:
            print(f"추천 포트폴리오 조회 실패: {e}", flush=True)
                    
    # 3. 만약 모두 비어있다면 디폴트 주요 종목으로 폴백 (최소한의 뉴스 보장)
    if not symbols_map:
        symbols_map = {
            "005930.KS": "삼성전자",
            "000660.KS": "SK하이닉스",
            "AAPL": "Apple Inc.",
            "NVDA": "NVIDIA Corp.",
            "TSLA": "Tesla Inc."
        }
        
    return list(symbols_map.items())

def main():
    print(f"=== [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 실시간 뉴스 수집 시작 ===", flush=True)
    load_dotenv()
    
    # 1. 모니터링할 종목 목록 추출
    targets = get_active_symbols_from_notion()
    print(f"모니터링 대상 종목: {[t[0] for t in targets]}", flush=True)
    
    # 2. 각 종목별 실시간 뉴스 수집 (국장은 Google News RSS, 미장은 yfinance + Google News RSS 폴백)
    aggregated_news = []
    for symbol, name in targets:
        print(f"[{symbol} - {name}] 뉴스 수집 중...", flush=True)
        try:
            ticker_news = fetch_stock_news(symbol, name)
            if ticker_news:
                print(f"  -> {len(ticker_news)}개의 기사 수집 완료.", flush=True)
                aggregated_news.extend(ticker_news)
            else:
                print(f"  -> 새로운 기사가 없습니다.", flush=True)
        except Exception as e:
            print(f"  -> 에러 발생: {e}", flush=True)
            
    # 3. 노션 뉴스 데이터베이스 동기화 (중복 필터링 및 72시간 지난 기사 자동 정리)
    if aggregated_news:
        sync_market_news_to_notion(aggregated_news, fast_translate=True)
    else:
        print("수집된 신규 뉴스가 없습니다.", flush=True)
        
    print(f"=== 뉴스 수집 및 노션 동기화 완료 ===\n", flush=True)
    os._exit(0)

if __name__ == "__main__":
    main()
