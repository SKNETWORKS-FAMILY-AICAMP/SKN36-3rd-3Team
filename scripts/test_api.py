
import os
import requests
import xml.etree.ElementTree as ET

API_KEY = os.environ["DATA_API_KEY"]

url = (
    "http://apis.data.go.kr/B554287/"
    "NationalWelfareInformationsV001/"
    "NationalWelfarelistV001"
)

params = {
    "serviceKey": API_KEY,
    "callTp": "L",
    "pageNo": 1,
    "numOfRows": 10,
    "srchKeyCode": "001"
}

response = requests.get(
    url,
    params=params,
    timeout=30
)

response.raise_for_status()

root = ET.fromstring(response.content)

print("HTTP 상태:", response.status_code)
print("전체 서비스 수:", root.findtext("totalCount"))
print("결과 코드:", root.findtext("resultCode"))
print("결과 메시지:", root.findtext("resultMessage"))

for service in root.findall("servList"):
    print(
        service.findtext("servId"),
        service.findtext("servNm")
    )
