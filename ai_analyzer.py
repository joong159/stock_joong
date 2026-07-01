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

    # Gemini 프롬프트 구축
    prompt = f"""
당신은 행동재무학(Behavioral Finance) 전문가이자, 퀀트 트레이딩 심리 컨설턴트입니다. 
유튜버 '노말이'의 AI 주식 공부법에 따라, 사용자의 실제 주식 거래 이력과 각 매매 당시 기입한 '매매 사유'를 정밀하게 평가하여 행동 분석 리포트를 작성해 주십시오.

[사용자의 매매 일지 기록]
{trade_table_markdown}

위 매매 데이터를 바탕으로 다음 4가지 핵심 영역에 대해 깊이 있고 직관적인 분석 보고서를 작성해 주세요. 
사용자에게 친근하면서도 날카롭고 구체적인 피드백을 전달해야 합니다. 존댓말로 작성하되, 투자 원칙을 지키도록 따뜻하게 권고하십시오.

보고서 서식 양식 (Markdown 형식):
# 🤖 AI 투자 심리 및 행동 경제학 분석 리포트

## 1. 📊 나의 투자 성향 및 매매 패턴 진단
- 사용자의 거래 주기, 평균 보유 시간, 선호하는 종목 유형(국장/미장 분포), 매매 집중도 등을 분석해 주세요.

## 2. 🧠 행동 경제학적 심리 취약점 분석 (행동 편향 진단)
- **처분 효과(Disposition Effect)**: 수익 중인 주식은 너무 빨리 팔고(조급함), 손실 중인 주식은 지나치게 오래 쥐고 있는지(손실 회피 편향) 분석해 주세요.
- **뇌동 매매 및 감정적 거래**: 매매 사유를 분석하여 계획적인 매수였는지, 혹은 뉴스나 시장 상승 분위기에 휩쓸린 감정적 추격 매수/충동 매도였는지 평가해 주세요.

## 3. 🎯 Chandelier Exit(추적 손절) 원칙 준수 평가
- 샹들리에 출적 손절 라인이 제대로 지켜졌는지, 아니면 손절 원칙을 회피하거나 미루고 "강제 가치 투자" 모드로 전환했는지 매매 사유와 가격 추이를 근거로 평가해 주세요.

## 4. 🚀 나만의 매매 행동 가이드라인 & 액션 플랜
- 사용자의 취약점을 극복하기 위해 당장 실천해야 할 구체적인 투자 습관 개선안 3가지를 명확히 제시해 주세요.
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
