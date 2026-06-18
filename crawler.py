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

# --- 2. 국토교통부 실거래가 Open API 연동 (버그 수정 버전) ---
api_key = os.environ.get("MOLIT_API_KEY")

if api_key:
    # 이번 달과 지난달 데이터 모두 조회
    months = [now.strftime("%Y%m")]
    first_of_this_month = now.replace(day=1)
    prev_month = first_of_this_month - timedelta(days=1)
    months.append(prev_month.strftime("%Y%m"))

    def fetch_apartment_deals(lawd_cd, apt_keyword):
        deals = []
        base_url = "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev"
        
        for ym in months:
            # 🔥 핵심 해결책: requests의 인코딩 버그를 피하기 위해 인코딩된 인증키를 URL 뒤에 강제로 직접 결합합니다.
            url = f"{base_url}?serviceKey={api_key}"
            params = {
                "pageNo": "1",
                "numOfRows": "100",
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": ym
            }
            try:
                response = requests.get(url, params=params, timeout=15)
                if response.status_code == 200:
                    root = ET.fromstring(response.content)
                    
                    result_code_el = root.find(".//resultCode")
                    if result_code_el is not None and result_code_el.text == "00":
                        for item in root.findall(".//item"):
                            apt_name = item.find("아파트").text if item.find("아파트") is not None else ""
                            
                            # 🔥 띄어쓰기 버그 방지: 검색어와 아파트 이름의 모든 공백을 제거하고 비교합니다.
                            target_keyword = apt_keyword.replace(" ", "")
                            target_apt_name = apt_name.replace(" ", "")
                            
                            if target_keyword in target_apt_name:
                                price = item.find("거래금액").text.strip()
                                area = item.find("전용면적").text.strip()
                                floor = item.find("층").text if item.find("층") is not None else "-"
                                month = item.find("월").text.strip()
                                day = item.find("일").text.strip()
                                
                                deals.append({
                                    "apt_name": apt_name.strip(),
                                    "price": price,
                                    "area": str(round(float(area), 1)),
                                    "floor": floor,
                                    "date": f"{month}/{day}"
                                })
                    else:
                        # API 인증 실패나 제한 걸렸을 때 원인을 파악하기 위해 에러 메시지 추출
                        msg = root.find(".//resultMsg").text if root.find(".//resultMsg") is not None else "인증 에러가 의심됩니다."
                        code = result_code_el.text if result_code_el is not None else "Error"
                        return [{"error_msg": f"공공데이터 API 에러 ({code}): {msg}"}]
            except Exception as e:
                return [{"error_msg": f"접속 실패: {str(e)}"}]
        return deals

    # 검색어를 단지명 핵심 키워드로 압축하여 매칭 확률 극대화
    megatria_list = fetch_apartment_deals("41171", "메가트리아")
    centum_list = fetch_apartment_deals("41173", "센텀퍼스트")

    # 에러가 발생했는지 검사
    all_responses = megatria_list + centum_list
    api_errors = [d["error_msg"] for d in all_responses if isinstance(d, dict) and "error_msg" in d]

    if api_errors:
        # 에러가 있다면 화면 리스트에 에러 메시지를 노출시켜 사용자가 원인을 볼 수 있게 함
        data_result["real_estate"].append({
            "title": f"⚠️ {api_errors[0]}",
            "price": "확인 요망"
        })
    else:
        # 정상 데이터 바인딩 (각 아파트별 최신 거래 최대 3건씩 표시)
        for d in megatria_list[:3]:
            data_result["real_estate"].append({
                "title": f"{d['apt_name']} ({d['area']}㎡) {d['floor']}층 | {d['date']}",
                "price": f"{d['price']}만원"
            })
        for d in centum_list[:3]:
            data_result["real_estate"].append({
                "title": f"{d['apt_name']} ({d['area']}㎡) {d['floor']}층 | {d['date']}",
                "price": f"{d['price']}만원"
            })

        if not data_result["real_estate"]:
            data_result["real_estate"].append({
                "title": "최근 2개월 내 신고된 실거래 내역이 존재하지 않습니다.",
                "price": "-"
            })
else:
    data_result["real_estate"].append({
        "title": "GitHub Secrets에 MOLIT_API_KEY가 설정되지 않았습니다.",
        "price": "-"
    })

# --- 3. 통합 JSON 파일 저장 ---
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data_result, f, ensure_ascii=False, indent=2)

print("data.json 갱신 완료")
