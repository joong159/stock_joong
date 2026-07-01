import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import os
import yfinance as yf
from toss_api import TossinvestClient
from portfolio_state import load_portfolio_state, sync_portfolio_state

# 의존성 없이 로컬 .env 파일을 파싱하는 헬퍼 함수
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

class LiveDashboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("토스증권 실시간 포트폴리오 대시보드")
        self.root.geometry("820x620")
        self.root.configure(bg="#0F172A") # Slate 900 (Dark theme background)
        
        # API 클라이언트 초기화
        load_dotenv()
        self.client_id = os.environ.get("TOSS_CLIENT_ID")
        self.client_secret = os.environ.get("TOSS_CLIENT_SECRET")
        self.base_url = os.environ.get("TOSS_BASE_URL", "https://openapi.tossinvest.com")
        
        self.toss_client = None
        self.is_offline = True
        
        if self.client_id and self.client_secret and self.client_id != "your_client_id_here":
            try:
                self.toss_client = TossinvestClient(self.client_id, self.client_secret, self.base_url)
                self.is_offline = False
            except Exception:
                self.toss_client = None
                
        # 대시보드 데이터 바인딩 변수
        self.var_total_assets = tk.StringVar(value="로딩 중...")
        self.var_cash = tk.StringVar(value="로딩 중...")
        self.var_stock_val = tk.StringVar(value="로딩 중...")
        self.var_exchange_rate = tk.StringVar(value="로딩 중...")
        self.var_market_regime = tk.StringVar(value="분석 대기 중")
        self.var_status = tk.StringVar(value="연결 상태 확인 중...")
        self.var_countdown = tk.StringVar(value="갱신 대기 중")
        
        self.is_running = True
        
        # 스타일링 초기화
        self.setup_styles()
        self.create_widgets()
        
        # 실시간 데이터 자동 갱신 스레드 가동
        self.refresh_thread = threading.Thread(target=self.auto_refresh_loop, daemon=True)
        self.refresh_thread.start()
        
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        
        # Treeview 스타일링 (홀딩스 목록)
        style.configure("Treeview",
                        background="#1E293B",
                        foreground="#F8FAFC",
                        rowheight=28,
                        fieldbackground="#1E293B",
                        borderwidth=0,
                        font=("Malgun Gothic", 10))
        style.map("Treeview", background=[("selected", "#3B82F6")])
        style.configure("Treeview.Heading",
                        background="#1B365D",
                        foreground="#FFFFFF",
                        font=("Malgun Gothic", 10, "bold"))
        
    def create_widgets(self):
        # --- Top Header ---
        header_frame = tk.Frame(self.root, bg="#1E293B", height=60)
        header_frame.pack(fill="x", side="top")
        
        header_label = tk.Label(header_frame, text="Toss Live Portfolio Dashboard",
                                font=("Malgun Gothic", 16, "bold"), fg="#3B82F6", bg="#1E293B")
        header_label.pack(side="left", padx=20, pady=10)
        
        # 연결 상태 배지
        status_color = "#10B981" if not self.is_offline else "#F59E0B"
        status_text = "● 실시간 API 연동 중" if not self.is_offline else "● 오프라인 모의 시뮬레이터"
        self.var_status.set(status_text)
        
        status_label = tk.Label(header_frame, textvariable=self.var_status,
                                font=("Malgun Gothic", 10, "bold"), fg=status_color, bg="#1E293B")
        status_label.pack(side="right", padx=20, pady=15)
        
        # --- Summary Grid Frame ---
        grid_frame = tk.Frame(self.root, bg="#0F172A", pady=15)
        grid_frame.pack(fill="x", padx=20)
        
        # Card 1. 총 자산
        c1 = tk.Frame(grid_frame, bg="#1E293B", bd=1, relief="flat", highlightbackground="#334155", highlightthickness=1)
        c1.grid(row=0, column=0, padx=10, sticky="nsew")
        tk.Label(c1, text="총 자산 (자산 평가금)", font=("Malgun Gothic", 10), fg="#94A3B8", bg="#1E293B").pack(pady=(10, 2))
        tk.Label(c1, textvariable=self.var_total_assets, font=("Malgun Gothic", 16, "bold"), fg="#F8FAFC", bg="#1E293B").pack(pady=(0, 10))
        
        # Card 2. 보유 현금
        c2 = tk.Frame(grid_frame, bg="#1E293B", bd=1, relief="flat", highlightbackground="#334155", highlightthickness=1)
        c2.grid(row=0, column=1, padx=10, sticky="nsew")
        tk.Label(c2, text="보유 현금 (예수금)", font=("Malgun Gothic", 10), fg="#94A3B8", bg="#1E293B").pack(pady=(10, 2))
        tk.Label(c2, textvariable=self.var_cash, font=("Malgun Gothic", 16, "bold"), fg="#10B981", bg="#1E293B").pack(pady=(0, 10))
        
        # Card 3. 주식 평가금
        c3 = tk.Frame(grid_frame, bg="#1E293B", bd=1, relief="flat", highlightbackground="#334155", highlightthickness=1)
        c3.grid(row=0, column=2, padx=10, sticky="nsew")
        tk.Label(c3, text="주식 평가액", font=("Malgun Gothic", 10), fg="#94A3B8", bg="#1E293B").pack(pady=(10, 2))
        tk.Label(c3, textvariable=self.var_stock_val, font=("Malgun Gothic", 16, "bold"), fg="#3B82F6", bg="#1E293B").pack(pady=(0, 10))
        
        # Card 4. 적용 환율
        c4 = tk.Frame(grid_frame, bg="#1E293B", bd=1, relief="flat", highlightbackground="#334155", highlightthickness=1)
        c4.grid(row=0, column=3, padx=10, sticky="nsew")
        tk.Label(c4, text="실시간 달러 환율", font=("Malgun Gothic", 10), fg="#94A3B8", bg="#1E293B").pack(pady=(10, 2))
        tk.Label(c4, textvariable=self.var_exchange_rate, font=("Malgun Gothic", 14, "bold"), fg="#F59E0B", bg="#1E293B").pack(pady=(3, 10))
        
        # Card 5. 시장 계절
        c5 = tk.Frame(grid_frame, bg="#1E293B", bd=1, relief="flat", highlightbackground="#334155", highlightthickness=1)
        c5.grid(row=0, column=4, padx=10, sticky="nsew")
        tk.Label(c5, text="현재 시장 계절", font=("Malgun Gothic", 10), fg="#94A3B8", bg="#1E293B").pack(pady=(10, 2))
        tk.Label(c5, textvariable=self.var_market_regime, font=("Malgun Gothic", 14, "bold"), fg="#EC4899", bg="#1E293B").pack(pady=(3, 10))
        
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)
        grid_frame.columnconfigure(2, weight=1)
        grid_frame.columnconfigure(3, weight=1)
        grid_frame.columnconfigure(4, weight=1)
        
        # --- Holdings Table Header ---
        lbl_holdings = tk.Label(self.root, text="📂 실시간 보유 주식 잔고 현황", font=("Malgun Gothic", 12, "bold"), fg="#F8FAFC", bg="#0F172A")
        lbl_holdings.pack(anchor="w", padx=30, pady=(10, 5))
        
        # --- Holdings Treeview ---
        table_frame = tk.Frame(self.root, bg="#0F172A")
        table_frame.pack(fill="both", expand=True, padx=30, pady=5)
        
        # 좌우 분할 프레임
        table_left_frame = tk.Frame(table_frame, bg="#0F172A")
        table_left_frame.pack(side="left", fill="both", expand=True)
        
        table_right_frame = tk.Frame(table_frame, bg="#0F172A")
        table_right_frame.pack(side="right", fill="both", expand=True, padx=(15, 0))
        self.current_pie_frame = table_right_frame
        
        self.tree = ttk.Treeview(table_left_frame, columns=("Symbol", "Name", "Qty", "Price", "PurchaseVal", "CurrentVal", "ProfitLoss", "Currency"), show="headings")
        self.tree.heading("Symbol", text="종목 코드")
        self.tree.heading("Name", text="회사명")
        self.tree.heading("Qty", text="보유 수량")
        self.tree.heading("Price", text="현재가")
        self.tree.heading("PurchaseVal", text="매수 금액")
        self.tree.heading("CurrentVal", text="평가 금액")
        self.tree.heading("ProfitLoss", text="수익률")
        self.tree.heading("Currency", text="통화")
        
        self.tree.column("Symbol", width=75, anchor="center")
        self.tree.column("Name", width=120, anchor="w")
        self.tree.column("Qty", width=80, anchor="e")
        self.tree.column("Price", width=90, anchor="e")
        self.tree.column("PurchaseVal", width=110, anchor="e")
        self.tree.column("CurrentVal", width=110, anchor="e")
        self.tree.column("ProfitLoss", width=80, anchor="center")
        self.tree.column("Currency", width=55, anchor="center")
        
        self.tree.tag_configure("plus", foreground="#F87171")  # Light red for profit
        self.tree.tag_configure("minus", foreground="#60A5FA") # Light blue for loss
        self.tree.tag_configure("neutral", foreground="#F8FAFC")
        self.tree.pack(fill="both", expand=True, side="left")
        
        scrollbar = ttk.Scrollbar(table_left_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(fill="y", side="right")
        
        # --- Bottom Control Panel ---
        ctrl_frame = tk.Frame(self.root, bg="#1E293B", pady=10)
        ctrl_frame.pack(fill="x", side="bottom")
        
        lbl_countdown = tk.Label(ctrl_frame, textvariable=self.var_countdown, font=("Malgun Gothic", 10), fg="#94A3B8", bg="#1E293B")
        lbl_countdown.pack(side="left", padx=30)
        
        btn_refresh = tk.Button(ctrl_frame, text="즉시 갱신", font=("Malgun Gothic", 10, "bold"),
                                bg="#3B82F6", fg="#FFFFFF", activebackground="#2563EB", activeforeground="#FFFFFF",
                                relief="flat", padx=15, command=self.manual_refresh)
        btn_refresh.pack(side="right", padx=10)
        
        btn_rebalance = tk.Button(ctrl_frame, text="포트폴리오 분석 및 리밸런싱 주문", font=("Malgun Gothic", 10, "bold"),
                                  bg="#10B981", fg="#FFFFFF", activebackground="#059669", activeforeground="#FFFFFF",
                                  relief="flat", padx=15, command=self.run_rebalance_engine)
        btn_rebalance.pack(side="right", padx=15)
        
        btn_notion_setup = tk.Button(ctrl_frame, text="🔗 노션 자동 설정", font=("Malgun Gothic", 10, "bold"),
                                     bg="#475569", fg="#FFFFFF", activebackground="#334155", activeforeground="#FFFFFF",
                                     relief="flat", padx=15, command=self.run_notion_setup)
        btn_notion_setup.pack(side="right", padx=10)
        
        btn_ai_analysis = tk.Button(ctrl_frame, text="🤖 AI 투자 행동 분석", font=("Malgun Gothic", 10, "bold"),
                                    bg="#8B5CF6", fg="#FFFFFF", activebackground="#7C3AED", activeforeground="#FFFFFF",
                                    relief="flat", padx=15, command=self.run_ai_analysis)
        btn_ai_analysis.pack(side="right", padx=10)
        
    def run_notion_setup(self):
        confirm = messagebox.askyesno("노션 자동 연동 설정", 
            "노션 워크스페이스에 '주식 자동 리밸런싱 대시보드'라는 이름의 빈 페이지를 만드셨나요?\n"
            "그리고 생성하신 노션 API 통합 권한을 해당 페이지에 연결하셨나요?\n\n"
            "확인을 누르시면 페이지를 자동으로 탐색하고 2개의 테이블 데이터베이스를 생성합니다.")
        if not confirm:
            return
            
        self.var_countdown.set("🔗 노션 자동 셋업 중...")
        
        def setup_bg():
            try:
                from notion_sync import setup_notion_workspace, decorate_notion_workspace
                msg = setup_notion_workspace()
                dec_msg = decorate_notion_workspace()
                self.root.after(0, lambda: messagebox.showinfo("노션 설정 결과", f"{msg}\n\n{dec_msg}"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("노션 설정 오류", f"작업 중 오류 발생: {e}"))
            finally:
                self.root.after(0, self.manual_refresh)
                
        threading.Thread(target=setup_bg, daemon=True).start()

    def run_ai_analysis(self):
        # 로딩 팝업 표시
        loading_popup = tk.Toplevel(self.root)
        loading_popup.title("🤖 AI 투자 행동 분석 중...")
        loading_popup.geometry("400x150")
        loading_popup.configure(bg="#0F172A")
        loading_popup.transient(self.root)
        loading_popup.grab_set()
        
        lbl_msg = tk.Label(loading_popup, text="🔄 노션 거래 일지를 수집하고\nGemini AI 분석 보고서를 생성하는 중입니다...\n(약 10~25초 소요)", 
                           font=("Malgun Gothic", 10, "bold"), fg="#F8FAFC", bg="#0F172A", pady=25)
        lbl_msg.pack()
        
        def analysis_bg():
            try:
                from ai_analyzer import generate_trading_analysis_report
                report_text = generate_trading_analysis_report()
                
                # 로딩 창 닫기
                self.root.after(0, loading_popup.destroy)
                
                # 결과 창 팝업
                self.root.after(0, lambda: self.show_ai_report_popup(report_text))
            except Exception as e:
                self.root.after(0, loading_popup.destroy)
                self.root.after(0, lambda: messagebox.showerror("AI 분석 오류", f"분석 연동 중 오류 발생: {e}"))
                
        threading.Thread(target=analysis_bg, daemon=True).start()

    def show_ai_report_popup(self, report_text):
        report_popup = tk.Toplevel(self.root)
        report_popup.title("🤖 AI 투자 행동 및 심리 분석 리포트")
        report_popup.geometry("800x600")
        report_popup.configure(bg="#0F172A")
        report_popup.transient(self.root)
        report_popup.grab_set()
        
        lbl_title = tk.Label(report_popup, text="📋 AI 투자 심리 & 매매 일지 분석 결과 보고서", font=("Malgun Gothic", 14, "bold"), fg="#8B5CF6", bg="#0F172A")
        lbl_title.pack(pady=15)
        
        txt_frame = tk.Frame(report_popup, bg="#0F172A")
        txt_frame.pack(fill="both", expand=True, padx=25, pady=5)
        
        txt_report = tk.Text(txt_frame, bg="#1E293B", fg="#F8FAFC", insertbackground="white", font=("Malgun Gothic", 10), wrap="word", relief="flat")
        txt_report.pack(side="left", fill="both", expand=True)
        
        scroll = ttk.Scrollbar(txt_frame, orient="vertical", command=txt_report.yview)
        txt_report.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        
        txt_report.insert("1.0", report_text)
        txt_report.config(state="disabled")
        
        btn_close = tk.Button(report_popup, text="확인 후 닫기", font=("Malgun Gothic", 10, "bold"),
                              bg="#64748B", fg="#FFFFFF", activebackground="#475569", activeforeground="#FFFFFF",
                              relief="flat", padx=20, pady=5, command=report_popup.destroy)
        btn_close.pack(pady=15)
        
    def fetch_live_data(self):
        """
        토스 API 혹은 로컬 시뮬레이터에서 실시간 계좌/주식 데이터를 조회합니다.
        """
        usd_krw = 1350.0
        toss_holdings = []
        cash_balance = 0.0
        
        try:
            if not self.is_offline and self.toss_client:
                # 1. 실시간 환율 조회
                usd_krw = self.toss_client.get_exchange_rate(base="USD", quote="KRW")
                # 2. 예수금 조회
                cash_balance = self.toss_client.get_buying_power(currency="KRW")
                # 3. 실시간 보유 잔고 조회
                toss_holdings = self.toss_client.get_holdings()
            else:
                # 시뮬레이터 모드: 로컬 포트폴리오 상태에서 보유 종목 불러오기
                state = load_portfolio_state()
                usd_krw = 1350.0
                cash_balance = 50.0 # 기본 예수금
                toss_holdings = []
                for sym, info in state.items():
                    # 원래 화폐 현재가는 yfinance에서 실시간 로드
                    ticker_name = sym
                    price_original = 0.0
                    try:
                        ticker_df = yf.download(ticker_name, period='1d', progress=False)
                        if not ticker_df.empty:
                            price_original = float(ticker_df['Close'].iloc[-1])
                    except Exception:
                        pass
                    
                    is_us = not (ticker_name.endswith('.KS') or ticker_name.endswith('.KQ'))
                    toss_holdings.append({
                        "symbol": sym,
                        "quantity": info.get("purchase_qty", 0.0),
                        "lastPrice": price_original,
                        "currency": "USD" if is_us else "KRW",
                        "averagePurchasePrice": info.get("purchase_price", 0.0)
                    })
                    
            # 4. 실시간 보유 종목 원화 평가가액 계산
            holdings_list = []
            stock_valuation = 0.0
            
            # 한글/영어 매핑 사전
            name_mapping = {
                'NVDA': '엔비디아', 'AAPL': '애플', 'MSFT': '마이크로소프트', 'AMD': 'AMD',
                'JPM': 'JP모건 체이스', 'GS': '골드만삭스', 'BAC': '뱅크오브아메리카', 'WFC': '웰스파고',
                'XOM': '엑슨모빌', 'CVX': '쉐브론', 'COP': '코노코필립스', 'BBY': '베스트바이',
                'SNDK': '샌디스크', 'F': '포드', '005930': '삼성전자', '000660': 'SK하이닉스',
                '373220': 'LG에너지솔루션', '207940': '삼성바이오로직스', '005380': '현대차',
                '000270': '기아', '068270': '셀트리온', '051910': 'LG화학', '035420': 'NAVER',
                '006400': '삼성SDI', '105560': 'KB금융', '055550': '신한지주', '028260': '삼성물산',
                '012330': '현대모비스', '066570': 'LG전자', '032830': '삼성생명', '003670': '포스코퓨처엠',
                '033780': 'KT&G', '011200': 'HMM', '035720': '카카오'
            }
            
            for item in toss_holdings:
                sym = item.get("symbol")
                qty = float(item.get("quantity", 0.0))
                price = float(item.get("lastPrice", 0.0))
                currency = item.get("currency", "KRW")
                
                # 매핑된 이름 찾기 (없으면 티커 그대로 또는 야후 검색 API로 자동 로드 시도)
                name = name_mapping.get(sym)
                if not name:
                    # 야후 파이낸스 검색 API로 회사명 가져오기 시도
                    try:
                        import urllib.request
                        import json
                        req = urllib.request.Request(
                            f"https://query2.finance.yahoo.com/v1/finance/search?q={sym}",
                            headers={'User-Agent': 'Mozilla/5.0'}
                        )
                        with urllib.request.urlopen(req, timeout=3) as res:
                            search_data = json.loads(res.read())
                            quotes = search_data.get('quotes', [])
                            if quotes:
                                name = quotes[0].get('longname') or quotes[0].get('shortname') or sym
                            else:
                                name = sym
                    except Exception:
                        name = sym
                        
                # 평단가 및 수익률 정보 조회
                avg_buy_price = float(item.get("averagePurchasePrice", 0.0))
                
                # 만약 Toss API의 profitLoss 딕셔너리가 직접 있다면 활용
                pl_dict = item.get("profitLoss", {})
                if pl_dict:
                    pl_rate = float(pl_dict.get("rate", 0.0)) * 100.0 # 백분율 (%)
                else:
                    if avg_buy_price > 0.0:
                        pl_rate = ((price - avg_buy_price) / avg_buy_price) * 100.0
                    else:
                        pl_rate = 0.0
                
                # 매수금액 / 평가금액 계산 (원화 환산 기준)
                avg_buy_price_krw = avg_buy_price * usd_krw if currency == "USD" else avg_buy_price
                purchase_val_krw = qty * avg_buy_price_krw
                
                price_krw = price * usd_krw if currency == "USD" else price
                val_krw = qty * price_krw
                stock_valuation += val_krw
                
                # 매수금액 안전장치 (매수 정보가 누락되어 0일 때 평가액 기준으로 동기화)
                if purchase_val_krw <= 0.0:
                    purchase_val_krw = val_krw
                
                holdings_list.append((sym, name, qty, price, purchase_val_krw, val_krw, pl_rate, currency))
                
            # 5. 주요 보유 종목 뉴스 수집
            news_list = []
            for h in holdings_list:
                sym = h[0]
                try:
                    ticker_news = yf.Ticker(sym).news
                    if ticker_news:
                        for art in ticker_news[:2]:  # 최대 2개 뉴스 수집
                            news_list.append({
                                "symbol": sym,
                                "title": art.get("title", ""),
                                "publisher": art.get("publisher", ""),
                                "link": art.get("link", ""),
                                "time": art.get("providerPublishTime", 0)
                            })
                except Exception as ex:
                    print(f"[News Fetch Warning] Failed for {sym}: {ex}")
            
            total_assets = cash_balance + stock_valuation
            
            # 메인 스레드 안전 업데이트
            self.root.after(0, self.update_gui_values, total_assets, cash_balance, stock_valuation, usd_krw, holdings_list, news_list)
        except Exception as e:
            self.root.after(0, self.show_error_message, str(e))
            
    def update_gui_values(self, total, cash, stock_val, rate, holdings_list, news_list=[]):
        self.var_total_assets.set(f"₩ {total:,.0f}")
        self.var_cash.set(f"₩ {cash:,.0f}")
        self.var_stock_val.set(f"₩ {stock_val:,.0f}")
        self.var_exchange_rate.set(f"₩ {rate:,.2f}")
        
        # 시장 국면(계절) 로드 및 표시
        regime = "분석 대기 중"
        if os.path.exists(".market_regime.txt"):
            try:
                with open(".market_regime.txt", "r", encoding="utf-8") as f:
                    regime_val = f.read().strip()
                    if regime_val == "SPRING":
                        regime = "🌸 봄 (SPRING)"
                    elif regime_val == "SUMMER":
                        regime = "☀️ 여름 (SUMMER)"
                    elif regime_val == "FALL":
                        regime = "🍁 가을 (FALL)"
                    elif regime_val == "WINTER":
                        regime = "❄️ 겨울 (WINTER)"
                    else:
                        regime = regime_val
            except Exception:
                pass
        self.var_market_regime.set(regime)
        
        # 목록 지우고 재작성
        for row in self.tree.get_children():
            self.tree.delete(row)
            
        for h in holdings_list:
            sym, name, qty, price, purchase_val_krw, val_krw, pl_rate, curr = h
            
            # 수량과 금액 예쁘게 포맷
            qty_str = f"{qty:.6f}" if curr == "USD" else f"{qty:,.0f}"
            price_str = f"$ {price:,.2f}" if curr == "USD" else f"₩ {price:,.0f}"
            purchase_val_str = f"₩ {purchase_val_krw:,.0f}"
            val_str = f"₩ {val_krw:,.0f}"
            pl_str = f"{pl_rate:+.2f}%"
            
            # 수익률에 따른 색상 태그 설정 (0.05% 기준 완화)
            if pl_rate > 0.05:
                tag = "plus"
            elif pl_rate < -0.05:
                tag = "minus"
            else:
                tag = "neutral"
                
            self.tree.insert("", "end", values=(sym, name, qty_str, price_str, purchase_val_str, val_str, pl_str, curr), tags=(tag,))
            
        self.draw_current_holdings_pie(holdings_list)
        
        # 노션 잔고 및 주요 뉴스 동기화 (UI 프리징 방지를 위해 백그라운드 스레드로 구동)
        try:
            from notion_sync import sync_holdings_to_notion, sync_market_news_to_notion
            threading.Thread(target=sync_holdings_to_notion, args=(holdings_list,), daemon=True).start()
            if news_list:
                threading.Thread(target=sync_market_news_to_notion, args=(news_list,), daemon=True).start()
        except Exception as e:
            print(f"[Notion sync trigger error] {e}")
        
    def draw_current_holdings_pie(self, holdings_list):
        # 기존 차트 위젯들 제거
        for widget in self.current_pie_frame.winfo_children():
            widget.destroy()
            
        if not holdings_list:
            lbl_no_data = tk.Label(self.current_pie_frame, text="보유 주식이 없습니다.", font=("Malgun Gothic", 10), fg="#94A3B8", bg="#0F172A")
            lbl_no_data.pack(expand=True)
            return
            
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import matplotlib.pyplot as plt
            import matplotlib.font_manager as fm
            
            # 한글 깨짐 방지 폰트 설정
            font_path = "C:/Windows/Fonts/malgun.ttf"
            if os.path.exists(font_path):
                font_name = fm.FontProperties(fname=font_path).get_name()
                matplotlib.rc('font', family=font_name)
            else:
                matplotlib.rc('font', family='Malgun Gothic')
                
            fig, ax = plt.subplots(figsize=(3.5, 3.5), dpi=100)
            fig.patch.set_facecolor('#0F172A') # Slate 900 매칭
            ax.set_facecolor('#0F172A')
            
            labels = []
            sizes = []
            colors = []
            
            for h in holdings_list:
                sym, name, qty, price, purchase_val_krw, val_krw, pl_rate, curr = h
                labels.append(name)
                sizes.append(val_krw)
                if curr == "USD":
                    colors.append('#2563EB') # Blue for US
                else:
                    colors.append('#059669') # Emerald for KR
                    
            if sum(sizes) == 0:
                plt.close(fig)
                lbl_no_val = tk.Label(self.current_pie_frame, text="평가 금액이 0원입니다.", font=("Malgun Gothic", 10), fg="#94A3B8", bg="#0F172A")
                lbl_no_val.pack(expand=True)
                return
                
            wedges, texts, autotexts = ax.pie(
                sizes,
                labels=labels,
                autopct='%1.1f%%',
                startangle=140,
                colors=colors,
                textprops=dict(color="white", fontsize=8),
                pctdistance=0.7
            )
            
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontsize(8)
                autotext.set_weight('bold')
            for text in texts:
                text.set_color('#E2E8F0')
                text.set_fontsize(8)
                
            ax.axis('equal')
            
            canvas = FigureCanvasTkAgg(fig, master=self.current_pie_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)
            plt.close(fig)
        except Exception as e:
            print(f"[CURRENT PIE ERROR] {e}")
            
    def show_error_message(self, err_msg):
        self.var_countdown.set("⚠️ 통신 에러 발생")
        print(f"[DASHBOARD ERROR] {err_msg}")
        
    def auto_refresh_loop(self):
        """
        60초 주기 자동 갱신 루프 스레드 (TOSS API 429 에러 방지)
        """
        while self.is_running:
            self.fetch_live_data()
            
            # 60초 카운트다운 매초 갱신
            for sec in range(60, 0, -1):
                if not self.is_running:
                    return
                self.var_countdown.set(f"⏱️ 자동 갱신: {sec}초 전")
                time.sleep(1)
                
    def manual_refresh(self):
        self.var_countdown.set("🔄 새로고침 중...")
        threading.Thread(target=self.fetch_live_data, daemon=True).start()
        
    def run_rebalance_engine(self):
        """
        quant_analyzer.py 퀀트 엔진을 백그라운드로 구동하여 추천 포트폴리오를 작성합니다.
        """
        self.var_countdown.set("🚀 포트폴리오 퀀트 연산 중...")
        btn_confirm = messagebox.askyesno("자동 리밸런싱 실행", "현재 시장 국면을 평가하고 리밸런싱 분석을 실행하시겠습니까?\n(약 10~30초 소요됩니다)")
        if not btn_confirm:
            self.manual_refresh()
            return
            
        def execute_backend():
            temp_output = "temp_output.xlsx"
            success = False
            try:
                import subprocess
                # S&P500, KRX 분석 및 엑셀 출력을 포함한 파이썬 스크립트 백그라운드 호출
                cmd = ["python", "quant_analyzer.py", "--output", temp_output]
                if self.is_offline:
                    cmd.append("--test") # 오프라인 모드일 땐 가볍게 11개 대형주 테스트 유니버스로 실행
                    
                res = subprocess.run(cmd, capture_output=True)
                
                def decode_bytes(b):
                    for enc in ['utf-8', 'cp949', 'euc-kr']:
                        try:
                            return b.decode(enc)
                        except UnicodeDecodeError:
                            continue
                    return b.decode('utf-8', errors='replace')
                    
                stdout_text = decode_bytes(res.stdout)
                stderr_text = decode_bytes(res.stderr)
                
                # 결과 출력 확인
                if res.returncode == 0:
                    success = True
                    self.root.after(0, lambda: self.show_analysis_results(temp_output))
                else:
                    self.root.after(0, lambda: messagebox.showerror("오류 발생", f"퀀트 분석기 실행 실패:\n{stderr_text}"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("오류 발생", f"오류 메시지: {e}"))
            finally:
                # 성공 시에는 show_analysis_results에서 파일을 다 읽고 삭제하므로,
                # 실패했을 때만 여기서 임시 파일을 청소합니다.
                if not success and os.path.exists(temp_output):
                    try:
                        os.remove(temp_output)
                    except Exception:
                        pass
                self.root.after(0, self.manual_refresh)
                
        threading.Thread(target=execute_backend, daemon=True).start()

    def show_analysis_results(self, temp_output):
        """
        분석이 성공한 후, 추천 포트폴리오와 리밸런싱 매매 계획을 화면에 표로 보여줍니다.
        """
        import pandas as pd
        import shutil
        
        df_port = None
        df_rebal = None
        
        try:
            # 엑셀 시트에서 데이터 로드 (첫 2행은 제목이므로 skiprows=2)
            df_port = pd.read_excel(temp_output, sheet_name="Final Portfolio", skiprows=2)
            df_port = df_port.dropna(subset=['Ticker'])
            
            try:
                df_rebal = pd.read_excel(temp_output, sheet_name="Rebalancing Plan", skiprows=2)
                df_rebal = df_rebal.dropna(subset=['Ticker'])
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("데이터 읽기 실패", f"결과 엑셀 파일을 읽는 중 오류가 발생했습니다: {e}")
            return
        finally:
            # 메모리에 데이터를 모두 로드했으므로 임시 파일은 즉시 안전하게 삭제합니다.
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception:
                    pass

        # 결과팝업 창 생성
        popup = tk.Toplevel(self.root)
        popup.title("📊 퀀트 분석 및 리밸런싱 주문 결과")
        popup.geometry("950x650")
        popup.configure(bg="#0F172A")  # Slate 900
        popup.transient(self.root)
        popup.grab_set()

        # 제목
        lbl_title = tk.Label(popup, text="🚀 퀀트 분석 및 포트폴리오 리밸런싱 결과", font=("Malgun Gothic", 16, "bold"), fg="#3B82F6", bg="#0F172A")
        lbl_title.pack(pady=(15, 5))

        # 시장 영업 시간 및 주문 방식 요약 프레임
        def is_us_market_open():
            import datetime
            now = datetime.datetime.now() # KST
            weekday = now.weekday()
            if weekday == 5 and now.hour >= 6:
                return False
            if weekday == 6:
                return False
            if weekday == 0 and now.hour < 9:
                return False
            hour = now.hour
            minute = now.minute
            if hour == 22 and minute >= 30:
                return True
            if hour >= 23:
                return True
            if hour < 6:
                return True
            return False

        def is_kr_market_open():
            import datetime
            now = datetime.datetime.now()
            weekday = now.weekday()
            if weekday >= 5:
                return False
            hour = now.hour
            minute = now.minute
            if 9 <= hour < 15:
                return True
            if hour == 15 and minute <= 30:
                return True
            return False

        kr_open = is_kr_market_open()
        us_open = is_us_market_open()
        kr_status_text = "🟢 한국시장 영업중 (실시간 체결 가능)" if kr_open else "🔴 한국시장 휴장중 (주문 전송 시 건너뜀)"
        us_status_text = "🟢 미국시장 영업중 (실시간 체결 가능)" if us_open else "🔴 미국시장 휴장중 (주문 전송 시 건너뜀)"

        summary_frame = tk.Frame(popup, bg="#1E293B", bd=1, relief="solid", highlightthickness=0)
        summary_frame.pack(fill="x", padx=20, pady=5)

        lbl_summary_title = tk.Label(summary_frame, text="💡 시장 개장 및 자금 분배 안내", font=("Malgun Gothic", 10, "bold"), fg="#94A3B8", bg="#1E293B")
        lbl_summary_title.pack(anchor="w", padx=15, pady=(8, 2))

        status_text = f"국내 주식: {kr_status_text}  |  미국 주식: {us_status_text}\n" \
                      f"각 주식에 들어갈 개별 투자 금액은 하단 표의 'Invest_Amount(KRW)'(포트폴리오) 및 'Diff_Value(KRW)'(주문서)에서 직접 확인 가능합니다.\n" \
                      f"※ 시장이 휴장 상태인 종목 주문은 실제 토스 전송 시 안전하게 건너뜁니다. (개장 시간에 맞추어 주문 전송을 실행해 주세요)"

        lbl_status_desc = tk.Label(summary_frame, text=status_text, font=("Malgun Gothic", 9), fg="#E2E8F0", bg="#1E293B", justify="left")
        lbl_status_desc.pack(anchor="w", padx=15, pady=(0, 8))

        # 탭 역할을 할 프레임
        tab_control = ttk.Notebook(popup)
        tab_control.pack(fill="both", expand=True, padx=20, pady=10)

        # 1. 추천 포트폴리오 탭
        tab_port = tk.Frame(tab_control, bg="#1E293B")
        tab_control.add(tab_port, text="  최종 추천 포트폴리오  ")

        # 좌우로 나누기 위한 프레임 생성
        port_left_frame = tk.Frame(tab_port, bg="#1E293B")
        port_left_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        port_right_frame = tk.Frame(tab_port, bg="#1E293B")
        port_right_frame.pack(side="right", fill="both", expand=False, padx=5, pady=5)

        # Treeview for Portfolio (좌측 프레임에 배치)
        cols_port = list(df_port.columns)
        tree_port = ttk.Treeview(port_left_frame, columns=cols_port, show="headings")
        for col in cols_port:
            tree_port.heading(col, text=col)
            # 정렬 및 너비 설정
            if col in ['Ticker', 'Market', 'Industry']:
                tree_port.column(col, width=80, anchor="center")
            elif col == 'Name':
                tree_port.column(col, width=120, anchor="w")
            elif col in ['Pure_Alpha(%)', 'AI_News_Score', 'Weight(%)']:
                tree_port.column(col, width=90, anchor="e")
            else:
                tree_port.column(col, width=110, anchor="e")
        tree_port.pack(fill="both", expand=True, padx=5, pady=5)

        # 원형 그래프 (Matplotlib) 그리기 및 임베드 (우측 프레임에 배치)
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import matplotlib.pyplot as plt
            import matplotlib.font_manager as fm
            
            # 한글 깨짐 방지 폰트 설정
            font_path = "C:/Windows/Fonts/malgun.ttf"
            if os.path.exists(font_path):
                font_name = fm.FontProperties(fname=font_path).get_name()
                matplotlib.rc('font', family=font_name)
            else:
                matplotlib.rc('font', family='Malgun Gothic')
                
            fig, ax = plt.subplots(figsize=(4.0, 4.0), dpi=100)
            fig.patch.set_facecolor('#1E293B')
            ax.set_facecolor('#1E293B')
            
            df_sorted = df_port.sort_values(by='Weight(%)', ascending=False)
            labels = df_sorted['Name'].tolist()
            sizes = df_sorted['Weight(%)'].tolist()
            
            # 미국 주식은 파란색 계열, 한국 주식은 초록색 계열로 칠함
            colors = []
            for _, row in df_sorted.iterrows():
                market = row.get('Market', '')
                ticker = row.get('Ticker', '')
                ticker_str = str(ticker)
                is_us = 'SP500' in str(market) or not (ticker_str.isdigit() or ticker_str.endswith('.KS') or ticker_str.endswith('.KQ'))
                if is_us:
                    colors.append('#2563EB') # Blue
                else:
                    colors.append('#059669') # Emerald
                    
            wedges, texts, autotexts = ax.pie(
                sizes,
                labels=labels,
                autopct='%1.1f%%',
                startangle=140,
                colors=colors,
                textprops=dict(color="white", fontsize=8),
                pctdistance=0.7
            )
            
            # 텍스트 스타일링
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontsize(8)
                autotext.set_weight('bold')
            for text in texts:
                text.set_color('#E2E8F0')
                text.set_fontsize(8)
                
            ax.axis('equal')
            
            canvas = FigureCanvasTkAgg(fig, master=port_right_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=5, pady=5)
            plt.close(fig)
        except Exception as e:
            print(f"[PIE CHART ERROR] {e}")
            # 차트 렌더링 실패 시 우측 프레임을 파괴하고 좌측 프레임을 전체로 채움
            port_right_frame.destroy()
            port_left_frame.pack_configure(fill="both", expand=True)
        
        # 데이터 삽입
        for _, row in df_port.iterrows():
            vals = []
            for col in cols_port:
                val = row[col]
                # 포맷팅
                if col == 'Weight(%)' and pd.notna(val):
                    vals.append(f"{float(val):.2f}%")
                elif col == 'Invest_Amount(KRW)' and pd.notna(val):
                    vals.append(f"₩{int(val):,}")
                elif col in ['Pure_Alpha(%)', 'AI_News_Score'] and pd.notna(val):
                    vals.append(f"{float(val):.2f}")
                else:
                    vals.append(str(val) if pd.notna(val) else "")
            tree_port.insert("", "end", values=vals)

        # 2. 리밸런싱 주문 계획 탭
        tab_rebal = tk.Frame(tab_control, bg="#1E293B")
        tab_control.add(tab_rebal, text="  리밸런싱 매매 주문서  ")

        if df_rebal is not None and not df_rebal.empty:
            cols_rebal = list(df_rebal.columns)
            tree_rebal = ttk.Treeview(tab_rebal, columns=cols_rebal, show="headings")
            for col in cols_rebal:
                tree_rebal.heading(col, text=col)
                if col in ['Ticker', 'Toss_Symbol', 'Action', 'Currency']:
                    tree_rebal.column(col, width=80, anchor="center")
                elif col == 'Name':
                    tree_rebal.column(col, width=140, anchor="w")
                elif col in ['Reason']:
                    tree_rebal.column(col, width=220, anchor="w")
                elif col in ['Current_Qty', 'Target_Qty', 'Diff_Qty']:
                    tree_rebal.column(col, width=80, anchor="e")
                else:
                    tree_rebal.column(col, width=100, anchor="e")
            tree_rebal.pack(fill="both", expand=True, padx=10, pady=10)

            for _, row in df_rebal.iterrows():
                vals = []
                for col in cols_rebal:
                    val = row[col]
                    # 포맷팅
                    if col in ['Target_Value(KRW)', 'Current_Value(KRW)', 'Diff_Value(KRW)'] and pd.notna(val):
                        vals.append(f"₩{int(val):,}")
                    elif col in ['Target_Weight(%)'] and pd.notna(val):
                        vals.append(f"{float(val):.2f}%")
                    elif col in ['Current_Qty', 'Target_Qty', 'Diff_Qty'] and pd.notna(val):
                        vals.append(f"{float(val):.4f}" if float(val) % 1 != 0 else f"{int(val)}")
                    elif col == 'Current_Price' and pd.notna(val):
                        vals.append(f"{float(val):,.2f}")
                    else:
                        vals.append(str(val) if pd.notna(val) else "")
                tree_rebal.insert("", "end", values=vals)
        else:
            lbl_no_trade = tk.Label(tab_rebal, text="매매 주문이 없습니다. (포트폴리오 비율이 유지 조건에 잘 부합합니다)", font=("Malgun Gothic", 12), fg="#94A3B8", bg="#1E293B")
            lbl_no_trade.pack(expand=True)

        # 하단 컨트롤 영역
        btn_frame = tk.Frame(popup, bg="#0F172A", pady=15)
        btn_frame.pack(fill="x", side="bottom")

        # 임시 보관된 시점 데이터를 저장하기 위해 팝업 내부 클로저로 엑셀 저장 함수 정의
        temp_data_for_excel = temp_output  # 실제로는 이미 파일은 삭제되었지만, 팝업 생성 시 데이터를 이미 화면에 채웠고,
        # 사용자가 엑셀로 내보내기를 원하면 재생성하거나, 삭제 전 데이터를 메모리에 버퍼링해두었다가 원클러 저장하게 합니다.
        # 가장 단순하고 버그가 없는 것은 temp_output 파일을 _request 처럼 화면을 닫을 때까지 유지하다가 닫을 때 지우는 것입니다.
        # 이를 위해, 위에서 바로 지우지 말고, popup 창이 닫힐 때(destroy) 지우도록 이벤트를 바인딩하겠습니다!

        def save_excel():
            output_file = filedialog.asksaveasfilename(
                initialfile='stock_analysis_results.xlsx',
                title="분석 결과를 저장할 엑셀 파일 위치 선택",
                defaultextension=".xlsx",
                filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")]
            )
            if output_file:
                try:
                    # 화면 로드를 위해 아직 지우지 않고 대기시켜둔 temp_output을 복사
                    shutil.copy(temp_output, output_file)
                    messagebox.showinfo("저장 완료", f"엑셀 보고서가 성공적으로 저장되었습니다:\n{output_file}")
                except Exception as err:
                    messagebox.showerror("저장 실패", f"파일 저장 중 오류 발생: {err}")

        btn_save = tk.Button(btn_frame, text="📥 엑셀 파일 저장", font=("Malgun Gothic", 10, "bold"),
                             bg="#3B82F6", fg="#FFFFFF", activebackground="#2563EB", activeforeground="#FFFFFF",
                             relief="flat", padx=15, pady=5, command=save_excel)
        btn_save.pack(side="left", padx=20)


            
        def show_execution_log_popup(stdout_text, stderr_text):
            log_popup = tk.Toplevel(self.root)
            log_popup.title("📄 실계좌 주문 전송 실행 로그")
            log_popup.geometry("750x500")
            log_popup.configure(bg="#0F172A")
            log_popup.transient(popup)
            log_popup.grab_set()
            
            lbl_title = tk.Label(log_popup, text="📋 토스증권 Open API 주문 전송 실행 결과 로그", font=("Malgun Gothic", 12, "bold"), fg="#3B82F6", bg="#0F172A")
            lbl_title.pack(pady=10)
            
            txt_frame = tk.Frame(log_popup, bg="#0F172A")
            txt_frame.pack(fill="both", expand=True, padx=20, pady=5)
            
            txt_log = tk.Text(txt_frame, bg="#1E293B", fg="#F8FAFC", insertbackground="white", font=("Consolas", 10), wrap="word", relief="flat")
            txt_log.pack(side="left", fill="both", expand=True)
            
            scroll = ttk.Scrollbar(txt_frame, orient="vertical", command=txt_log.yview)
            txt_log.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_stdout = ansi_escape.sub('', stdout_text)
            clean_stderr = ansi_escape.sub('', stderr_text)
            
            full_log = ""
            if clean_stdout:
                full_log += "=== 표준 출력 로그 ===\n" + clean_stdout + "\n"
            if clean_stderr:
                full_log += "=== 표준 에러/오류 로그 ===\n" + clean_stderr + "\n"
                
            txt_log.insert("1.0", full_log)
            txt_log.config(state="disabled")
            
            btn_close = tk.Button(log_popup, text="확인 후 닫기", font=("Malgun Gothic", 10, "bold"),
                                  bg="#64748B", fg="#FFFFFF", activebackground="#475569", activeforeground="#FFFFFF",
                                  relief="flat", padx=20, pady=5, command=log_popup.destroy)
            btn_close.pack(pady=15)

        # 실제 토스 계좌 주문 전송 함수
        def send_real_orders(market_filter):
            if df_rebal is None or df_rebal.empty:
                messagebox.showinfo("주문 대상 없음", "분석 결과 전송할 매매 리밸런싱 주문이 존재하지 않습니다.")
                return
                
            # 필터링 대상 주문 확인 (t_name.endswith('.KS') or t_name.endswith('.KQ') => 한국 주식)
            filtered_orders = []
            for t_name, row in df_rebal.iterrows():
                t_name_str = str(t_name)
                is_us = not (t_name_str.isdigit() or t_name_str.endswith('.KS') or t_name_str.endswith('.KQ'))
                if market_filter == 'KRX' and not is_us:
                    filtered_orders.append(t_name)
                elif market_filter == 'SP500' and is_us:
                    filtered_orders.append(t_name)
                    
            if not filtered_orders:
                market_name = "한국 주식(국장)" if market_filter == 'KRX' else "미국 주식(미장)"
                messagebox.showinfo("주문 대상 없음", f"전송 대상인 {market_name} 리밸런싱 주문이 존재하지 않습니다.")
                return
                
            market_msg = "한국 주식(국장)" if market_filter == 'KRX' else "미국 주식(미장)"
            confirm = messagebox.askyesno("⚠️ 실계좌 매매 전송", f"정말로 토스증권 Open API를 통해 실제 {market_msg} 매매 주문(시장가)을 보내시겠습니까?\n이 작업은 즉시 실제 주식 거래로 체결됩니다!")
            if not confirm:
                return
                
            btn_execute = btn_execute_kr if market_filter == 'KRX' else btn_execute_us
            btn_execute.config(state="disabled", text="⏳ 전송 중...")
            
            def execute_real_orders_bg():
                try:
                    import subprocess
                    cmd = ["python", "quant_analyzer.py", "--execute", "--output", "temp_exec_output.xlsx", "--market-filter", market_filter]
                    if self.is_offline:
                        cmd.append("--test")
                        
                    res = subprocess.run(cmd, capture_output=True)
                    
                    def decode_bytes(b):
                        for enc in ['utf-8', 'cp949', 'euc-kr']:
                            try:
                                return b.decode(enc)
                            except UnicodeDecodeError:
                                continue
                        return b.decode('utf-8', errors='replace')
                        
                    stdout_text = decode_bytes(res.stdout)
                    stderr_text = decode_bytes(res.stderr)
                    
                    if os.path.exists("temp_exec_output.xlsx"):
                        try:
                            os.remove("temp_exec_output.xlsx")
                        except Exception:
                            pass
                            
                    # 실행 결과 로그 창을 팝업
                    self.root.after(0, lambda: show_execution_log_popup(stdout_text, stderr_text))
                    
                    if res.returncode == 0:
                        self.root.after(0, lambda: btn_execute.config(text="✅ 전송 완료"))
                    else:
                        btn_text = "🚀 국장 주문 전송" if market_filter == 'KRX' else "🚀 미장 주문 전송"
                        self.root.after(0, lambda: btn_execute.config(state="normal", text=btn_text))
                except Exception as err:
                    self.root.after(0, lambda: messagebox.showerror("주문 실패", f"연동 프로세스 실행 실패: {err}"))
                    btn_text = "🚀 국장 주문 전송" if market_filter == 'KRX' else "🚀 미장 주문 전송"
                    self.root.after(0, lambda: btn_execute.config(state="normal", text=btn_text))
                finally:
                    self.root.after(0, self.manual_refresh)
                    
            threading.Thread(target=execute_real_orders_bg, daemon=True).start()

        # 실제 국장 주문 전송 버튼
        btn_execute_kr = tk.Button(btn_frame, text="🚀 국장 주문 전송", font=("Malgun Gothic", 10, "bold"),
                                   bg="#059669", fg="#FFFFFF", activebackground="#047857", activeforeground="#FFFFFF",
                                   relief="flat", padx=15, pady=5, command=lambda: send_real_orders('KRX'))
        btn_execute_kr.pack(side="left", padx=10)

        # 실제 미장 주문 전송 버튼
        btn_execute_us = tk.Button(btn_frame, text="🚀 미장 주문 전송", font=("Malgun Gothic", 10, "bold"),
                                   bg="#2563EB", fg="#FFFFFF", activebackground="#1D4ED8", activeforeground="#FFFFFF",
                                   relief="flat", padx=15, pady=5, command=lambda: send_real_orders('SP500'))
        btn_execute_us.pack(side="left", padx=10)

        # 창이 닫힐 때 임시 파일 제거 이벤트 바인딩
        def on_popup_close():
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception:
                    pass
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", on_popup_close)

        btn_close = tk.Button(btn_frame, text="확인 / 닫기", font=("Malgun Gothic", 10, "bold"),
                              bg="#64748B", fg="#FFFFFF", activebackground="#475569", activeforeground="#FFFFFF",
                              relief="flat", padx=15, pady=5, command=on_popup_close)
        btn_close.pack(side="right", padx=20)




if __name__ == "__main__":
    root = tk.Tk()
    app = LiveDashboardApp(root)
    
    def on_closing():
        app.is_running = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
