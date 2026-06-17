import requests
from bs4 import BeautifulSoup
import json

url = "https://finance.naver.com/sise/sise_market_sum.naver"
headers = {"User-Agent": "Mozilla/5.0"}

res = requests.get(url, headers=headers)
res.encoding = "euc-kr"

soup = BeautifulSoup(res.text, "html.parser")

stocks = []

for row in soup.select("table.type_2 tr"):
    cols = row.find_all("td")
    if len(cols) < 12:
        continue

    a = cols[1].find("a")
    if not a:
        continue

    name = a.text.strip()

    if name.endswith("우"):
        continue

    stocks.append({
        "rank": len(stocks) + 1,
        "name": name,
        "price": cols[2].text.strip(),
        "market_cap": cols[6].text.strip()
    })

    if len(stocks) >= 5:
        break

with open("stocks.json", "w", encoding="utf-8") as f:
    json.dump(stocks, f, ensure_ascii=False, indent=2)

print("stocks.json 생성 완료")
