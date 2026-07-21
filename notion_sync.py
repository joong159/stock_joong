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

import json

TRANSLATION_CACHE_FILE = ".translation_cache.json"

def load_translation_cache():
    if os.path.exists(TRANSLATION_CACHE_FILE):
        try:
            with open(TRANSLATION_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_translation_cache(cache):
    try:
        with open(TRANSLATION_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

def translate_via_google_fallback(text):
    """
    제미나이 할당량 초과 시 호출되는 백업 번역기 (구글 번역 무료 엔드포인트 활용)
    """
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "ko",
            "dt": "t",
            "q": text
        }
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            res_json = r.json()
            if res_json and len(res_json) > 0 and len(res_json[0]) > 0:
                translated = "".join([part[0] for part in res_json[0] if part[0]])
                return translated.strip()
    except Exception as e:
        print(f"[Google Translate Fallback Warning] Failed: {e}")
    return text

def translate_headline_to_korean(headline, fast=False):
    """
    제미나이 2.5 플래시 모델을 활용하여 영문 뉴스 헤드라인을 자연스럽고 간결한 한국어로 번역합니다.
    - fast=True 이거나 API 키가 없는 경우, 구글 번역 fallback을 사용하여 매우 신속하게 응답하고 API 할당량을 대폭 아낍니다.
    """
    if not headline:
        return headline
        
    cache = load_translation_cache()
    if headline in cache:
        return cache[headline]
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if fast or not api_key:
        translated = translate_via_google_fallback(headline)
        cache[headline] = translated
        save_translation_cache(cache)
        return translated
        
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"Translate the following financial news headline to Korean in a natural, concise, professional analyst style. Output ONLY the Korean translation, with no quotes and no extra comments: {headline}"
        response = model.generate_content(prompt, request_options={"timeout": 10.0})
        if response and response.text:
            translated = response.text.strip().replace('"', '')
            cache[headline] = translated
            save_translation_cache(cache)
            return translated
    except Exception as e:
        # 제미나이 429 할당량 초과 시 구글 번역 fallback 호출
        print(f"[News Translate Warning] Failed to translate via Gemini: {e}")
        print("[News Translate] Falling back to free Google Translate API...")
        translated = translate_via_google_fallback(headline)
        cache[headline] = translated
        save_translation_cache(cache)
        return translated
        
    return headline

def get_single_news_sentiment(title_en, title_ko):
    """
    VADER 감성 분석기 및 한국어 키워드 기반 매칭을 활용하여 개별 뉴스의 호재/악재 여부를 판별합니다.
    """
    try:
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        import nltk
        try:
            nltk.data.find('sentiment/vader_lexicon')
        except LookupError:
            nltk.download('vader_lexicon', quiet=True)
        sia = SentimentIntensityAnalyzer()
        score = sia.polarity_scores(title_en)['compound']
        if score > 0.05:
            return "호재 🟢", score
        elif score < -0.05:
            return "악재 🔴", score
    except Exception:
        pass

    # 한국어 키워드 매칭
    pos_words = ["상승", "호조", "급등", "어닝서프라이즈", "성장", "호재", "흑자", "최대", "돌파", "계약", "유치", "강세", "긍정", "목표가 상향", "성공"]
    neg_words = ["하락", "급락", "어닝쇼크", "부진", "감소", "악재", "적자", "붕괴", "취소", "약세", "부정", "목표가 하향", "소송", "규제", "과징금", "실패", "우려"]
    
    pos_count = sum(1 for w in pos_words if w in title_ko)
    neg_count = sum(1 for w in neg_words if w in title_ko)
    
    if pos_count > neg_count:
        return "호재 🟢", 0.5
    elif neg_count > pos_count:
        return "악재 🔴", -0.5
        
    return "중립 ⚪", 0.0

def get_korean_company_name(symbol):
    # Mapping for common tickers to clean Korean names
    korean_names = {
        # KRX Top Tickers
        '005930.KS': '삼성전자', '005930': '삼성전자',
        '000660.KS': 'SK하이닉스', '000660': 'SK하이닉스',
        '005380.KS': '현대차', '005380': '현대차',
        '000270.KS': '기아', '000270': '기아',
        '035420.KS': 'NAVER', '035420': 'NAVER',
        '035720.KS': '카카오', '035720': '카카오',
        '068270.KS': '셀트리온', '068270': '셀트리온',
        '005490.KS': 'POSCO홀딩스', '005490': 'POSCO홀딩스',
        '207940.KS': '삼성바이오로직스', '207940': '삼성바이오로직스',
        '051910.KS': 'LG화학', '051910': 'LG화학',
        '105560.KS': 'KB금융', '105560': 'KB금융',
        '055550.KS': '신한지주', '055550': '신한지주',
        '011200.KS': 'HMM', '011200': 'HMM',
        '033780.KS': 'KT&G', '033780': 'KT&G',
        '373220.KS': 'LG에너지솔루션', '373220': 'LG에너지솔루션',
        '006400.KS': '삼성SDI', '006400': '삼성SDI',
        '028260.KS': '삼성물산', '028260': '삼성물산',
        '012330.KS': '현대모비스', '012330': '현대모비스',
        '066570.KS': 'LG전자', '066570': 'LG전자',
        '032830.KS': '삼성생명', '032830': '삼성생명',
        '003670.KS': '포스코퓨처엠', '003670': '포스코퓨처엠',
        '000810.KS': '삼성화재', '000810': '삼성화재',
        '015760.KS': '한국전력', '015760': '한국전력',
        '086790.KS': '하나금융지주', '086790': '하나금융지주',
        '017670.KS': 'SK텔레콤', '017670': 'SK텔레콤',
        '010140.KS': '삼성중공업', '010140': '삼성중공업',
        '009150.KS': '삼성전기', '009150': '삼성전기',
        '034730.KS': 'SK', '034730': 'SK',
        '329180.KS': 'HD현대중공업', '329180': 'HD현대중공업',
        '003550.KS': 'LG', '003550': 'LG',
        '036570.KS': '엔씨소프트', '036570': '엔씨소프트',
        '018260.KS': '삼성SDS', '018260': '삼성SDS',
        '024110.KS': '기업은행', '024110': '기업은행',
        '030200.KS': 'KT', '030200': 'KT',
        '010950.KS': 'S-Oil', '010950': 'S-Oil',
        '034020.KS': '두산에너빌리티', '034020': '두산에너빌리티',
        '000150.KS': '두산', '000150': '두산',
        '096770.KS': 'SK이노베이션', '096770': 'SK이노베이션',
        
        # US Popular Tickers
        'AAPL': '애플', 'MSFT': '마이크로소프트', 'GOOGL': '알파벳(구글)', 'GOOG': '알파벳(구글)',
        'AMZN': '아마존', 'NVDA': '엔비디아', 'TSLA': '테슬라', 'META': '메타(페이스북)',
        'BRK.B': '버크셔해서웨이', 'BRK-B': '버크셔해서웨이', 'BRK-A': '버크셔해서웨이',
        'JNJ': '존슨앤드존슨', 'V': '비자', 'PG': '프록터앤갬블(P&G)', 'JPM': 'JP모건체이스',
        'UNH': '유나이티드헬스', 'HD': '홈디포', 'MA': '마스터카드', 'BAC': '뱅크오브아메리카',
        'DIS': '디즈니', 'ADBE': '어도비', 'NFLX': '넷플릭스', 'KO': '코카콜라',
        'PEP': '펩시코', 'T': 'AT&T', 'VZ': '버라이즌', 'INTC': '인텔',
        'CSCO': '시스코', 'MRK': '머크', 'PFE': '화이자', 'WMT': '월마트',
        'LLY': '일라이릴리', 'AVGO': '브로드컴', 'COST': '코스트코', 'AMD': 'AMD',
        'CRM': '세일즈포스', 'NKE': '나이키', 'MCD': '맥도날드', 'TXN': '텍사스인스트루먼트',
        'QCOM': '퀄컴', 'HON': '하니웰', 'GE': '제너럴일렉트릭', 'XOM': '엑슨모빌',
        'CVX': '쉐브론', 'WFC': '웰스파고', 'SNDK': '샌디스크', 'PANW': '팔로알토네트웍스',
        'VLO': '발레로에너지', 'MTD': '메틀러토레도', 'MAS': '마스코',
        'EXPD': '익스페디터스', 'CHRW': 'CH 로빈슨', 'UNP': '유니온 퍼시픽',
        'HPQ': 'HP (휴렛팩커드)', 'FTNT': '포티넷', 'CRWD': '크라우드스트라이크',
        'DELL': '델 테크놀로지스', 'NTAP': '넷앱', 'BBY': '베스트바이'
    }
    
    clean_sym = symbol.strip().upper()
    if clean_sym in korean_names:
        return korean_names[clean_sym]
        
    # Fallback to fetching company name from yahoo search api with clean formatting
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            f"https://query2.finance.yahoo.com/v1/finance/search?q={clean_sym}",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=2) as res:
            data = json.loads(res.read())
            quotes = data.get('quotes', [])
            if quotes:
                eng_name = quotes[0].get('longname') or quotes[0].get('shortname') or symbol
                cleaned = eng_name.replace(" , Ltd.", "").replace(" ,Ltd", "").replace(" ,", "").replace(", Inc.", "").replace(", Corp.", "").replace(", Corporation", "").replace(", Ltd.", "").replace(" Inc.", "").replace(" Corp.", "").rstrip(",").strip()
                return cleaned if cleaned else symbol
    except Exception:
        pass
        
    return symbol

