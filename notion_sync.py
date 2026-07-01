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
        # 시장 국면 로드하여 노션 페이지 스타일 동적 업데이트
        if os.path.exists(".market_regime.txt"):
            try:
                with open(".market_regime.txt", "r", encoding="utf-8") as f:
                    regime_val = f.read().strip()
                    update_notion_regime_style(regime_val)
            except Exception:
                pass

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

        # 데이터베이스 스키마 보완 (칼럼들 타입을 rich_text로 변경하여 형식 통일 및 깔끔하게 노출)
        try:
            update_db_url = f"https://api.notion.com/v1/databases/{db_id}"
            schema_payload = {
                "properties": {
                    "Qty": {"rich_text": {}},
                    "Price": {"rich_text": {}},
                    "PurchaseVal": {"rich_text": {}},
                    "Value": {"rich_text": {}},
                    "ProfitLoss": {"rich_text": {}}
                }
            }
            requests.patch(update_db_url, headers=HEADERS, json=schema_payload, timeout=10)
        except Exception:
            pass

        # 2. 실시간 잔고 동기화 진행
        active_symbols = set()
        for item in holdings_list:
            sym, name, qty, price, purchase_val_krw, val_krw, pl_rate, currency = item
            active_symbols.add(sym)
            
            # 값 예쁘게 원화 및 달러 기호 포맷팅
            if currency == "USD":
                qty_str = f"{qty:.4f}" if qty % 1 != 0 else f"{int(qty)}"
                price_krw = (val_krw / qty) if qty > 0 else (price * 1350.0)
                price_str = f"$ {price:,.2f} (₩ {price_krw:,.0f})"
            else:
                qty_str = f"{qty:,.0f}"
                price_str = f"₩ {price:,.0f}"
                
            purchase_val_str = f"₩ {purchase_val_krw:,.0f}"
            val_str = f"₩ {val_krw:,.0f}"
            pl_str = f"{pl_rate:+.2f}%"
            
            # 노션 데이터베이스 속성 빌드
            properties = {
                "Name": {"title": [{"text": {"content": name}}]},
                "Symbol": {"rich_text": [{"text": {"content": sym}}]},
                "Qty": {"rich_text": [{"text": {"content": qty_str}}]},
                "Price": {"rich_text": [{"text": {"content": price_str}}]},
                "PurchaseVal": {"rich_text": [{"text": {"content": purchase_val_str}}]},
                "Value": {"rich_text": [{"text": {"content": val_str}}]},
                "ProfitLoss": {"rich_text": [{"text": {"content": pl_str}}]},
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

def sync_market_news_to_notion(news_list):
    """
    주요 종목 뉴스 및 센티먼트 리스트를 노션 데이터베이스('📰 주요 시장 뉴스')와 동기화합니다.
    """
    if not NOTION_TOKEN:
        return
        
    db_id = find_database_by_name("📰 주요 시장 뉴스")
    if not db_id:
        print("[Notion News] '📰 주요 시장 뉴스' 데이터베이스를 찾을 수 없어 뉴스 동기화를 건너뜁니다.")
        return
        
    try:
        # 1. 기존의 노션 뉴스 아이템 전부 조회 후 아카이브 (최신 뉴스 위주 유지를 위함)
        query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
        res = requests.post(query_url, headers=HEADERS, json={"page_size": 100}, timeout=10)
        if res.status_code == 200:
            results = res.json().get("results", [])
            for page in results:
                page_id = page.get("id")
                requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json={"archived": True}, timeout=10)
                
        # 2. 신규 뉴스 아이템 생성
        for art in news_list:
            create_url = "https://api.notion.com/v1/pages"
            
            # 시간 파싱
            pub_time = art.get("time")
            if isinstance(pub_time, (int, float)):
                try:
                    dt = datetime.datetime.fromtimestamp(pub_time)
                    date_str = dt.isoformat()
                except Exception:
                    date_str = datetime.datetime.now().isoformat()
            else:
                date_str = datetime.datetime.now().isoformat()
                
            payload = {
                "parent": {"database_id": db_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": art.get("title", "뉴스 헤드라인")}}]},
                    "Stock": {"rich_text": [{"text": {"content": art.get("symbol", "")}}]},
                    "Publisher": {"rich_text": [{"text": {"content": art.get("publisher", "")}}]},
                    "Link": {"url": art.get("link", "")},
                    "Date": {"date": {"start": date_str}}
                }
            }
            requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
            
        print(f"[Notion News] 성공적으로 {len(news_list)}개의 시장 뉴스를 동기화 완료했습니다.")
    except Exception as e:
        print(f"[Notion News Error] {e}")

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
        requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
        res.raise_for_status()
        print(f"[Notion Log] 성공적으로 {name}({symbol})의 {side} 거래 정보를 노션 일지에 기록했습니다.")
    except Exception as e:
        print(f"[Notion Log Error] {e}")

