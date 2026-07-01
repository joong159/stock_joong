import os
import requests
import datetime

# .env 파일 파싱 헬퍼 (의존성 최소화)
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
        except Exception:
            pass

load_dotenv()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def find_database_by_name(name):
    """
    노션 워크스페이스에 공유된 데이터베이스 중 이름이 일치하는 데이터베이스 ID를 검색합니다.
    """
    if not NOTION_TOKEN:
        return None
    url = "https://api.notion.com/v1/search"
    payload = {
        "query": name,
        "filter": {
            "property": "object",
            "value": "database"
        }
    }
    try:
        res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        if res.status_code == 200:
            results = res.json().get("results", [])
            for db in results:
                title_list = db.get("title", [])
                db_title = "".join([t.get("plain_text", "") for t in title_list])
                if db_title.strip() == name:
                    return db.get("id")
        else:
            print(f"[Notion Search Warning] Status: {res.status_code}, Res: {res.text}")
    except Exception as e:
        print(f"[Notion Connection Error] {e}")
    return None

def sync_holdings_to_notion(holdings_list):
    """
    실시간 보유 주식 잔고 현황을 노션 데이터베이스('실시간 보유 잔고 현황')와 완벽 동기화합니다.
    - holdings_list: (symbol, name, qty, price, val_krw, currency) 튜플 리스트
    """
    if not NOTION_TOKEN:
        return
        
    db_id = find_database_by_name("실시간 보유 잔고 현황")
    if not db_id:
        print("[Notion Sync] '실시간 보유 잔고 현황' 데이터베이스를 찾을 수 없어 노션 동기화를 건너뜁니다.")
        return
        
    try:
        # 1. 노션 데이터베이스의 기존 페이지 조회
        query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
        res = requests.post(query_url, headers=HEADERS, json={}, timeout=10)
        res.raise_for_status()
        existing_pages = res.json().get("results", [])
        
        # Symbol -> PageID 매핑 딕셔너리 구축
        notion_holdings = {}
        for page in existing_pages:
            page_id = page.get("id")
            props = page.get("properties", {})
            
            # Symbol 속성 읽기
            symbol_prop = props.get("Symbol", {}).get("rich_text", [])
            symbol = "".join([t.get("plain_text", "") for t in symbol_prop]).strip()
            if symbol:
                notion_holdings[symbol] = page_id

        # 2. 실시간 잔고 동기화 진행
        active_symbols = set()
        for item in holdings_list:
            sym, name, qty, price, val_krw, currency = item
            active_symbols.add(sym)
            
            # 노션 데이터베이스 속성 빌드
            properties = {
                "Name": {"title": [{"text": {"content": name}}]},
                "Symbol": {"rich_text": [{"text": {"content": sym}}]},
                "Qty": {"number": float(qty)},
                "Price": {"number": float(price)},
                "Value": {"number": float(val_krw)},
                "Currency": {"select": {"name": currency}}
            }
            
            if sym in notion_holdings:
                # 기존 항목 정보 업데이트
                page_id = notion_holdings[sym]
                update_url = f"https://api.notion.com/v1/pages/{page_id}"
                requests.patch(update_url, headers=HEADERS, json={"properties": properties}, timeout=10)
            else:
                # 신규 항목 생성
                create_url = "https://api.notion.com/v1/pages"
                payload = {
                    "parent": {"database_id": db_id},
                    "properties": properties
                }
                requests.post(create_url, headers=HEADERS, json=payload, timeout=10)

        # 3. 더 이상 보유하지 않는 종목 삭제 (Archived 처리)
        for sym, page_id in notion_holdings.items():
            if sym not in active_symbols:
                delete_url = f"https://api.notion.com/v1/pages/{page_id}"
                requests.patch(delete_url, headers=HEADERS, json={"archived": True}, timeout=10)
                
        print(f"[Notion Sync] 성공적으로 {len(holdings_list)}개의 잔고 종목을 노션 데이터베이스와 동기화 완료했습니다.")
    except Exception as e:
        print(f"[Notion Sync Error] {e}")

def log_trade_to_notion(symbol, name, side, qty, price, val_krw, reason=""):
    """
    체결된 거래 정보를 노션 데이터베이스('주식 거래 일지')에 새 로그로 기록합니다.
    """
    if not NOTION_TOKEN:
        return
        
    db_id = find_database_by_name("주식 거래 일지")
    if not db_id:
        print("[Notion Log] '주식 거래 일지' 데이터베이스를 찾을 수 없어 거래 일지 기록을 건너뜁니다.")
        return
        
    try:
        now_str = datetime.datetime.now().isoformat()
        title = f"{name} { '매수' if side == 'BUY' else '매도'}"
        
        properties = {
            "Name": {"title": [{"text": {"content": title}}]},
            "Date": {"date": {"start": now_str}},
            "Symbol": {"rich_text": [{"text": {"content": symbol}}]},
            "Side": {"select": {"name": side}},
            "Qty": {"number": float(qty)},
            "Price": {"number": float(price)},
            "Value": {"number": float(val_krw)},
            "Reason": {"rich_text": [{"text": {"content": str(reason)}}]}
        }
        
        create_url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": db_id},
            "properties": properties
        }
        res = requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
        res.raise_for_status()
        print(f"[Notion Log] 성공적으로 {name}({symbol})의 {side} 거래 정보를 노션 일지에 기록했습니다.")
    except Exception as e:
        print(f"[Notion Log Error] {e}")