def find_database_by_name(name):
    """
    노션 워크스페이스에 공유된 데이터베이스 중 이름이 일치하는 데이터베이스 ID를 검색합니다.
    - 이모지가 포함된 경우 검색 쿼리 이모지를 제거하여 정확하게 매칭합니다.
    """
    if not NOTION_TOKEN:
        return None
    clean_query = name.replace("💡", "").replace("🏆", "").replace("🚨", "").replace("📰", "").replace("📊", "").strip()
    url = "https://api.notion.com/v1/search"
    payload = {
        "query": clean_query,
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
                if clean_query in db_title:
                    return db.get("id")
        else:
            print(f"[Notion Search Warning] Status: {res.status_code}, Res: {res.text}")
    except Exception as e:
        print(f"[Notion Connection Error] {e}")
    return None

def update_notion_kpi_card(total_assets, cash_balance, stock_valuation, usd_krw, holdings_list):
    """
    노션 대시보드 페이지 상단에 총 자산, 예수금, 주식 평가액, 총 평가 손익 등의 현황을
    가독성이 뛰어난 프리미엄 자산 현황판(KPI Card)으로 생성하거나 실시간 업데이트합니다.
    """
    if not NOTION_TOKEN:
        return
    db_id = find_database_by_name("실시간 보유 잔고 현황")
    if not db_id:
        return
        
    try:
        # 1. DB 정보를 조회하여 상위(parent) 페이지 ID를 획득합니다.
        db_url = f"https://api.notion.com/v1/databases/{db_id}"
        db_res = requests.get(db_url, headers=HEADERS, timeout=10)
        if db_res.status_code != 200:
            return
        parent_page = db_res.json().get("parent", {})
        page_id = parent_page.get("page_id")
        if not page_id:
            return
            
        # 2. 페이지 본문 블록 목록을 조회하여 기존 KPI 카드가 있는지 검색합니다.
        blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        b_res = requests.get(blocks_url, headers=HEADERS, timeout=10)
        kpi_block_id = None
        if b_res.status_code == 200:
            blocks = b_res.json().get("results", [])
            for block in blocks:
                if block.get("type") == "callout":
                    c_texts = block.get("callout", {}).get("rich_text", [])
                    c_text = "".join([t.get("plain_text", "") for t in c_texts]).strip()
                    if "실시간 자산 및 리밸런싱 현황판" in c_text or "Real-time KPI Summary" in c_text:
                        kpi_block_id = block.get("id")
                        break
                        
        # 3. 누적 평가 수익 및 수익률 계산
        total_purchase_val = 0.0
        total_current_val = 0.0
        for item in holdings_list:
            # item 형식: (symbol, name, qty, price, purchase_val_krw, val_krw, pl_rate, currency)
            if len(item) >= 6:
                total_purchase_val += float(item[4])
                total_current_val += float(item[5])
                
        total_pl = total_current_val - total_purchase_val
        pl_rate = (total_pl / total_purchase_val) * 100 if total_purchase_val > 0 else 0.0
        
        # 4. 현황판에 표시할 텍스트 템플릿 구성
        kpi_text = (
            f"📊 실시간 자산 및 리밸런싱 현황판 (Real-time KPI Summary)\n"
            f"• 실시간 총 자산 (자산 평가금): ₩ {total_assets:,.0f}\n"
            f"• 보유 예수금 (CASH): ₩ {cash_balance:,.0f}\n"
            f"• 주식 평가액 (STOCKS): ₩ {stock_valuation:,.0f}\n"
            f"• 포트폴리오 평가 손익: ₩ {total_pl:+,.0f} ({pl_rate:+.2f}%)\n"
            f"• 기준 고시 환율 (USD/KRW): ₩ {usd_krw:,.2f}\n"
            f"• 마지막 대시보드 갱신 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        if kpi_block_id:
            # 기존 블록 내용 패치 (실시간 업데이트)
            patch_url = f"https://api.notion.com/v1/blocks/{kpi_block_id}"
            payload = {
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": kpi_text}}],
                    "icon": {"type": "emoji", "emoji": "📊"},
                    "color": "green_background"
                }
            }
            requests.patch(patch_url, headers=HEADERS, json=payload, timeout=10)
        else:
            # 없을 경우 신규 생성하여 추가 (본문 최상단에 근접하도록 추가)
            payload = {
                "children": [
                    {
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [{"type": "text", "text": {"content": kpi_text}}],
                            "icon": {"type": "emoji", "emoji": "📊"},
                            "color": "green_background"
                        }
                    }
                ]
            }
            requests.patch(blocks_url, headers=HEADERS, json=payload, timeout=10)
            
    except Exception as e:
        print(f"[Notion KPI Update Error] {e}")