def setup_notion_workspace():
    """
    사용자가 생성한 '주식 자동 리밸런싱 대시보드' 페이지를 검색한 뒤,
    그 하위에 필요한 2개의 데이터베이스를 자동으로 생성해 줍니다.
    """
    if not NOTION_TOKEN:
        return "Notion API 토큰(.env의 NOTION_TOKEN)이 설정되어 있지 않습니다."
        
    # 1. '주식 자동 리밸런싱 대시보드' 페이지 검색
    url = "https://api.notion.com/v1/search"
    payload = {
        "query": "주식 자동 리밸런싱 대시보드",
        "filter": {
            "property": "object",
            "value": "page"
        }
    }
    
    try:
        res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        if res.status_code != 200:
            return f"노션 API 호출 실패 (상태코드: {res.status_code})"
            
        results = res.json().get("results", [])
        parent_page_id = None
        for page in results:
            props = page.get("properties", {})
            for prop_name, prop_val in props.items():
                if prop_val.get("type") == "title":
                    title_list = prop_val.get("title", [])
                    page_title = "".join([t.get("plain_text", "") for t in title_list])
                    if page_title.strip() == "주식 자동 리밸런싱 대시보드":
                        parent_page_id = page.get("id")
                        break
            if parent_page_id:
                break
                
        if not parent_page_id:
            return "노션에서 '주식 자동 리밸런싱 대시보드'라는 이름의 페이지를 찾을 수 없습니다.\n먼저 새 페이지를 만든 뒤, 우측 상단 '...' -> '연결 대상'에서 생성하신 API를 추가해 주세요."
            
        # 2. 이미 데이터베이스가 있는지 검사
        holdings_db_id = find_database_by_name("실시간 보유 잔고 현황")
        logs_db_id = find_database_by_name("주식 거래 일지")
        
        created_count = 0
        
        # 3. '실시간 보유 잔고 현황' 생성
        if not holdings_db_id:
            create_url = "https://api.notion.com/v1/databases"
            db_payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": "실시간 보유 잔고 현황"}}],
                "properties": {
                    "Name": {"title": {}},
                    "Symbol": {"rich_text": {}},
                    "Qty": {"rich_text": {}},
                    "Price": {"rich_text": {}},
                    "PurchaseVal": {"rich_text": {}},
                    "Value": {"rich_text": {}},
                    "ProfitLoss": {"rich_text": {}},
                    "Currency": {
                        "select": {
                            "options": [
                                {"name": "KRW", "color": "green"},
                                {"name": "USD", "color": "blue"}
                            ]
                        }
                    }
                }
            }
            c_res = requests.post(create_url, headers=HEADERS, json=db_payload, timeout=10)
            if c_res.status_code == 200:
                created_count += 1
            else:
                return f"'실시간 보유 잔고 현황' 디비 생성 실패: {c_res.text}"
                
        # 4. '주식 거래 일지' 생성
        if not logs_db_id:
            create_url = "https://api.notion.com/v1/databases"
            db_payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": "주식 거래 일지"}}],
                "properties": {
                    "Name": {"title": {}},
                    "Date": {"date": {}},
                    "Symbol": {"rich_text": {}},
                    "Side": {
                        "select": {
                            "options": [
                                {"name": "BUY", "color": "green"},
                                {"name": "SELL", "color": "red"}
                            ]
                        }
                    },
                    "Qty": {"number": {"format": "number"}},
                    "Price": {"number": {"format": "number"}},
                    "Value": {"number": {"format": "number"}},
                    "Reason": {"rich_text": {}}
                }
            }
            c_res = requests.post(create_url, headers=HEADERS, json=db_payload, timeout=10)
            if c_res.status_code == 200:
                created_count += 1
            else:
                return f"'주식 거래 일지' 디비 생성 실패: {c_res.text}"
                
        # 5. '📰 주요 시장 뉴스' 데이터베이스 생성
        news_db_id = find_database_by_name("📰 주요 시장 뉴스")
        if not news_db_id:
            create_url = "https://api.notion.com/v1/databases"
            db_payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": "📰 주요 시장 뉴스"}}],
                "properties": {
                    "Name": {"title": {}},
                    "Stock": {"rich_text": {}},
                    "Publisher": {"rich_text": {}},
                    "Link": {"url": {}},
                    "Date": {"date": {}}
                }
            }
            c_res = requests.post(create_url, headers=HEADERS, json=db_payload, timeout=10)
            if c_res.status_code == 200:
                created_count += 1
            else:
                return f"'📰 주요 시장 뉴스' 디비 생성 실패: {c_res.text}"

        if created_count > 0:
            return f"성공적으로 {created_count}개의 데이터베이스를 노션 페이지 하위에 생성/연동 완료했습니다!"
        else:
            return "이미 필요한 데이터베이스들이 노션 워크스페이스에 생성되어 연동된 상태입니다."
            
    except Exception as e:
        return f"노션 자동 설정 중 오류 발생: {e}"

