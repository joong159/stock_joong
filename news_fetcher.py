import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import yfinance as yf


def parse_yfinance_news_article(article):
    content = article.get("content", {})
    if content:
        title = content.get("title", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "") if provider else ""
        link = content.get("clickThroughUrl", {}).get("url") or content.get("canonicalUrl", {}).get("url") or ""
        pub_date_str = content.get("pubDate")
        time_val = 0
        if pub_date_str:
            try:
                dt = datetime.datetime.strptime(pub_date_str.replace("Z", "+00:00"), "%Y-%m-%dT%H:%M:%S%z")
                time_val = int(dt.timestamp())
            except Exception:
                pass
        return {
            "title": title,
            "publisher": publisher,
            "link": link,
            "time": time_val
        }
    return {}


def fetch_stock_news(symbol, name):
    is_kr = symbol.endswith('.KS') or symbol.endswith('.KQ') or (len(symbol) == 6 and symbol.isdigit())

    # 1. 국장인 경우 Google News RSS로 즉시 이동
    if is_kr:
        query = name
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)
                items = []
                for item in root.findall(".//item")[:2]:  # 최대 2개 뉴스
                    title = item.find("title").text
                    link = item.find("link").text
                    pub_date = item.find("pubDate").text
                    source = item.find("source").text if item.find("source") is not None else "Google News"
                    try:
                        # Sat, 04 Jul 2026 00:00:00 GMT / GMT or local GMT representations
                        clean_pub_date = pub_date.split(" GMT")[0].split(" UTC")[0]
                        dt = datetime.datetime.strptime(clean_pub_date, "%a, %d %b %Y %H:%M:%S")
                        timestamp = int(dt.timestamp())
                    except Exception:
                        timestamp = int(datetime.datetime.now().timestamp())
                    items.append({
                        "symbol": symbol,
                        "title": title,
                        "publisher": source,
                        "link": link,
                        "time": timestamp
                    })
                return items
        except Exception as e:
            print(f"[Google News RSS Error] Failed for {name}: {e}")
            return []

    # 2. 미장인 경우 yfinance 뉴스 시도
    else:
        try:
            ticker_news = yf.Ticker(symbol).news
            if ticker_news:
                items = []
                for art in ticker_news[:2]:
                    parsed = parse_yfinance_news_article(art)
                    if parsed.get("title"):
                        items.append({
                            "symbol": symbol,
                            "title": parsed["title"],
                            "publisher": parsed["publisher"],
                            "link": parsed["link"],
                            "time": parsed["time"]
                        })
                return items
        except Exception as ex:
            print(f"[yfinance News Error] Failed for {symbol}: {ex}")

        # yfinance 실패 시 Google News RSS로 폴백
        query = symbol
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)
                items = []
                for item in root.findall(".//item")[:2]:
                    title = item.find("title").text
                    link = item.find("link").text
                    pub_date = item.find("pubDate").text
                    source = item.find("source").text if item.find("source") is not None else "Google News"
                    try:
                        clean_pub_date = pub_date.split(" GMT")[0].split(" UTC")[0]
                        dt = datetime.datetime.strptime(clean_pub_date, "%a, %d %b %Y %H:%M:%S")
                        timestamp = int(dt.timestamp())
                    except Exception:
                        timestamp = int(datetime.datetime.now().timestamp())
                    items.append({
                        "symbol": symbol,
                        "title": title,
                        "publisher": source,
                        "link": link,
                        "time": timestamp
                    })
                return items
        except Exception:
            return []