def sync_holdings_to_notion(holdings_list, total_assets=None, cash_balance=None, stock_valuation=None, usd_krw=None):
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
        # 실시간 자산 현황판 KPI 블록 동적 갱신
        if total_assets is not None:
            update_notion_kpi_card(total_assets, cash_balance, stock_valuation, usd_krw, holdings_list)

        # 시장 국면 로드하여 노션 페이지 스타일 동적 업데이트 (Supabase 동기화 반영)
        try:
            import portfolio_state
            regime_val = portfolio_state.load_market_regime()
            update_notion_regime_style(regime_val)
        except Exception:
            pass

        # 1. 노션 데이터베이스의 기존 페이지 조회
        query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
        res = requests.post(query_url, headers=HEADERS, json={}, timeout=10)
        res.raise_for_status()
        existing_pages = res.json().get("results", [])
        
        # Symbol -> PageID 리스트 매핑 딕셔너리 구축 (중복 제거용)
        notion_holdings = {}
        for page in existing_pages:
            page_id = page.get("id")
            props = page.get("properties", {})
            
            # Symbol 속성 읽기
            symbol_prop = props.get("Symbol", {}).get("rich_text", [])
            symbol = "".join([t.get("plain_text", "") for t in symbol_prop]).strip()
            if symbol:
                if symbol not in notion_holdings:
                    notion_holdings[symbol] = []
                notion_holdings[symbol].append(page_id)

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
            
            if sym in notion_holdings and notion_holdings[sym]:
                # 기존 항목 정보 업데이트 (첫 번째 페이지 활용)
                page_ids = notion_holdings[sym]
                page_id = page_ids[0]
                update_url = f"https://api.notion.com/v1/pages/{page_id}"
                requests.patch(update_url, headers=HEADERS, json={"properties": properties}, timeout=10)
                
                # 나머지 중복 페이지들은 즉시 아카이브 처리하여 중복 제거!
                for extra_page_id in page_ids[1:]:
                    requests.patch(f"https://api.notion.com/v1/pages/{extra_page_id}", headers=HEADERS, json={"archived": True}, timeout=10)
            else:
                # 신규 항목 생성
                create_url = "https://api.notion.com/v1/pages"
                payload = {
                    "parent": {"database_id": db_id},
                    "properties": properties
                }
                requests.post(create_url, headers=HEADERS, json=payload, timeout=10)

        # 3. 더 이상 보유하지 않는 종목 삭제 (Archived 처리)
        for sym, page_ids in notion_holdings.items():
            if sym not in active_symbols:
                for page_id in page_ids:
                    delete_url = f"https://api.notion.com/v1/pages/{page_id}"
                    requests.patch(delete_url, headers=HEADERS, json={"archived": True}, timeout=10)
                
        print(f"[Notion Sync] 성공적으로 {len(holdings_list)}개의 잔고 종목을 노션 데이터베이스와 동기화 완료했습니다.")
    except Exception as e:
        print(f"[Notion Sync Error] {e}")

def sync_market_news_to_notion(news_list, fast_translate=False):
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
        # 데이터베이스 스키마 보완 (Market 및 Sentiment 칼럼 추가)
        try:
            update_db_url = f"https://api.notion.com/v1/databases/{db_id}"
            schema_payload = {
                "properties": {
                    "Market": {
                        "select": {
                            "options": [
                                {"name": "KRX", "color": "green"},
                                {"name": "S&P500", "color": "blue"}
                            ]
                        }
                    },
                    "Sentiment": {
                        "select": {
                            "options": [
                                {"name": "호재 🟢", "color": "green"},
                                {"name": "중립 ⚪", "color": "gray"},
                                {"name": "악재 🔴", "color": "red"}
                            ]
                        }
                    }
                }
            }
            requests.patch(update_db_url, headers=HEADERS, json=schema_payload, timeout=10)
        except Exception:
            pass

        # 1. 기존의 노션 뉴스 아이템 조회 및 72시간 지난 뉴스 아카이브
        existing_links = set()
        query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
        res = requests.post(query_url, headers=HEADERS, json={"page_size": 100}, timeout=10)
        
        now = datetime.datetime.now()
        if res.status_code == 200:
            results = res.json().get("results", [])
            for page in results:
                page_id = page.get("id")
                props = page.get("properties", {})
                
                # 링크 수집
                link_url = props.get("Link", {}).get("url")
                if link_url:
                    existing_links.add(link_url)
                    
                # 날짜 검사하여 72시간(3일) 지난 기사는 삭제(아카이브)
                date_prop = props.get("Date", {}).get("date")
                if date_prop and date_prop.get("start"):
                    try:
                        date_str = date_prop["start"]
                        if "T" in date_str:
                            clean_date_str = date_str.split("+")[0].split("Z")[0]
                            dt = datetime.datetime.fromisoformat(clean_date_str)
                        else:
                            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                        if (now - dt).total_seconds() > 3 * 24 * 3600:
                            requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json={"archived": True}, timeout=10)
                            if link_url in existing_links:
                                existing_links.remove(link_url)
                    except Exception as date_err:
                        print(f"[Notion News Date Check Warning] {date_err}")

        # 2. 신규 뉴스 아이템 생성 (중복 링크 제외)
        inserted_count = 0
        for art in news_list:
            link = art.get("link", "")
            if link and link in existing_links:
                continue
                
            create_url = "https://api.notion.com/v1/pages"
            pub_time = art.get("time")
            if isinstance(pub_time, (int, float)):
                try:
                    dt = datetime.datetime.fromtimestamp(pub_time)
                    date_str = dt.isoformat()
                except Exception:
                    date_str = datetime.datetime.now().isoformat()
            else:
                date_str = datetime.datetime.now().isoformat()
                
            raw_title = art.get("title", "뉴스 헤드라인")
            korean_title = translate_headline_to_korean(raw_title, fast=fast_translate)
            
            sym = art.get("symbol", "")
            is_us = not (sym.endswith('.KS') or sym.endswith('.KQ'))
            market_val = "S&P500" if is_us else "KRX"
            
            company_name = get_korean_company_name(sym)
            stock_display = f"{company_name} ({sym})" if company_name != sym else sym
            sentiment_val, _ = get_single_news_sentiment(raw_title, korean_title)
            
            payload = {
                "parent": {"database_id": db_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": korean_title}}]},
                    "Stock": {"rich_text": [{"text": {"content": stock_display}}]},
                    "Publisher": {"rich_text": [{"text": {"content": art.get("publisher", "")}}]},
                    "Link": {"url": link},
                    "Date": {"date": {"start": date_str}},
                    "Market": {"select": {"name": market_val}},
                    "Sentiment": {"select": {"name": sentiment_val}}
                }
            }
            res_create = requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
            if res_create.status_code in [200, 201]:
                inserted_count += 1
                if link:
                    existing_links.add(link)
            
        print(f"[Notion News] 성공적으로 {inserted_count}개의 새로운 시장 뉴스를 동기화했습니다.")
    except Exception as e:
        print(f"[Notion News Error] {e}")

