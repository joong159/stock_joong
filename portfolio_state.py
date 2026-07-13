import os
import json
import time
import threading
import requests

STATE_FILE = '.portfolio_state.json'
REGIME_FILE = '.market_regime.txt'
state_lock = threading.Lock()

# Supabase 연동 변수 로드
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def get_supabase_headers():
    if not SUPABASE_KEY:
        return None
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

def load_portfolio_state():
    """
    로컬 포트폴리오 상태 파일(.portfolio_state.json)을 로드합니다.
    Supabase 연동 정보가 있고 조회가 성공하는 경우 Supabase 데이터를 가져와 동기화합니다.
    """
    headers = get_supabase_headers()
    if SUPABASE_URL and headers:
        try:
            url = f"{SUPABASE_URL}/rest/v1/portfolio_state"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                state = {}
                for item in data:
                    sym = item.get("symbol")
                    if sym:
                        state[sym] = {
                            "purchase_date": item.get("purchase_date"),
                            "purchase_price": float(item.get("purchase_price", 0.0)),
                            "highest_price": float(item.get("highest_price", 0.0)),
                            "purchase_qty": float(item.get("purchase_qty", 0.0))
                        }
                # 로컬 파일에 캐싱하여 일치시킴
                try:
                    with open(STATE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(state, f, ensure_ascii=False, indent=4)
                except Exception:
                    pass
                return state
        except Exception as e:
            print(f"[Supabase Portfolio Load Warning] {e}. Falling back to local file.")

    # 로컬 폴백
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[PORTFOLIO STATE WARNING] 상태 파일을 읽는 중 오류 발생: {e}")
        return {}

def save_portfolio_state(state):
    """
    포트폴리오 상태를 로컬 파일 및 Supabase에 저장합니다.
    """
    # 1. 로컬 저장
    with state_lock:
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[PORTFOLIO STATE WARNING] 상태 파일을 저장하는 중 오류 발생: {e}")

    # 2. Supabase 동기화
    headers = get_supabase_headers()
    if SUPABASE_URL and headers:
        try:
            url = f"{SUPABASE_URL}/rest/v1/portfolio_state"
            # DB의 전체 보유 종목과 로컬 목록을 동기화하기 위해, DB에만 존재하는 종목(매도됨) 삭제
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                db_symbols = [item.get("symbol") for item in res.json()]
                for sym in db_symbols:
                    if sym not in state:
                        requests.delete(f"{url}?symbol=eq.{sym}", headers=headers, timeout=5)

            # 현재 상태 전체를 Upsert
            if state:
                payload = [
                    {
                        "symbol": sym,
                        "purchase_date": info.get("purchase_date"),
                        "purchase_price": info.get("purchase_price"),
                        "highest_price": info.get("highest_price"),
                        "purchase_qty": info.get("purchase_qty")
                    }
                    for sym, info in state.items()
                ]
                headers_upsert = headers.copy()
                headers_upsert["Prefer"] = "resolution=merge-duplicates"
                requests.post(url, headers=headers_upsert, json=payload, timeout=5)
        except Exception as e:
            print(f"[Supabase Portfolio Save Warning] {e}")

def load_market_regime():
    """
    시장 국면 정보(.market_regime.txt)를 로드합니다.
    Supabase 연동이 활성화된 경우 Supabase 데이터를 가져옵니다.
    """
    headers = get_supabase_headers()
    if SUPABASE_URL and headers:
        try:
            url = f"{SUPABASE_URL}/rest/v1/market_regime"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                regimes = {item.get("market"): item.get("regime") for item in data}
                if regimes:
                    try:
                        with open(REGIME_FILE, 'w', encoding='utf-8') as f:
                            json.dump(regimes, f, ensure_ascii=False)
                    except Exception:
                        pass
                    return regimes
        except Exception as e:
            print(f"[Supabase Regime Load Warning] {e}. Falling back to local file.")

    if not os.path.exists(REGIME_FILE):
        return {"US": "SPRING", "KR": "SPRING"}
    try:
        with open(REGIME_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"US": "SPRING", "KR": "SPRING"}

def save_market_regime(regime_dict):
    """
    시장 국면 정보를 로컬 파일 및 Supabase에 저장합니다.
    """
    # 1. 로컬 저장
    try:
        with open(REGIME_FILE, 'w', encoding='utf-8') as f:
            json.dump(regime_dict, f, ensure_ascii=False)
    except Exception as e:
        print(f"[REGIME SAVE WARNING] {e}")

    # 2. Supabase 동기화
    headers = get_supabase_headers()
    if SUPABASE_URL and headers:
        try:
            url = f"{SUPABASE_URL}/rest/v1/market_regime"
            payload = [
                {"market": "US", "regime": regime_dict.get("US", "SPRING")},
                {"market": "KR", "regime": regime_dict.get("KR", "SPRING")}
            ]
            headers_upsert = headers.copy()
            headers_upsert["Prefer"] = "resolution=merge-duplicates"
            requests.post(url, headers=headers_upsert, json=payload, timeout=5)
        except Exception as e:
            print(f"[Supabase Regime Save Warning] {e}")

def sync_portfolio_state(current_holdings_dict):
    """
    보유 주식 정보와 로컬 상태를 동기화하고 최고가 및 보유 수량을 업데이트합니다.
    - current_holdings_dict: { 'Toss_Symbol': { 'qty': 수량, 'price_original': 원래화폐현재가, ... } }
    """
    state = load_portfolio_state()
    updated = False
    
    # 1. 실제 보유하지 않은 종목은 상태에서 삭제 (매도 처리 완료)
    for sym in list(state.keys()):
        if sym not in current_holdings_dict:
            state.pop(sym)
            updated = True
            print(f"[PORTFOLIO STATE] 종목 매도 완료 감지: {sym}")
            
    # 2. 새로 매수한 종목 추가 및 기존 보유 종목 최고가/수량 갱신
    for sym, info in current_holdings_dict.items():
        qty = info.get("qty", 0.0)
        if qty <= 0:
            continue
            
        curr_price = info.get("price_original", 0.0)
        
        if sym not in state:
            # 신규 종목 추가 (최고가를 현재가로 최초 설정)
            state[sym] = {
                "purchase_date": time.strftime('%Y-%m-%d %H:%M:%S'),
                "purchase_price": curr_price,
                "highest_price": curr_price,
                "purchase_qty": qty
            }
            updated = True
            print(f"[PORTFOLIO STATE] 신규 보유 주식 추가: {sym} (진입가: {curr_price}, 수량: {qty})")
        else:
            old_high = state[sym].get("highest_price", 0.0)
            old_qty = state[sym].get("purchase_qty", 0.0)
            
            # 최고가 갱신 검증
            if curr_price > old_high:
                state[sym]["highest_price"] = curr_price
                updated = True
                print(f"[PORTFOLIO STATE] 종목 최고가 갱신: {sym} ({old_high} -> {curr_price})")
            
            # 보유 수량 갱신 검증
            if qty != old_qty:
                state[sym]["purchase_qty"] = qty
                updated = True
                print(f"[PORTFOLIO STATE] 종목 수량 변경 감지: {sym} ({old_qty} -> {qty})")
                
    if updated:
        save_portfolio_state(state)
        
    return state
