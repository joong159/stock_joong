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
        
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)
        grid_frame.columnconfigure(2, weight=1)
        grid_frame.columnconfigure(3, weight=1)
        
        # --- Holdings Table Header ---
        lbl_holdings = tk.Label(self.root, text="📂 실시간 보유 주식 잔고 현황", font=("Malgun Gothic", 12, "bold"), fg="#F8FAFC", bg="#0F172A")
        lbl_holdings.pack(anchor="w", padx=30, pady=(10, 5))
        
        # --- Holdings Treeview ---
        table_frame = tk.Frame(self.root, bg="#0F172A")
        table_frame.pack(fill="both", expand=True, padx=30, pady=5)
        
        self.tree = ttk.Treeview(table_frame, columns=("Symbol", "Qty", "Price", "Value", "Currency"), show="headings")
        self.tree.heading("Symbol", text="종목 코드")
        self.tree.heading("Qty", text="보유 수량")
        self.tree.heading("Price", text="현재가")
        self.tree.heading("Value", text="평가 금액(원화)")
        self.tree.heading("Currency", text="통화")
        
        self.tree.column("Symbol", width=120, anchor="center")
        self.tree.column("Qty", width=120, anchor="e")
        self.tree.column("Price", width=150, anchor="e")
        self.tree.column("Value", width=180, anchor="e")
        self.tree.column("Currency", width=100, anchor="center")
        self.tree.pack(fill="both", expand=True, side="left")
        
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
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
        btn_rebalance.pack(side="right", padx=20)
        
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
                        "currency": "USD" if is_us else "KRW"
                    })
                    
            # 4. 실시간 보유 종목 원화 평가가액 계산
            holdings_list = []
            stock_valuation = 0.0
            
            for item in toss_holdings:
                sym = item.get("symbol")
                qty = float(item.get("quantity", 0.0))
                price = float(item.get("lastPrice", 0.0))
                currency = item.get("currency", "KRW")
                
                price_krw = price * usd_krw if currency == "USD" else price
                val_krw = qty * price_krw
                stock_valuation += val_krw
                
                holdings_list.append((sym, qty, price, val_krw, currency))
                
            total_assets = cash_balance + stock_valuation
            
            # 메인 스레드 안전 업데이트
            self.root.after(0, self.update_gui_values, total_assets, cash_balance, stock_valuation, usd_krw, holdings_list)
        except Exception as e:
            self.root.after(0, self.show_error_message, str(e))
            
    def update_gui_values(self, total, cash, stock_val, rate, holdings_list):
        self.var_total_assets.set(f"₩ {total:,.0f}")
        self.var_cash.set(f"₩ {cash:,.0f}")
        self.var_stock_val.set(f"₩ {stock_val:,.0f}")
        self.var_exchange_rate.set(f"₩ {rate:,.2f}")
        
        # 목록 지우고 재작성
        for row in self.tree.get_children():
            self.tree.delete(row)
            
        for h in holdings_list:
            sym, qty, price, val, curr = h
            # 수량과 금액 예쁘게 포맷
            qty_str = f"{qty:.6f}" if curr == "USD" else f"{qty:,.0f}"
            price_str = f"$ {price:,.2f}" if curr == "USD" else f"₩ {price:,.0f}"
            val_str = f"₩ {val:,.0f}"
            
            self.tree.insert("", "end", values=(sym, qty_str, price_str, val_str, curr))
            
    def show_error_message(self, err_msg):
        self.var_countdown.set("⚠️ 통신 에러 발생")
        print(f"[DASHBOARD ERROR] {err_msg}")
        
    def auto_refresh_loop(self):
        """
        5초 주기 자동 갱신 루프 스레드
        """
        while self.is_running:
            self.fetch_live_data()
            
            # 5초 카운트다운 매초 갱신
            for sec in range(5, 0, -1):
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
            try:
                import subprocess
                import shutil
                # S&P500, KRX 분석 및 엑셀 출력을 포함한 파이썬 스크립트 백그라운드 호출
                cmd = ["python", "quant_analyzer.py", "--output", temp_output]
                if self.is_offline:
                    cmd.append("--test") # 오프라인 모드일 땐 가볍게 11개 대형주 테스트 유니버스로 실행
                    
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
                
                # 결과 출력 확인
                if res.returncode == 0:
                    def ask_save():
                        save_confirm = messagebox.askyesno("엑셀 보고서 저장", "퀀트 리밸런싱 분석 및 주문 전송이 성공적으로 완료되었습니다!\n분석 결과 엑셀 보고서 파일을 저장하시겠습니까?")
                        if save_confirm:
                            output_file = filedialog.asksaveasfilename(
                                initialfile='stock_analysis_results.xlsx',
                                title="분석 결과를 저장할 엑셀 파일 위치 선택",
                                defaultextension=".xlsx",
                                filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")]
                            )
                            if output_file:
                                try:
                                    shutil.copy(temp_output, output_file)
                                    messagebox.showinfo("저장 완료", f"엑셀 보고서가 성공적으로 저장되었습니다:\n{output_file}")
                                except Exception as err:
                                    messagebox.showerror("저장 실패", f"파일 저장 중 오류 발생: {err}")
                    self.root.after(0, ask_save)
                else:
                    self.root.after(0, lambda: messagebox.showerror("오류 발생", f"퀀트 분석기 실행 실패:\n{res.stderr}"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("오류 발생", f"오류 메시지: {e}"))
            finally:
                # 임시 파일 삭제
                if os.path.exists(temp_output):
                    try:
                        os.remove(temp_output)
                    except Exception:
                        pass
                self.root.after(0, self.manual_refresh)
                
        threading.Thread(target=execute_backend, daemon=True).start()



if __name__ == "__main__":
    root = tk.Tk()
    app = LiveDashboardApp(root)
    
    def on_closing():
        app.is_running = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