def ensure_recommend_db_properties(db_id):
    """
    💡 퀀트 추천 포트폴리오 데이터베이스에 액션(Action), 수치형 비중(Weight (%)), 보유금 대비 비중 (%), 전일 대비 속성이
    존재하고 올바른 타입으로 정의되어 있는지 확인하고 자동 추가/수정합니다.
    """
    url = f"https://api.notion.com/v1/databases/{db_id}"
    payload = {
        "properties": {
            "Action": {
                "select": {
                    "options": [
                        {"name": "BUY", "color": "green"},
                        {"name": "HOLD", "color": "yellow"},
                        {"name": "SELL", "color": "red"}
                    ]
                }
            },
            "Weight (%)": {
                "number": {
                    "format": "percent"
                }
            },
            "보유금 대비 비중 (%)": {
                "number": {
                    "format": "percent"
                }
            },
            "전일 대비": {
                "rich_text": {}
            },
            "Date": {
                "date": {}
            }
        }
    }
    try:
        res = requests.patch(url, headers=HEADERS, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"[Notion Schema Update Warning] Status: {res.status_code}, Res: {res.text}")
    except Exception as e:
        print(f"[Notion Properties Warning] Failed to update recommended portfolio schema: {e}")

def sync_recommended_portfolio_to_notion(portfolio_list):
    """
    김민겸 퀀트 추천 포트폴리오를 노션 데이터베이스('💡 퀀트 추천 포트폴리오')와 완벽 동기화합니다.
    - portfolio_list: {"symbol": sym, "name": name, "market": mkt, "industry": ind, "score": score, "weight": weight, "amount": amt, "action": act} 리스트
    """
    if not NOTION_TOKEN:
        return
        
    db_id = find_database_by_name("💡 퀀트 추천 포트폴리오")
    if not db_id:
        print("[Notion Recommend] '퀀트 추천 포트폴리오' 데이터베이스를 찾을 수 없어 동기화를 건너뜁니다.")
        return
        
    try:
        # 데이터베이스 속성(스키마) 유효성 보장 및 보강
        ensure_recommend_db_properties(db_id)
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 1. 기존 노션 추천 포트폴리오 항목 조회 (어제 데이터는 캘린더용으로 보존하고, 오늘 항목만 덮어쓰기 위해 아카이브)
        query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
        res = requests.post(query_url, headers=HEADERS, json={"page_size": 100}, timeout=10)
        
        prev_weights = {} # {ticker: weight_pct}
        if res.status_code == 200:
            results = res.json().get("results", [])
            for page in results:
                page_id = page.get("id")
                props = page.get("properties", {})
                
                # 날짜 추출
                date_prop = props.get("Date", {}).get("date", {})
                page_date = date_prop.get("start", "") if date_prop else ""
                
                # Symbol 추출
                symbol_prop = props.get("Symbol", {}).get("rich_text", [])
                symbol_txt = "".join([t.get("plain_text", "") for t in symbol_prop]).strip()
                
                if not symbol_txt:
                    if page_date == today_str:
                        requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json={"archived": True}, timeout=10)
                    continue
                
                # 티커 추출 (예: "🇺🇸 AAPL" -> "AAPL", "005930.KS" -> "005930.KS")
                import re
                match = re.search(r'([A-Za-z0-9\.\-]+)$', symbol_txt)
                ticker = match.group(1).strip() if match else symbol_txt
                
                # 비중 수치 추출
                weight_num = props.get("Weight (%)", {}).get("number", None)
                if weight_num is not None:
                    weight_pct = weight_num * 100.0 if weight_num <= 1.0 else weight_num
                    prev_weights[ticker] = weight_pct
                
                # 오늘 이미 등록된 페이지라면 중복 방지를 위해 아카이브(삭제) 처리
                # 과거 날짜 페이지는 아카이브하지 않고 캘린더 기록용으로 보존합니다!
                if page_date == today_str:
                    requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json={"archived": True}, timeout=10)
                
        # 2. 신규 추천 항목 생성 (어제 비중 대조를 통한 전일 대비 변동률 및 BUY / HOLD 판정)
        for item in portfolio_list:
            create_url = "https://api.notion.com/v1/pages"
            
            sym = item.get("symbol", "")
            name = item.get("name", "")
            market = item.get("market", "")
            industry = item.get("industry", "")
            score = item.get("score", 0.0)
            weight = item.get("weight", 0.0)
            amount = item.get("amount", 0.0)
            
            # 회사 한국어 이름과 코드 통합 표기
            company_name = get_korean_company_name(sym)
            clean_name = company_name if company_name != sym else name
            
            # 국장/미장 국기 이모지 표기
            flag = "🇺🇸" if market == "SP500" else "🇰🇷"
            stock_display = f"{flag} {sym}"
            
            # 전날 비중 대조하여 전일 대비 변동 계산
            prev_w = prev_weights.get(sym, None)
            if prev_w is None:
                action = "BUY"
                diff_str = "🆕 신규 편입"
            else:
                action = "HOLD"
                diff = weight - prev_w
                if abs(diff) < 0.01:
                    diff_str = "➖ 변동 없음"
                elif diff > 0:
                    diff_str = f"🔺 +{diff:.2f}%p"
                else:
                    diff_str = f"🔻 {diff:.2f}%p"
            
            currency = "USD" if market == "SP500" else "KRW"
            score_str = f"{score:+.2f}"
            weight_str = f"{weight:.2f}%"
            amount_str = f"보유금의 {weight:.2f}%"
            
            weight_val = weight / 100.0
            
            payload = {
                "parent": {"database_id": db_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": clean_name}}]},
                    "Symbol": {"rich_text": [{"text": {"content": stock_display}}]},
                    "Market": {"rich_text": [{"text": {"content": market}}]},
                    "Industry": {"rich_text": [{"text": {"content": industry}}]},
                    "NewsScore": {"rich_text": [{"text": {"content": score_str}}]},
                    "Weight": {"rich_text": [{"text": {"content": weight_str}}]},
                    "InvestAmount": {"rich_text": [{"text": {"content": amount_str}}]},
                    "Currency": {"select": {"name": currency}},
                    "Action": {"select": {"name": action}},
                    "Weight (%)": {"number": weight_val},
                    "보유금 대비 비중 (%)": {"number": weight_val},
                    "전일 대비": {"rich_text": [{"text": {"content": diff_str}}]},
                    "Date": {"date": {"start": today_str}}
                }
            }
            res_create = requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
            if res_create.status_code not in [200, 201]:
                print(f"[Notion Recommend Warning] Page creation failed. Status: {res_create.status_code}, Res: {res_create.text}")
                
        print(f"[Notion Recommend] 성공적으로 {len(portfolio_list)}개의 추천 포트폴리오를 동기화 완료했습니다. (전일 대비 변동 기록 완료)")
    except Exception as e:
        print(f"[Notion Recommend Error] {e}")

