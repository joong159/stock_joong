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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

HEADERS_NOTION = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def get_notion_trade_logs():
    """
    노션의 '주식 거래 일지' 데이터베이스에서 거래 기록들을 가져옵니다.
    """
    from notion_sync import find_database_by_name
    db_id = find_database_by_name("주식 거래 일지")
    if not db_id:
        return None, "노션에서 '주식 거래 일지' 데이터베이스를 찾을 수 없습니다."

    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    try:
        res = requests.post(url, headers=HEADERS_NOTION, json={}, timeout=10)
        if res.status_code != 200:
            return None, f"노션 API 호출 실패 (상태코드: {res.status_code})"
            
        results = res.json().get("results", [])
        trades = []
        for page in results:
            props = page.get("properties", {})
            
            # Title
            title_prop = props.get("Name", {}).get("title", [])
            title = "".join([t.get("plain_text", "") for t in title_prop]).strip()
            
            # Date
            date_prop = props.get("Date", {}).get("date")
            date_str = date_prop.get("start") if date_prop else ""
            
            # Symbol
            sym_prop = props.get("Symbol", {}).get("rich_text", [])
            symbol = "".join([t.get("plain_text", "") for t in sym_prop]).strip()
            
            # Side
            side_prop = props.get("Side", {}).get("select")
            side = side_prop.get("name") if side_prop else ""
            
            # Qty
            qty_prop = props.get("Qty", {}).get("number")
            qty = float(qty_prop) if qty_prop is not None else 0.0
            
            # Price
            price_prop = props.get("Price", {}).get("number")
            price = float(price_prop) if price_prop is not None else 0.0
            
            # Value
            val_prop = props.get("Value", {}).get("number")
            val_krw = float(val_prop) if val_prop is not None else 0.0
            
            # Reason
            reason_prop = props.get("Reason", {}).get("rich_text", [])
            reason = "".join([t.get("plain_text", "") for t in reason_prop]).strip()
            
            trades.append({
                "title": title,
                "date": date_str,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "val_krw": val_krw,
                "reason": reason
            })
        return trades, None
    except Exception as e:
        return None, f"노션 연동 중 오류 발생: {e}"

def get_notion_market_news():
    """
    노션의 '📰 주요 시장 뉴스' 데이터베이스에서 최근 뉴스 기록들을 가져옵니다.
    """
    from notion_sync import find_database_by_name
    db_id = find_database_by_name("📰 주요 시장 뉴스")
    if not db_id:
        return None, "노션에서 '📰 주요 시장 뉴스' 데이터베이스를 찾을 수 없습니다."

    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    try:
        res = requests.post(url, headers=HEADERS_NOTION, json={"page_size": 20}, timeout=10)
        if res.status_code != 200:
            return None, f"노션 API 호출 실패 (상태코드: {res.status_code})"
            
        results = res.json().get("results", [])
        news_items = []
        for page in results:
            props = page.get("properties", {})
            
            # Title
            title_prop = props.get("Name", {}).get("title", [])
            title = "".join([t.get("plain_text", "") for t in title_prop]).strip()
            
            # Stock
            stock_prop = props.get("Stock", {}).get("rich_text", [])
            stock = "".join([t.get("plain_text", "") for t in stock_prop]).strip()
            
            # Publisher
            pub_prop = props.get("Publisher", {}).get("rich_text", [])
            publisher = "".join([t.get("plain_text", "") for t in pub_prop]).strip()
            
            # Link
            link = props.get("Link", {}).get("url") or ""
            
            # Date
            date_prop = props.get("Date", {}).get("date")
            date_str = date_prop.get("start") if date_prop else ""
            
            news_items.append({
                "title": title,
                "stock": stock,
                "publisher": publisher,
                "link": link,
                "date": date_str
            })
        return news_items, None
    except Exception as e:
        return None, f"노션 연동 중 뉴스 조회 오류 발생: {e}"

