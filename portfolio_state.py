import os
import json
import time
import threading

STATE_FILE = '.portfolio_state.json'
state_lock = threading.Lock()

def load_portfolio_state():
    """
    로컬 포트폴리오 상태 파일(.portfolio_state.json)을 로드합니다.
    """
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
    포트폴리오 상태를 로컬 파일에 저장합니다.
    """
    with state_lock:
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[PORTFOLIO STATE WARNING] 상태 파일을 저장하는 중 오류 발생: {e}")

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