def ensure_ranking_db_properties(db_id):
    """
    🏆 퀀트 종목 랭킹 데이터베이스에 날짜(Date) 속성이 존재하고 올바른 타입으로 정의되어 있는지 확인하고 자동 추가합니다.
    """
    url = f"https://api.notion.com/v1/databases/{db_id}"
    payload = {
        "properties": {
            "Date": {
                "date": {}
            }
        }
    }
    try:
        requests.patch(url, headers=HEADERS, json=payload, timeout=10)
    except Exception as e:
        print(f"[Notion Properties Warning] Failed to update ranking database schema: {e}")

def sync_rankings_to_notion(rankings_list):
    """
    국장 및 미장 종목 랭킹 리스트를 각각 '🏆 국장 퀀트 종목 랭킹' 및 '🏆 미장 퀀트 종목 랭킹' 데이터베이스에 동기화합니다.
    - rankings_list: [{"name": name, "symbol": sym, "market": mkt, "rank": rank, "score": score, "industry": ind}] 리스트
    """
    if not NOTION_TOKEN:
        return
        
    db_kr_id = find_database_by_name("🏆 국장 퀀트 종목 랭킹")
    db_us_id = find_database_by_name("🏆 미장 퀀트 종목 랭킹")
    
    if not db_kr_id or not db_us_id:
        print("[Notion Ranking] 데이터베이스를 찾을 수 없어 랭킹 동기화를 건너뜁니다.")
        return
        
    try:
        # 두 데이터베이스 속성 보강
        ensure_ranking_db_properties(db_kr_id)
        ensure_ranking_db_properties(db_us_id)
        
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 국장 및 미장 아이템 분류
        kr_items = [item for item in rankings_list if item.get("market") == "KRX"]
        us_items = [item for item in rankings_list if item.get("market") != "KRX"]
        
        # 1. 오늘 날짜로 이미 동기화된 항목이 있다면 중복 제거를 위해 아카이브 처리
        for db_id in [db_kr_id, db_us_id]:
            query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
            filter_payload = {
                "filter": {
                    "property": "Date",
                    "date": {
                        "equals": today_str
                    }
                },
                "page_size": 100
            }
            res = requests.post(query_url, headers=HEADERS, json=filter_payload, timeout=10)
            if res.status_code == 200:
                results = res.json().get("results", [])
                for page in results:
                    page_id = page.get("id")
                    requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json={"archived": True}, timeout=10)
                    
        # 2. 국장 신규 랭킹 생성 (오늘 날짜 부여)
        # 순위가 정돈되어 들어가도록 Rank 역순(20위부터 1위)으로 생성하여 노션 디폴트 정렬 시 1위가 맨 위로 오도록 함
        kr_items_sorted = sorted(kr_items, key=lambda x: x.get("rank", 999), reverse=True)
        for item in kr_items_sorted:
            create_url = "https://api.notion.com/v1/pages"
            rank_val = item.get("rank", 0)
            sym = item.get("symbol", "")
            name = item.get("name", "")
            
            # 회사 한국어 이름과 코드 통합 표기
            company_name = get_korean_company_name(sym)
            clean_name = company_name if company_name != sym else name
            stock_display = f"🇰🇷 {sym}"
            
            display_name = f"[{rank_val}위] {clean_name}"
            payload = {
                "parent": {"database_id": db_kr_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": display_name}}]},
                    "Symbol": {"rich_text": [{"text": {"content": stock_display}}]},
                    "Rank": {"number": rank_val},
                    "Score": {"number": round(item.get("score", 0.0), 4)},
                    "Industry": {"rich_text": [{"text": {"content": item.get("industry", "")}}]},
                    "Date": {"date": {"start": today_str}}
                }
            }
            res_create = requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
            if res_create.status_code not in [200, 201]:
                print(f"[Notion Ranking Warning] KR page creation failed. Status: {res_create.status_code}, Res: {res_create.text}")
            
        # 3. 미장 신규 랭킹 생성 (오늘 날짜 부여)
        # 순위가 정돈되어 들어가도록 Rank 역순(20위부터 1위)으로 생성
        us_items_sorted = sorted(us_items, key=lambda x: x.get("rank", 999), reverse=True)
        for item in us_items_sorted:
            create_url = "https://api.notion.com/v1/pages"
            rank_val = item.get("rank", 0)
            sym = item.get("symbol", "")
            name = item.get("name", "")
            
            # 회사 한국어 이름과 코드 통합 표기
            company_name = get_korean_company_name(sym)
            clean_name = company_name if company_name != sym else name
            stock_display = f"🇺🇸 {sym}"
            
            display_name = f"[{rank_val}위] {clean_name}"
            payload = {
                "parent": {"database_id": db_us_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": display_name}}]},
                    "Symbol": {"rich_text": [{"text": {"content": stock_display}}]},
                    "Rank": {"number": rank_val},
                    "Score": {"number": round(item.get("score", 0.0), 4)},
                    "Industry": {"rich_text": [{"text": {"content": item.get("industry", "")}}]},
                    "Date": {"date": {"start": today_str}}
                }
            }
            res_create = requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
            if res_create.status_code not in [200, 201]:
                print(f"[Notion Ranking Warning] US page creation failed. Status: {res_create.status_code}, Res: {res_create.text}")
            
        print(f"[Notion Ranking] 국장/미장 각각 랭킹 동기화를 완료했습니다.")
    except Exception as e:
        print(f"[Notion Ranking Error] {e}")

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
                    if "주식 자동 리밸런싱 대시보드" in page_title:
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
                    "Date": {"date": {}},
                    "Market": {
                        "select": {
                            "options": [
                                {"name": "KRX", "color": "green"},
                                {"name": "S&P500", "color": "blue"}
                            ]
                        }
                    }
                }
            }
            c_res = requests.post(create_url, headers=HEADERS, json=db_payload, timeout=10)
            if c_res.status_code == 200:
                created_count += 1
            else:
                return f"'📰 주요 시장 뉴스' 디비 생성 실패: {c_res.text}"

        # 6. '💡 퀀트 추천 포트폴리오' 데이터베이스 생성
        recommend_db_id = find_database_by_name("💡 퀀트 추천 포트폴리오")
        if not recommend_db_id:
            create_url = "https://api.notion.com/v1/databases"
            db_payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": "💡 퀀트 추천 포트폴리오"}}],
                "properties": {
                    "Name": {"title": {}},
                    "Symbol": {"rich_text": {}},
                    "Market": {"rich_text": {}},
                    "Industry": {"rich_text": {}},
                    "NewsScore": {"rich_text": {}},
                    "Weight": {"rich_text": {}},
                    "InvestAmount": {"rich_text": {}},
                    "Currency": {
                        "select": {
                            "options": [
                                {"name": "KRW", "color": "green"},
                                {"name": "USD", "color": "blue"}
                            ]
                        }
                    },
                    "Action": {
                        "select": {
                            "options": [
                                {"name": "BUY", "color": "green"},
                                {"name": "HOLD", "color": "yellow"},
                                {"name": "SELL", "color": "red"}
                            ]
                        }
                    },
                    "Weight (%)": {
                        "number": {
                            "format": "percent"
                        }
                    },
                    "보유금 대비 비중 (%)": {
                        "number": {
                            "format": "percent"
                        }
                    }
                }
            }
            c_res = requests.post(create_url, headers=HEADERS, json=db_payload, timeout=10)
            if c_res.status_code == 200:
                created_count += 1
            else:
                return f"'💡 퀀트 추천 포트폴리오' 디비 생성 실패: {c_res.text}"

        # 7. '🏆 국장 퀀트 종목 랭킹' 및 '🏆 미장 퀀트 종목 랭킹' 데이터베이스 생성
        old_ranking_db_id = find_database_by_name("🏆 퀀트 종목 랭킹")
        if old_ranking_db_id:
            # 기존 통합 랭킹 DB가 존재하면 깔끔하게 아카이브 처리
            requests.patch(f"https://api.notion.com/v1/pages/{old_ranking_db_id}", headers=HEADERS, json={"archived": True}, timeout=10)

        kr_ranking_db_id = find_database_by_name("🏆 국장 퀀트 종목 랭킹")
        if not kr_ranking_db_id:
            create_url = "https://api.notion.com/v1/databases"
            db_payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": "🏆 국장 퀀트 종목 랭킹"}}],
                "properties": {
                    "Name": {"title": {}},
                    "Symbol": {"rich_text": {}},
                    "Rank": {"number": {"format": "number"}},
                    "Score": {"number": {"format": "number"}},
                    "Industry": {"rich_text": {}},
                    "Date": {"date": {}}
                }
            }
            c_res = requests.post(create_url, headers=HEADERS, json=db_payload, timeout=10)
            if c_res.status_code == 200:
                created_count += 1
            else:
                return f"'🏆 국장 퀀트 종목 랭킹' 디비 생성 실패: {c_res.text}"

        us_ranking_db_id = find_database_by_name("🏆 미장 퀀트 종목 랭킹")
        if not us_ranking_db_id:
            create_url = "https://api.notion.com/v1/databases"
            db_payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": "🏆 미장 퀀트 종목 랭킹"}}],
                "properties": {
                    "Name": {"title": {}},
                    "Symbol": {"rich_text": {}},
                    "Rank": {"number": {"format": "number"}},
                    "Score": {"number": {"format": "number"}},
                    "Industry": {"rich_text": {}},
                    "Date": {"date": {}}
                }
            }
            c_res = requests.post(create_url, headers=HEADERS, json=db_payload, timeout=10)
            if c_res.status_code == 200:
                created_count += 1
            else:
                return f"'🏆 미장 퀀트 종목 랭킹' 디비 생성 실패: {c_res.text}"

        # 8. '🚨 퀀트 매도 시그널' 데이터베이스 생성
        sell_db_id = find_database_by_name("🚨 퀀트 매도 시그널")
        if not sell_db_id:
            create_url = "https://api.notion.com/v1/databases"
            db_payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": "🚨 퀀트 매도 시그널"}}],
                "properties": {
                    "Name": {"title": {}},
                    "Symbol": {"rich_text": {}},
                    "Reason": {"rich_text": {}},
                    "Date": {"date": {}},
                    "Market": {
                        "select": {
                            "options": [
                                {"name": "KRX", "color": "green"},
                                {"name": "S&P500", "color": "blue"}
                            ]
                        }
                    },
                    "Action": {
                        "select": {
                            "options": [
                                {"name": "BUY", "color": "green"},
                                {"name": "HOLD", "color": "yellow"},
                                {"name": "SELL", "color": "red"}
                            ]
                        }
                    }
                }
            }
            c_res = requests.post(create_url, headers=HEADERS, json=db_payload, timeout=10)
            if c_res.status_code == 200:
                created_count += 1
            else:
                return f"'🚨 퀀트 매도 시그널' 디비 생성 실패: {c_res.text}"

        if created_count > 0:
            return f"성공적으로 {created_count}개의 데이터베이스를 노션 페이지 하위에 생성/연동 완료했습니다!"
        else:
            return "이미 필요한 데이터베이스들이 노션 워크스페이스에 생성되어 연동된 상태입니다."
            
    except Exception as e:
        return f"노션 자동 설정 중 오류 발생: {e}"