def generate_trading_analysis_report():
    """
    노션 매매일지 데이터를 추출하여 Gemini API를 활용한 투자 행동 분석 보고서를 생성합니다.
    """
    if not GEMINI_API_KEY:
        return "⚠️ 오류: .env 파일에 GEMINI_API_KEY가 등록되어 있지 않습니다.\nGoogle AI Studio (https://aistudio.google.com/)에서 API Key를 발급받아 .env 파일에 추가해 주세요."

    trades, err = get_notion_trade_logs()
    if err:
        return f"⚠️ 오류: {err}"
        
    if not trades:
        return "📋 분석을 진행할 거래 기록이 노션 '주식 거래 일지' 데이터베이스에 존재하지 않습니다.\n대시보드에서 국장/미장 실거래 주문을 최소 1건 이상 실행하여 일지가 기록된 뒤 다시 시도해 주세요!"

    # 매매 내역을 마크다운 텍스트 테이블로 변환
    trade_text_lines = []
    trade_text_lines.append("| 날짜 | 종목 | 매수/매도 | 수량 | 가격 | 거래 금액(원화) | 매매 사유 |")
    trade_text_lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    
    # 시간 순 정렬 (오래된 순)
    sorted_trades = sorted([t for t in trades if t['date']], key=lambda x: x['date'])
    
    for t in sorted_trades:
        # 날짜 포맷
        d = t['date'][:16].replace("T", " ") if t['date'] else "N/A"
        
        # Qty 포맷
        qty_str = f"{t['qty']:.6f}" if t['qty'] % 1 != 0 else f"{int(t['qty'])}"
        
        # Price 포맷
        is_us_ticker = t['symbol'].replace(".", "").isalpha()
        if is_us_ticker:
            price_str = f"${t['price']:,.2f}"
        else:
            price_str = f"₩{int(t['price']):,}"
            
        trade_text_lines.append(
            f"| {d} | {t['symbol']} | {t['side']} | {qty_str} | {price_str} | {int(t['val_krw']):,}원 | {t['reason']} |"
        )
    
    trade_table_markdown = "\n".join(trade_text_lines)

    # 시장 국면 계절 로드
    regime = "알 수 없음 (분석 대기 중)"
    if os.path.exists(".market_regime.txt"):
        try:
            with open(".market_regime.txt", "r", encoding="utf-8") as f:
                regime_val = f.read().strip()
                if regime_val == "SPRING":
                    regime = "🌸 봄 (SPRING) - 성장국면"
                elif regime_val == "SUMMER":
                    regime = "☀️ 여름 (SUMMER) - 과열국면"
                elif regime_val == "FALL":
                    regime = "🍁 가을 (FALL) - 쇠퇴국면"
                elif regime_val == "WINTER":
                    regime = "❄️ 겨울 (WINTER) - 위축국면"
                else:
                    regime = regime_val
        except Exception:
            pass

    # 주요 시장 뉴스 조회
    news_items, _ = get_notion_market_news()
    news_text = ""
    if news_items:
        news_lines = []
        for n in news_items:
            date_part = n['date'][:10] if n['date'] else "N/A"
            news_lines.append(f"- [{n['stock']}] {n['title']} (출처: {n['publisher']}, 날짜: {date_part})")
        news_text = "\n".join(news_lines)
    else:
        news_text = "최근 등록된 보유 종목 관련 주요 뉴스가 없습니다."

    # Gemini 프롬프트 구축
    prompt = f"""
당신은 세계적인 투자은행(IB)의 수석 시장 전략가(Chief Market Strategist)이자 최고 애널리스트(Chief Analyst)입니다.
사용자의 최근 주식 거래 내역과 현재 보유 종목들에 대한 최근 주요 뉴스 헤드라인, 그리고 분석된 매크로 시장 계절(국면) 정보를 대조하여 **현재 시장의 분위기와 센티먼트를 애널리스트 수준으로 냉철하고 정교하게 분석한 시장 분석 보고서**를 작성해 주십시오.

[현재 매크로 시장 계절 (Market Regime)]
- {regime}

[보유 종목 관련 최근 주요 뉴스 및 헤드라인]
{news_text}

[사용자의 매매 일지 기록 (최근 거래 내역)]
{trade_table_markdown}

위 정보들을 종합적으로 분석하여 아래 서식에 맞게 마크다운(Markdown) 보고서로 작성해 주세요. 
어투는 금융 리포트 특유의 격식 있고 정밀한 어조(하십시오체, 경어체)를 사용하고, 시장 상황에 대해 지나치게 감상적이거나 낙관적인 태도를 배제하고 데이터와 뉴스 센티먼트에 기반하여 날카롭게 서술해 주십시오.

보고서 서식 양식 (Markdown 형식):
# 📈 월가 수석 전략가 AI 시장 센티먼트 & 포트폴리오 진단 보고서

## 1. 🌐 글로벌 매크로 동향 & 시장 계절(국면) 분석
- 현재 판단된 시장의 계절(국면)이 **{regime}**인 점과 글로벌 매크로 상황을 결합하여, 현재 주식시장의 전반적인 심리(위험 선호 vs 위험 회피) 및 자산군 분위기를 매크로 관점에서 명확하게 진단해 주십시오.

## 2. 📰 보유 종목별 뉴스 센티먼트 & 실시간 리스크 평가
- 제공된 최신 뉴스 헤드라인과 종목 정보를 바탕으로, 사용자 포트폴리오 종목들의 주요 호재/악재와 시장의 반응(센티먼트)을 애널리스트 관점에서 해석해 주십시오.
- 최근 시장 이슈가 해당 종목들의 중단기 주가 흐름에 미칠 영향과 잠재적 리스크 요인을 짚어 주십시오.

## 3. ⚖️ 최근 매매 일지 피드백 & 전략적 제언
- 최근 매매 일지 기록의 거래 내역(매수/매도 시점, 금액, 사유)을 현재 시장 분위기 및 뉴스 상황과 대조하여 합리적이었는지 분석해 주십시오.
- 특히 시장 국면(계절)과 부합하는 행동이었는지, 샹들리에 추적 손절(Chandelier Exit) 규칙을 기계적으로 잘 준수하고 있는지 냉정하게 평가해 주십시오.

## 4. 🛠️ 대응 시나리오 & 애널리스트 권고 사항 (Actionable Strategy)
- 다가오는 거래일 동안 사용자가 취해야 할 구체적인 포트폴리오 리밸런싱 전략, 리스크 헤징 방안(예: 현금 비중 조절, 손절가 상향 조정 등)을 3가지 내외로 구체적으로 제안해 주십시오.
"""

    # Gemini API 호출 (Requests 활용)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    try:
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        if res.status_code == 200:
            candidates = res.json().get("candidates", [])
            if candidates:
                text_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if text_content:
                    return text_content
            return "⚠️ 오류: Gemini API로부터 분석 결과를 생성할 수 없습니다. 응답 구조를 확인해 주세요."
        else:
            return f"⚠️ 오류: Gemini API 호출 실패 (상태코드: {res.status_code})\n상세 내용: {res.text}"
    except Exception as e:
        return f"⚠️ 오류: Gemini API 연동 중 오류 발생: {e}"
