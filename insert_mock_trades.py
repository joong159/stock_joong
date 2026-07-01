import os
import requests
import datetime
from notion_sync import find_database_by_name, HEADERS

def load_dotenv(dotenv_path=".env"):
    if os.path.exists(dotenv_path):
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

load_dotenv()

def insert_test_trades():
    db_id = find_database_by_name("주식 거래 일지")
    if not db_id:
        print("오류: '주식 거래 일지' 데이터베이스를 찾을 수 없습니다.")
        return False
        
    mock_data = [
        {
            "title": "애플(AAPL) 매수",
            "date": "2026-06-25T10:15:00.000+09:00",
            "symbol": "AAPL",
            "side": "BUY",
            "qty": 5.0,
            "price": 182.50,
            "val_krw": 1231875.0, # 5 * 182.5 * 1350
            "reason": "S&P 500 포트폴리오 재배정 및 알파 랭킹 상승에 따른 신규 진입"
        },
        {
            "title": "삼성전자(005930.KS) 매수",
            "date": "2026-06-26T09:30:00.000+09:00",
            "symbol": "005930.KS",
            "side": "BUY",
            "qty": 15.0,
            "price": 71200.0,
            "val_krw": 1068000.0, # 15 * 71200
            "reason": "코스피 반도체 섹터 모멘텀 확인 및 목표 비중 충족을 위한 매수"
        },
        {
            "title": "테슬라(TSLA) 매도",
            "date": "2026-06-29T23:45:00.000+09:00",
            "symbol": "TSLA",
            "side": "SELL",
            "qty": 3.0,
            "price": 205.10,
            "val_krw": 830655.0, # 3 * 205.1 * 1350
            "reason": "Chandelier Exit (추적 손절) 기준가인 $206.5 이하로 가격이 이탈하여 원칙 매도 집행"
        }
    ]
    
    print("노션 데이터베이스에 테스트용 가상 거래 데이터 3건을 삽입합니다...")
    for item in mock_data:
        properties = {
            "Name": {"title": [{"text": {"content": item["title"]}}]},
            "Date": {"date": {"start": item["date"]}},
            "Symbol": {"rich_text": [{"text": {"content": item["symbol"]}}]},
            "Side": {"select": {"name": item["side"]}},
            "Qty": {"number": float(item["qty"])},
            "Price": {"number": float(item["price"])},
            "Value": {"number": float(item["val_krw"])},
            "Reason": {"rich_text": [{"text": {"content": item["reason"]}}]}
        }
        
        create_url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": db_id},
            "properties": properties
        }
        try:
            res = requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
            if res.status_code == 200:
                print(f"성공: {item['title']} 삽입 완료")
            else:
                print(f"실패: {item['title']} - {res.text}")
        except Exception as e:
            print(f"에러: {item['title']} - {e}")
    return True

if __name__ == "__main__":
    insert_test_trades()