def sync_sell_signals_to_notion(sell_list):
    """
    오늘 매도(SELL) 시그널이 발생한 종목들을 '🚨 퀀트 매도 시그널' 데이터베이스에 동기화합니다.
    - sell_list: [{"symbol": sym, "name": name, "reason": reason, "market": mkt}] 리스트
    """
    if not NOTION_TOKEN:
        return
        
    db_id = find_database_by_name("🚨 퀀트 매도 시그널")
    if not db_id:
        print("[Notion Sell Signal] Database 'SELL Signal' not found. Creating...")
        setup_notion_workspace()
        db_id = find_database_by_name("🚨 퀀트 매도 시그널")
        if not db_id:
            return
            
    try:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 1. 오늘 날짜로 이미 동기화된 매도 시그널 항목 아카이브 (중복 방지)
        query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
        res = requests.post(query_url, headers=HEADERS, json={"page_size": 100}, timeout=10)
        if res.status_code == 200:
            for page in res.json().get("results", []):
                date_prop = page.get("properties", {}).get("Date", {}).get("date", {})
                page_date = date_prop.get("start", "") if date_prop else ""
                if page_date == today_str:
                    requests.patch(f"https://api.notion.com/v1/pages/{page.get('id')}", headers=HEADERS, json={"archived": True}, timeout=10)
                    
        # 2. 오늘 매도 항목 생성
        if sell_list:
            for item in sell_list:
                create_url = "https://api.notion.com/v1/pages"
                sym = item.get("symbol", "")
                name = item.get("name", "")
                reason = item.get("reason", "손절선 이탈 또는 비중 교체")
                mkt = item.get("market", "KRX" if (sym.endswith(".KS") or sym.endswith(".KQ")) else "S&P500")
                
                c_name = get_korean_company_name(sym)
                clean_name = c_name if c_name != sym else name
                flag = "🇺🇸" if mkt == "S&P500" else "🇰🇷"
                stock_disp = f"{flag} {sym}"
                
                payload = {
                    "parent": {"database_id": db_id},
                    "properties": {
                        "Name": {"title": [{"text": {"content": clean_name}}]},
                        "Symbol": {"rich_text": [{"text": {"content": stock_disp}}]},
                        "Action": {"select": {"name": "SELL"}},
                        "Reason": {"rich_text": [{"text": {"content": reason}}]},
                        "Market": {"select": {"name": mkt}},
                        "Date": {"date": {"start": today_str}}
                    }
                }
                requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
            print(f"[Notion Sell Signal] Synced {len(sell_list)} SELL items.")
        else:
            # 매도 종목이 없으면 '안전' 안내 카드 추가
            create_url = "https://api.notion.com/v1/pages"
            payload = {
                "parent": {"database_id": db_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": "🟢 오늘 매도할 종목이 없습니다 (안전 보유 중)"}}]},
                    "Symbol": {"rich_text": [{"text": {"content": "안전"}}]},
                    "Action": {"select": {"name": "HOLD"}},
                    "Reason": {"rich_text": [{"text": {"content": "모든 보유 종목이 손절선 위에서 안정적으로 추세를 유지하고 있습니다."}}]},
                    "Market": {"select": {"name": "KRX"}},
                    "Date": {"date": {"start": today_str}}
                }
            }
            requests.post(create_url, headers=HEADERS, json=payload, timeout=10)
            print("[Notion Sell Signal] No SELL signals today (Added safety info page).")
    except Exception as e:
        print(f"[Notion Sell Signal Error] {e}")

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
                    if page_title.strip().startswith("주식 자동 리밸런싱 대시보드"):
                        page_id = page.get("id")
                        break
            if page_id:
                break
                
        if not page_id:
            return "노션에서 '주식 자동 리밸런싱 대시보드' 페이지를 찾을 수 없습니다."

        # 시장 국면 계절에 따른 동적 아이콘/커버 로드 (Supabase 동기화 반영)
        regime_val = "UNKNOWN"
        try:
            import portfolio_state
            reg = portfolio_state.load_market_regime()
            if isinstance(reg, dict):
                regime_val = reg.get("US", "UNKNOWN")
            else:
                regime_val = str(reg)
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

        # 3. 기존에 추가된 블록 목록 조회하여 원칙 박스와 팁 박스가 이미 있는지 개별 검사
        blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        b_res = requests.get(blocks_url, headers=HEADERS, timeout=10)
        has_callout = False
        has_tips = False
        if b_res.status_code == 200:
            blocks = b_res.json().get("results", [])
            for block in blocks:
                if block.get("type") == "callout":
                    c_text = ""
                    rich_text = block.get("callout", {}).get("rich_text", [])
                    if rich_text:
                        c_text = rich_text[0].get("text", {}).get("content", "")
                    if "3대 절대 원칙" in c_text or "절대 원칙" in c_text:
                        has_callout = True
                    if "대시보드 뷰 커스텀" in c_text or "뷰 커스텀 팁" in c_text:
                        has_tips = True
        
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
                    }
                ]
            }
            requests.patch(blocks_url, headers=HEADERS, json=children_payload, timeout=10)
            
        # 5. 팁 콜아웃 박스 추가 (없을 경우에만)
        if not has_tips:
            tips_payload = {
                "children": [
                    {
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "📅 대시보드 뷰 커스텀 팁\n1. 거래 일지 / 뉴스 캘린더화: 데이터베이스 상단 '+' 버튼 클릭 -> '캘린더' 선택 (기준 날짜: Date)\n2. 주요시장뉴스 국장/미장 분리: 탭 복사 후 필터 -> Market을 'KRX' 또는 'S&P500'으로 필터링\n3. 퀀트 랭킹 캘린더: 국장/미장 퀀트 랭킹도 상단 '+' 클릭 -> '캘린더' 선택 시 날짜별로 보기가 바뀝니다."
                                    }
                                }
                            ],
                            "icon": {"type": "emoji", "emoji": "💡"},
                            "color": "yellow_background"
                        }
                    },
                    {
                        "object": "block",
                        "type": "divider",
                        "divider": {}
                    }
                ]
            }
            requests.patch(blocks_url, headers=HEADERS, json=tips_payload, timeout=10)
            
        return "노션 페이지 디자인 꾸미기가 완료되었습니다!"
    except Exception as e:
        return f"노션 디자인 꾸미기 중 오류 발생: {e}"

