import requests
import time
import uuid

class TossinvestClient:
    """
    토스증권 Open API 연동 클라이언트 클래스
    """
    def __init__(self, client_id, client_secret, base_url="https://openapi.tossinvest.com"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.access_token = None
        self.token_expiry = 0
        self.account_seq = None

    def _get_token(self):
        """
        OAuth 2.0 클라이언트 토큰을 발급/갱신합니다. (유효시간 만료 60초 전 자동 갱신)
        """
        if self.access_token and time.time() < self.token_expiry - 60:
            return self.access_token

        url = f"{self.base_url}/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        try:
            res = requests.post(url, headers=headers, data=data, timeout=10)
            res.raise_for_status()
            res_data = res.json()
            
            self.access_token = res_data.get("access_token")
            expires_in = int(res_data.get("expires_in", 3600))
            self.token_expiry = time.time() + expires_in
            return self.access_token
        except Exception as e:
            raise Exception(f"토스증권 API 토큰 발급 중 오류 발생: {e}")

    def fetch_account_seq(self):
        """
        사용자의 종합매매(BROKERAGE) 계좌 식별자(accountSeq)를 가져옵니다.
        """
        url = f"{self.base_url}/api/v1/accounts"
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json"
        }
        
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            res_json = res.json()
            
            # getAccounts_200_response의 스키마는 'result' 필드에 Account 리스트가 포함됩니다.
            accounts = res_json.get("result", [])
            
            # 종합매매(BROKERAGE) 계좌 우선 선택
            for acc in accounts:
                if acc.get("accountType") == "BROKERAGE":
                    self.account_seq = acc.get("accountSeq")
                    return self.account_seq
            
            # 없으면 첫 번째 계좌 선택
            if accounts:
                self.account_seq = accounts[0].get("accountSeq")
                return self.account_seq
                
            raise Exception("조회 가능한 토스증권 계좌가 없습니다.")
        except Exception as e:
            raise Exception(f"토스증권 계좌 조회 중 오류 발생: {e}")

    def get_headers(self, require_account=True):
        """
        API 요청에 필요한 헤더를 구성합니다.
        """
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json"
        }
        if require_account:
            if not self.account_seq:
                self.fetch_account_seq()
            headers["X-Tossinvest-Account"] = str(self.account_seq)
        return headers

    def get_holdings(self):
        """
        보유 주식 잔고 목록을 조회합니다.
        """
        url = f"{self.base_url}/api/v1/holdings"
        try:
            res = requests.get(url, headers=self.get_headers(require_account=True), timeout=10)
            res.raise_for_status()
            res_json = res.json()
            
            # getHoldings_200_response 스키마: result -> items -> HoldingsItem 리스트
            holdings_overview = res_json.get("result", {})
            return holdings_overview.get("items", [])
        except Exception as e:
            print(f"[TOSS API WARNING] 보유 주식 조회 실패: {e}")
            return []

    def get_buying_power(self, currency="KRW"):
        """
        현금 기반 매수 가능 금액(예수금)을 조회합니다.
        """
        url = f"{self.base_url}/api/v1/buying-power"
        params = {"currency": currency}
        try:
            res = requests.get(url, headers=self.get_headers(require_account=True), params=params, timeout=10)
            res.raise_for_status()
            res_json = res.json()
            
            # getBuyingPower_200_response 스키마: result -> cashBuyingPower
            buying_power_res = res_json.get("result", {})
            return float(buying_power_res.get("cashBuyingPower", 0.0))
        except Exception as e:
            print(f"[TOSS API WARNING] 매수 가능 금액 조회 실패: {e}")
            return 0.0

    def get_exchange_rate(self, base="USD", quote="KRW"):
        """
        실시간 환율을 조회합니다.
        """
        url = f"{self.base_url}/api/v1/exchange-rate"
        params = {"baseCurrency": base, "quoteCurrency": quote}
        try:
            res = requests.get(url, headers=self.get_headers(require_account=False), params=params, timeout=10)
            res.raise_for_status()
            res_json = res.json()
            
            # getExchangeRate_200_response 스키마: result -> rate
            rate_res = res_json.get("result", {})
            return float(rate_res.get("rate", 1300.0))
        except Exception as e:
            print(f"[TOSS API WARNING] 환율 조회 실패: {e}. 기본값 1,300원을 사용합니다.")
            return 1300.0

    def create_order(self, symbol, side, quantity=None, price=None, order_type="MARKET", order_amount=None):
        """
        매수/매도 주문을 접수합니다.
        - symbol: KR 종목코드 (예: '005930') 또는 US 티커 (예: 'AAPL')
        - side: 'BUY' (매수) 또는 'SELL' (매도)
        - quantity: 주문 수량 (정수 또는 소수점 문자열/float)
        - price: 지정가 주문 시 가격
        - order_type: 'MARKET' 또는 'LIMIT'
        - order_amount: 주문 금액 (달러 단위, US 시장가 매수 전용)
        """
        url = f"{self.base_url}/api/v1/orders"
        headers = self.get_headers(require_account=True)
        headers["Content-Type"] = "application/json"
        
        # 멱등성 보장 및 중복 주문 방지를 위한 clientOrderId 생성
        client_order_id = str(uuid.uuid4())
        
        body = {
            "clientOrderId": client_order_id,
            "symbol": symbol,
            "side": side,
            "orderType": order_type
        }
        
        if quantity is not None:
            body["quantity"] = quantity
        if order_amount is not None:
            body["orderAmount"] = order_amount
        if price is not None:
            body["price"] = price

        try:
            res = requests.post(url, headers=headers, json=body, timeout=15)
            res.raise_for_status()
            return res.json().get("result", {})
        except Exception as e:
            # 상세 오류 메시지 파싱 시도
            try:
                err_msg = res.json().get("message", str(e))
                raise Exception(f"{err_msg} (HTTP {res.status_code})")
            except Exception:
                raise Exception(str(e))

    def get_orders(self, status="OPEN"):
        """
        주문 목록을 조회합니다.
        - status: 'OPEN' (미체결/대기), 'CLOSED' (체결완료/취소) 등 (기본값: 'OPEN')
        """
        url = f"{self.base_url}/api/v1/orders"
        params = {}
        if status:
            params["status"] = status
        try:
            res = requests.get(url, headers=self.get_headers(require_account=True), params=params, timeout=10)
            res.raise_for_status()
            res_json = res.json()
            return res_json.get("result", {}).get("orders", [])
        except Exception as e:
            print(f"[TOSS API WARNING] 주문 목록 조회 실패: {e}")
            return []

    def cancel_order(self, order_id):
        """
        특정 대기 중인 주문을 취소합니다.
        """
        url = f"{self.base_url}/api/v1/orders/{order_id}/cancel"
        headers = self.get_headers(require_account=True)
        headers["Content-Type"] = "application/json"
        try:
            res = requests.post(url, headers=headers, json={}, timeout=10)
            res.raise_for_status()
            return res.json().get("result", {})
        except Exception as e:
            print(f"[TOSS API WARNING] 주문 취소 실패 (주문번호 {order_id}): {e}")
            return {}


