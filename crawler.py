import requests
from bs4 import BeautifulSoup
import json
import os
import xml.etree.ElementTree as ET
import time
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

# --- 2. 국토교통부 실거래가 Open API 연동 (네트워크 에러 완벽 방어 버전) ---
api_key = os.environ.get("MOLIT_API_KEY")

if api_key:
    # 이번 달과 지난달 데이터 모두 조회
    months = [now.strftime("%Y%m")]
    first_of_this_month = now.replace(day=1)
    prev_month = first_of_this_month - timedelta(days=1)
    months.append(prev_month.strftime("%Y%m"))

    def fetch_apartment_deals(lawd_cd, apt_keyword):
        deals = []
        
        # 서버 상태에 따라 http와 https 중 열려있는 포트로 우회하기 위한 리스트
        base_urls = [
            "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev",
            "https://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev"
        ]
        
        # 🔥 차단 방지: 실제 윈도우 크롬 브라우저에서 요청하는 것처럼 헤더 위장
        request_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/xml, text/xml, */*"
        }
        
        for ym in months:
            params = {
                "pageNo": "1",
                "numOfRows": "100",
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": ym
            }
            
            success = False
            last_error = "알 수 없는 에러"
            
            # 🔥 일시적 접속 끊김을 방지하기 위해 최대 3회 재시도 (Backoff Retry)
            for attempt in range(3):
                # 0번째 시도는 http, 1~2번째 재시도는 https 등으로 프로토콜 교차 테스트
                base_url = base_urls[attempt % 2]
                url = f"{base_url}?serviceKey={api_key}"
                
                try:
                    # 타임아웃을 30초로 늘려 지연 응답 대기
                    response = requests.get(url, params=params, headers=request_headers, timeout=30)
                    
                    if response.status_code == 200:
                        root = ET.fromstring(response.content)
                        result_code_el = root.find(".//resultCode")
                        
                        if result_code_el is not None and result_code_el.text == "00":
                            for item in root.findall(".//item"):
                                apt_name = item.find("아파트").text if item.find("아파트") is not None else ""
                                
                                # 띄어쓰기 무시 매칭
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
                            success = True
                            break # 성공했으므로 재시도 루프 탈출
                        else:
                            msg = root.find(".//resultMsg").text if root.find(".//resultMsg") is not None else "인증 에러"
                            last_error = f"API 리턴 에러 ({result_code_el.text if result_code_el is not None else '?'}): {msg}"
                    else:
                        last_error = f"HTTP 응답 에러 (상태코드: {response.status_code})"
                        
                except Exception as e:
                    last_error = f"접속 실패 ({str(e)})"
                
                # 실패 시 즉시 재시도하지 않고 3초간 서버 호흡을 고른 후 재접속
                if not success and attempt < 2:
                    time.sleep(3)
            
            # 3번 모두 실패한 경우 최종 에러 메시지를 결과에 심어둠
            if not success:
                return [{"error_msg": f"{ym} 조회 실패 -> {last_error}"}]
                
        return deals

    # 안양 메가트리아 / 평촌 센텀퍼스트 각각 데이터 수집
    megatria_list = fetch_apartment_deals("41171", "메가트리아")
    centum_list = fetch_apartment_deals("41173", "센텀퍼스트")

    # 리스트 내부 에러 검사
    all_responses = megatria_list + centum_list
    api_errors = [d["error_msg"] for d in all_responses if isinstance(d, dict) and "error_msg" in d]

    if api_errors:
        data_result["real_estate"].append({
            "title": f"⚠️ {api_errors[0]}",
            "price": "확인 요망"
        })
    else:
        # 정상 데이터 결합 (각각 최신 거래 최대 3건 표시)
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