def calculate_portfolio_returns():
    """
    월요일 매수 가정을 기반으로 퀀트 추천 포트폴리오의 주간 수익률 및 월간 수익률을 동적으로 연산합니다.
    """
    try:
        import yfinance as yf
        import numpy as np
        
        # 1. 노션 '💡 퀀트 추천 포트폴리오' 종목 추출 시도
        all_tickers = []
        try:
            portfolio_db_id = find_database_by_name("💡 퀀트 추천 포트폴리오")
            if portfolio_db_id:
                url = f"https://api.notion.com/v1/databases/{portfolio_db_id}/query"
                res = requests.post(url, headers=HEADERS, json={"page_size": 100}, timeout=10)
                if res.status_code == 200:
                    for p in res.json().get("results", []):
                        props = p.get("properties", {})
                        sym_list = props.get("Symbol", {}).get("rich_text", [])
                        sym = sym_list[0].get("text", {}).get("content", "") if sym_list else ""
                        clean_sym = sym.replace("🇺🇸", "").replace("🇰🇷", "").strip()
                        if clean_sym and clean_sym not in all_tickers:
                            all_tickers.append(clean_sym)
        except Exception:
            pass
            
        if not all_tickers:
            all_tickers = ['AAPL', 'MSFT', 'CVX', '005930.KS', '000660.KS', '000270.KS', '055550.KS', '011200.KS', '105560.KS', '033780.KS']
            
        now = datetime.datetime.now()
        df_prices = yf.download(all_tickers, period='60d', progress=False)
        close_df = df_prices['Close'] if 'Close' in df_prices.columns else df_prices
        
        w_rets = []
        m_rets = []
        first_day_of_month = datetime.date(now.year, now.month, 1)
        
        for t in all_tickers:
            try:
                if t in close_df.columns:
                    series_t = close_df[t].dropna()
                    if len(series_t) >= 5:
                        p_latest = float(series_t.iloc[-1])
                        
                        # 주간 (최근 5영업일 전 대비 변동 %)
                        p_5d_ago = float(series_t.iloc[-5])
                        w_rets.append(((p_latest - p_5d_ago) / p_5d_ago) * 100.0)
                        
                        # 월간 (당월 1일 이후 첫 거래일 대비 변동 %)
                        m_post = series_t.loc[first_day_of_month.strftime("%Y-%m-%d"):]
                        if len(m_post) > 0:
                            p_m_start = float(m_post.iloc[0])
                        else:
                            p_m_start = float(series_t.iloc[-20])
                        m_rets.append(((p_latest - p_m_start) / p_m_start) * 100.0)
            except Exception:
                pass
                
        w_ret = float(np.mean(w_rets)) if w_rets else 0.0
        m_ret = float(np.mean(m_rets)) if m_rets else 0.0
        return w_ret, m_ret
    except Exception as e:
        print(f"[Return Calc Warning] {e}")
        return 0.0, 0.0

