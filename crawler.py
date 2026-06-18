import requests
from bs4 import BeautifulSoup
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# 한국 시간(KST) 기준 날짜 설정
kst = timezone(timedelta(hours=9))
now = datetime.now(kst)
update_time_str = now.strftime("%y.%m.%d %H:%M") # YY.MM.DD HH:MM 형식

data_result = {
    "updated_at": update_time_str,
    "stocks": [],
    "real_estate": []
}

# --- 1. 네이버 증권 시가총액 TOP 5 크롤링 ---
try:
    stock_url = "https://finance.naver.com/sise/sise_market_sum.naver"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(stock_url, headers=headers)
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
    data_result["stocks"] = stocks
except Exception as e:
    print(f"주식 크롤링 오류: {e}")

# --- 2. 국토교통부 실거래가 Open API 연동 ---
api_key = os.environ.get("MOLIT_API_KEY")

if api_key:
    # 당월 거래가 아직 신고되지 않았을 수 있으므로 이번 달과 지난달을 모두 조회
    months = [now.strftime("%Y%m")]
    first_of_this_month = now.replace(day=1)
    prev_month = first_of_this_month - timedelta(days=1)
    months.append(prev_month.strftime("%Y%m"))

    def fetch_apartment_deals(lawd_cd, apt_keyword):
        deals = []
        url = "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev"
        
        for ym in months:
            params = {
                "serviceKey": requests.utils.unquote(api_key),
                "pageNo": "1",
                "numOfRows": "100",
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": ym
            }
            try:
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    root = ET.fromstring(response.content)
                    if root.find(".//resultCode").text == "00":
                        for item in root.findall(".//item"):
                            apt_name = item.find("아파트").text if item.find("아파트") is not None else ""
                            if apt_keyword in apt_name:
                                price = item.find("거래금액").text.strip()
                                area = item.find("전용면적").text.strip()
                                floor = item.find("층").text if item.find("층") is not None else "-"
                                month = item.find("월").text.strip()
                                day = item.find("일").text.strip()
                                
                                deals.append({
                                    "apt_name": apt_name,
                                    "price": price,
                                    "area": str(round(float(area), 1)),
                                    "floor": floor,
                                    "date": f"{month}/{day}"
                                })
            except Exception as e:
                print(f"{apt_keyword} API 조회 중 오류 발생 ({ym}): {e}")
        return deals

    # 만안구(41171) - 메가트리아 / 동안구(41173) - 센텀퍼스트 각각 최신 데이터 수집
    megatria_list = fetch_apartment_deals("41171", "래미안안양메가트리아")
    centum_list = fetch_apartment_deals("41173", "평촌센텀퍼스트") or fetch_apartment_deals("41173", "센텀퍼스트")

    # 각 아파트별 가장 최근 실거래 2건씩만 등록
    for d in megatria_list[:2]:
        data_result["real_estate"].append({
            "title": f"{d['apt_name']} ({d['area']}㎡) {d['floor']}층 | {d['date']} 계약",
            "price": f"{d['price']}만원"
        })
    for d in centum_list[:2]:
        data_result["real_estate"].append({
            "title": f"{d['apt_name']} ({d['area']}㎡) {d['floor']}층 | {d['date']} 계약",
            "price": f"{d['price']}만원"
        })

    if not data_result["real_estate"]:
        data_result["real_estate"].append({"title": "최근 2개월 내 신고된 실거래가가 없습니다.", "price": "-"})
else:
    data_result["real_estate"].append({"title": "GitHub Secrets에 MOLIT_API_KEY가 없습니다.", "price": "-"})

# --- 3. 통합 JSON 파일 저장 ---
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data_result, f, ensure_ascii=False, indent=2)

print("data.json 데이터 갱신 완료")