def decorate_notion_workspace():
    """
    '주식 자동 리밸런싱 대시보드' 페이지의 아이콘, 커버 이미지, 소개글,
    그리고 '투자 3대 절대 원칙' 콜아웃 박스를 추가하여 디자인을 아름답게 꾸밉니다.
    """
    if not NOTION_TOKEN:
        return "Notion API 토큰이 설정되어 있지 않습니다."

    # 1. 페이지 검색
    url = "https://api.notion.com/v1/search"
    payload = {
        "query": "주식 자동 리밸런싱 대시보드",
        "filter": {
            "property": "object",
            "value": "page"
        }
    }
    
    try:
        res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        if res.status_code != 200:
            return f"페이지 검색 실패 (상태코드: {res.status_code})"
            
        results = res.json().get("results", [])
        page_id = None
        for page in results:
            props = page.get("properties", {})
            for prop_name, prop_val in props.items():
                if prop_val.get("type") == "title":
                    title_list = prop_val.get("title", [])
                    page_title = "".join([t.get("plain_text", "") for t in title_list])
                    if page_title.strip() == "주식 자동 리밸런싱 대시보드":
                        page_id = page.get("id")
                        break
            if page_id:
                break
                
        if not page_id:
            return "노션에서 '주식 자동 리밸런싱 대시보드' 페이지를 찾을 수 없습니다."

        # 시장 국면 계절에 따른 동적 아이콘/커버 로드
        regime_val = "UNKNOWN"
        if os.path.exists(".market_regime.txt"):
            try:
                with open(".market_regime.txt", "r", encoding="utf-8") as f:
                    regime_val = f.read().strip()
            except Exception:
                pass

        regime_styles = {
            "SPRING": {
                "emoji": "🌸",
                "cover": "https://images.unsplash.com/photo-1522748906645-95d8adfd52c7?q=80&w=2070&auto=format&fit=crop",
                "title_suffix": " (현재 계절: 🌸 봄 - SPRING)"
            },
            "SUMMER": {
                "emoji": "☀️",
                "cover": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?q=80&w=2073&auto=format&fit=crop",
                "title_suffix": " (현재 계절: ☀️ 여름 - SUMMER)"
            },
            "FALL": {
                "emoji": "🍁",
                "cover": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?q=80&w=2070&auto=format&fit=crop",
                "title_suffix": " (현재 계절: 🍁 가을 - FALL)"
            },
            "WINTER": {
                "emoji": "❄️",
                "cover": "https://images.unsplash.com/photo-1491002052546-bf38f186af56?q=80&w=2008&auto=format&fit=crop",
                "title_suffix": " (현재 계절: ❄️ 겨울 - WINTER)"
            }
        }
        
        style = regime_styles.get(regime_val, {
            "emoji": "📈",
            "cover": "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?q=80&w=2070&auto=format&fit=crop",
            "title_suffix": ""
        })

        # 2. 페이지 아이콘 및 커버 설정 (PATCH /v1/pages/{page_id})
        page_url = f"https://api.notion.com/v1/pages/{page_id}"
        page_payload = {
            "icon": {
                "type": "emoji",
                "emoji": style["emoji"]
            },
            "cover": {
                "type": "external",
                "external": {
                    "url": style["cover"]
                }
            },
            "properties": {
                "title": {
                    "title": [{"text": {"content": f"주식 자동 리밸런싱 대시보드{style['title_suffix']}"}}]
                }
            }
        }
        requests.patch(page_url, headers=HEADERS, json=page_payload, timeout=10)

        # 3. 기존에 추가된 블록 목록 조회하여 원칙 박스가 이미 있는지 검사
        blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        b_res = requests.get(blocks_url, headers=HEADERS, timeout=10)
        has_callout = False
        if b_res.status_code == 200:
            blocks = b_res.json().get("results", [])
            for block in blocks:
                if block.get("type") == "callout":
                    has_callout = True
                    break
        
        # 4. 원칙 콜아웃 박스 및 소개글 추가 (없을 경우에만)
        if not has_callout:
            children_payload = {
                "children": [
                    {
                        "object": "block",
                        "type": "heading_1",
                        "heading_1": {
                            "rich_text": [{"type": "text", "text": {"content": "📈 퀀트 포트폴리오 자동 리밸런싱 시스템"}}]
                        }
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text", 
                                    "text": {"content": "본 페이지는 토스증권 Open API 및 제미나이 AI와 실시간으로 연동되어 가동되는 자동화 자산 배분 관리 화면입니다. 아래의 보유 현황 및 거래 일지는 백그라운드 엔진에 의해 실시간으로 업데이트됩니다."}
                                }
                            ]
                        }
                    },
                    {
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "현재 시장 계절: 분석 대기 중 (실시간 지표에 의해 자동으로 변동됩니다)"
                                    }
                                }
                            ],
                            "icon": {"type": "emoji", "emoji": "📈"},
                            "color": "gray_background"
                        }
                    },
                    {
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "🛡️ 퀀트 투자 3대 절대 원칙\n1. 글로벌 자산 배분 비율 준수: 국장(한국 주식) 50% & 미장(미국 주식) 50% 비중 강제\n2. 샹들리에 추적 손절: Chandelier Exit 추적 손절라인 이탈 시 기계적으로 전량 시장가 즉시 매도\n3. AI 심리 피드백: 매 거래 발생 시 마다 매매 사유를 기입하고, 주기적으로 AI 자산진단을 수행하여 뇌동 매매를 방지"
                                    }
                                }
                            ],
                            "icon": {"type": "emoji", "emoji": "🛡️"},
                            "color": "purple_background"
                        }
                    },
                    {
                        "object": "block",
                        "type": "divider",
                        "divider": {}
                    }
                ]
            }
            requests.patch(blocks_url, headers=HEADERS, json=children_payload, timeout=10)
            return "노션 페이지 디자인 꾸미기(커버 설정, 아이콘 지정, 투자 원칙 콜아웃 박스 생성)가 완료되었습니다!"
        else:
            return "커버 이미지 및 아이콘이 갱신되었습니다. (소개글과 투자 원칙 박스는 이미 존재하여 유지만 되었습니다)"

    except Exception as e:
        return f"노션 디자인 꾸미기 중 오류 발생: {e}"