def get_previous_notion_recommended_symbols():
    """
    노션 '💡 퀀트 추천 포트폴리오' 데이터베이스에서 직전/기존 추천 종목 심볼 목록을 조회합니다.
    """
    if not NOTION_TOKEN:
        return {}
    db_id = find_database_by_name("💡 퀀트 추천 포트폴리오")
    if not db_id:
        return {}
    
    try:
        url = f"https://api.notion.com/v1/databases/{db_id}/query"
        res = requests.post(url, headers=HEADERS, json={"page_size": 100}, timeout=10)
        prev_symbols = {}
        if res.status_code == 200:
            for p in res.json().get("results", []):
                props = p.get("properties", {})
                sym_list = props.get("Symbol", {}).get("rich_text", [])
                sym = sym_list[0].get("text", {}).get("content", "") if sym_list else ""
                clean_sym = sym.replace("🇺🇸", "").replace("🇰🇷", "").strip()
                name_list = props.get("Name", {}).get("title", [])
                name = name_list[0].get("text", {}).get("content", "") if name_list else ""
                if clean_sym:
                    prev_symbols[clean_sym] = name
        return prev_symbols
    except Exception as e:
        print(f"[Get Prev Notion Symbols Error] {e}")
        return {}

def update_notion_regime_style(regime_val):
    """
    현재 매크로 국면에 따라 노션 대시보드 페이지의 커버 이미지와 이모지를 동적으로 변경하고 메인 수익률 현황판을 업데이트합니다.
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

        # 1. 국장/미장 계절 값 파싱
        regime_us = "SPRING"
        regime_kr = "SPRING"
        val_str = str(regime_val).strip()
        
        if val_str.startswith("{") or val_str.startswith("'{") or val_str.startswith('"{'):
            try:
                import json
                clean_str = val_str.strip("'\"")
                data = json.loads(clean_str)
                regime_us = data.get("US", "SPRING")
                regime_kr = data.get("KR", "SPRING")
            except Exception:
                pass
        elif val_str.startswith("("):
            try:
                val_eval = eval(val_str)
                if isinstance(val_eval, tuple) and len(val_eval) >= 2:
                    regime_us = val_eval[0]
                    regime_kr = val_eval[1]
            except Exception:
                pass
        else:
            regime_us = val_str
            regime_kr = val_str

        # 계절별 속성 딕셔너리
        regime_attrs = {
            "SPRING": {"emoji": "🌸", "name": "봄 (SPRING) - 성장 국면 (적극 매수)", "color": "green_background", "cover": "https://images.unsplash.com/photo-1522748906645-95d8adfd52c7?q=80&w=2070&auto=format&fit=crop"},
            "SUMMER": {"emoji": "☀️", "name": "여름 (SUMMER) - 과열 국면 (선별 매수)", "color": "orange_background", "cover": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?q=80&w=2073&auto=format&fit=crop"},
            "FALL": {"emoji": "🍁", "name": "가을 (FALL) - 쇠퇴 국면 (자산 방어)", "color": "yellow_background", "cover": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?q=80&w=2070&auto=format&fit=crop"},
            "WINTER": {"emoji": "❄️", "name": "겨울 (WINTER) - 위축 국면 (현금/숏)", "color": "blue_background", "cover": "https://images.unsplash.com/photo-1491002052546-bf38f186af56?q=80&w=2008&auto=format&fit=crop"}
        }

        # 기본 속성 폴백
        default_attr = {"emoji": "📈", "name": "UNKNOWN", "color": "gray_background", "cover": "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?q=80&w=2070&auto=format&fit=crop"}
        attr_us = regime_attrs.get(regime_us, default_attr)
        attr_kr = regime_attrs.get(regime_kr, default_attr)

        # 2. 페이지 아이콘 및 커버 설정 (미장 기준으로 비주얼 일관성 유지)
        page_url = f"https://api.notion.com/v1/pages/{page_id}"
        title_suffix = f" (현재 계절: 미장 {attr_us['emoji']} / 국장 {attr_kr['emoji']})"
        
        page_payload = {
            "icon": {
                "type": "emoji",
                "emoji": attr_us["emoji"]
            },
            "cover": {
                "type": "external",
                "external": {
                    "url": attr_us["cover"]
                }
            },
            "properties": {
                "title": {
                    "title": [{"text": {"content": f"주식 자동 리밸런싱 대시보드{title_suffix}"}}]
                }
            }
        }
        requests.patch(page_url, headers=HEADERS, json=page_payload, timeout=10)

        # 3. 페이지 본문 내부의 '현재 시장 계절' 콜아웃 박스 찾기
        blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        b_res = requests.get(blocks_url, headers=HEADERS, timeout=10)
        regime_block_id = None
        if b_res.status_code == 200:
            blocks = b_res.json().get("results", [])
            for block in blocks:
                if block.get("type") == "callout":
                    c_texts = block.get("callout", {}).get("rich_text", [])
                    c_text = "".join([t.get("plain_text", "") for t in c_texts]).strip()
                    if "현재 시장 계절" in c_text or "시장 계절:" in c_text or "미국 시장 (S&P500):" in c_text or "퀀트 추천 포트폴리오" in c_text:
                        regime_block_id = block.get("id")
                        break

        # 4. 현황판에 표시할 텍스트 템플릿 구성 (수익률 현황 + 국장/미장 계절 분리)
        w_ret, m_ret = calculate_portfolio_returns()
        w_str = f"+{w_ret:.2f}% 🔺" if w_ret > 0 else (f"{w_ret:.2f}% 🔻" if w_ret < 0 else "0.00% ➖")
        m_str = f"+{m_ret:.2f}% 🔺" if m_ret > 0 else (f"{m_ret:.2f}% 🔻" if m_ret < 0 else "0.00% ➖")

        now_m = datetime.datetime.now().month
        regime_text = (
            f"📊 퀀트 추천 포트폴리오 수익률 성과 현황 (월요일 매수 가정)\n"
            f"• 🗓️ 주간 수익률 (이번 주 월요일 매수 시): {w_str}\n"
            f"• 📅 {now_m}월 누적 수익률 ({now_m}/1 ~ 오늘): {m_str}\n\n"
            f"🌐 현재 시장 계절 (Market Season Summary)\n"
            f"• 🇺🇸 미국 시장 (S&P500): {attr_us['emoji']} {attr_us['name']}\n"
            f"• 🇰🇷 한국 시장 (KRX): {attr_kr['emoji']} {attr_kr['name']}"
        )
        
        # 콜아웃의 색상은 미장 색상으로 설정
        regime_color = attr_us["color"]

        if regime_block_id:
            # 기존 블록 내용 패치
            patch_block_url = f"https://api.notion.com/v1/blocks/{regime_block_id}"
            patch_payload = {
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": regime_text}}],
                    "icon": {"type": "emoji", "emoji": attr_us["emoji"]},
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
                            "icon": {"type": "emoji", "emoji": attr_us["emoji"]},
                            "color": regime_color
                        }
                    }
                ]
            }
            requests.patch(blocks_url, headers=HEADERS, json=append_payload, timeout=10)

    except Exception as e:
        print(f"[Notion Regime Style Update Error] {e}")