def update_notion_regime_style(regime_val):
    """
    현재 매크로 국면에 따라 노션 대시보드 페이지의 커버 이미지와 이모지를 동적으로 변경합니다.
    """
    if not NOTION_TOKEN:
        return
        
    url = "https://api.notion.com/v1/search"
    payload = {
        "query": "주식 자동 리밸런싱 대시보드",
        "filter": {
            "property": "object",
            "value": "page"
        }
    }
    try:
        res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        if res.status_code != 200:
            return
        results = res.json().get("results", [])
        page_id = None
        for page in results:
            props = page.get("properties", {})
            for prop_name, prop_val in props.items():
                if prop_val.get("type") == "title":
                    title_list = prop_val.get("title", [])
                    page_title = "".join([t.get("plain_text", "") for t in title_list])
                    if "주식 자동 리밸런싱 대시보드" in page_title:
                        page_id = page.get("id")
                        break
            if page_id:
                break
        if not page_id:
            return

        # 계절별 아이콘 및 커버 매핑
        regime_styles = {
            "SPRING": {
                "emoji": "🌸",
                "cover": "https://images.unsplash.com/photo-1522748906645-95d8adfd52c7?q=80&w=2070&auto=format&fit=crop",
                "title_suffix": " (현재 계절: 🌸 봄 - SPRING)"
            },
            "SUMMER": {
                "emoji": "☀️",
                "cover": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?q=80&w=2073&auto=format&fit=crop",
                "title_suffix": " (현재 계절: ☀️ 여름 - SUMMER)"
            },
            "FALL": {
                "emoji": "🍁",
                "cover": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?q=80&w=2070&auto=format&fit=crop",
                "title_suffix": " (현재 계절: 🍁 가을 - FALL)"
            },
            "WINTER": {
                "emoji": "❄️",
                "cover": "https://images.unsplash.com/photo-1491002052546-bf38f186af56?q=80&w=2008&auto=format&fit=crop",
                "title_suffix": " (현재 계절: ❄️ 겨울 - WINTER)"
            }
        }

        style = regime_styles.get(regime_val, {
            "emoji": "📈",
            "cover": "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?q=80&w=2070&auto=format&fit=crop",
            "title_suffix": ""
        })

        page_url = f"https://api.notion.com/v1/pages/{page_id}"
        page_payload = {
            "icon": {
                "type": "emoji",
                "emoji": style["emoji"]
            },
            "cover": {
                "type": "external",
                "external": {
                    "url": style["cover"]
                }
            },
            "properties": {
                "title": {
                    "title": [{"text": {"content": f"주식 자동 리밸런싱 대시보드{style['title_suffix']}"}}]
                }
            }
        }
        requests.patch(page_url, headers=HEADERS, json=page_payload, timeout=10)

        # 4. 페이지 본문 내부의 '현재 시장 계절' 콜아웃 박스도 찾아서 동적으로 동기화
        blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        b_res = requests.get(blocks_url, headers=HEADERS, timeout=10)
        regime_block_id = None
        if b_res.status_code == 200:
            blocks = b_res.json().get("results", [])
            for block in blocks:
                if block.get("type") == "callout":
                    c_texts = block.get("callout", {}).get("rich_text", [])
                    c_text = "".join([t.get("plain_text", "") for t in c_texts]).strip()
                    if "현재 시장 계절:" in c_text or "시장 계절:" in c_text:
                        regime_block_id = block.get("id")
                        break

        regime_desc_map = {
            "SPRING": "현재 시장 계절: 🌸 봄 (SPRING) - 성장 국면 (적극 주식 매수 전략)",
            "SUMMER": "현재 시장 계절: ☀️ 여름 (SUMMER) - 과열 국면 (주도 업종 선별 매수 전략)",
            "FALL": "현재 시장 계절: 🍁 가을 (FALL) - 쇠퇴 국면 (안전 자산 방어 및 리스크 대비)",
            "WINTER": "현재 시장 계절: ❄️ 겨울 (WINTER) - 위축 국면 (현금화 및 하방 대기 전략)"
        }
        regime_text = regime_desc_map.get(regime_val, f"현재 시장 계절: {regime_val}")

        regime_color_map = {
            "SPRING": "green_background",
            "SUMMER": "orange_background",
            "FALL": "yellow_background",
            "WINTER": "blue_background"
        }
        regime_color = regime_color_map.get(regime_val, "gray_background")

        if regime_block_id:
            # 기존 블록 내용 패치
            patch_block_url = f"https://api.notion.com/v1/blocks/{regime_block_id}"
            patch_payload = {
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": regime_text}}],
                    "icon": {"type": "emoji", "emoji": style["emoji"]},
                    "color": regime_color
                }
            }
            requests.patch(patch_block_url, headers=HEADERS, json=patch_payload, timeout=10)
        else:
            # 없으면 추가 (소개글 밑 등에 생성되도록 append)
            append_payload = {
                "children": [
                    {
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [{"type": "text", "text": {"content": regime_text}}],
                            "icon": {"type": "emoji", "emoji": style["emoji"]},
                            "color": regime_color
                        }
                    }
                ]
            }
            requests.post(blocks_url, headers=HEADERS, json=append_payload, timeout=10)

    except Exception as e:
        print(f"[Notion Regime Style Update Error] {e}")
