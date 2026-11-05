
import os
import csv
import json
import time
import requests
import xml.etree.ElementTree as ET

API_KEY = os.environ["DATA_API_KEY"]

URL = (
    "http://apis.data.go.kr/B554287/"
    "NationalWelfareInformationsV001/"
    "NationalWelfarelistV001"
)

all_services = []
page = 1
page_size = 100

while True:
    params = {
        "serviceKey": API_KEY,
        "callTp": "L",
        "pageNo": page,
        "numOfRows": page_size,
        "srchKeyCode": "001"
    }

    response = requests.get(
        URL, params=params, timeout=30
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)

    result_code = root.findtext("resultCode")
    if result_code != "0":
        raise RuntimeError(
            f"API 오류: {root.findtext('resultMessage')}"
        )

    total_count = int(root.findtext("totalCount", "0"))
    services = root.findall("servList")

    if not services:
        if len(all_services) < total_count:
            raise RuntimeError("예상보다 일찍 빈 페이지가 반환됨")
        break

    for service in services:
        item = {
            child.tag: child.text
            for child in service
        }
        all_services.append(item)

    print(
        f"페이지 {page} 완료: "
        f"{len(all_services)}/{total_count}건"
    )

    if len(all_services) >= total_count:
        break

    page += 1
    time.sleep(0.5)

os.makedirs("welfare_data", exist_ok=True)

json_path = "welfare_data/welfare_list.json"
csv_path = "welfare_data/welfare_list.csv"

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(
        all_services, f,
        ensure_ascii=False, indent=2
    )

fields = list(dict.fromkeys(
    key
    for item in all_services
    for key in item.keys()
))

with open(
    csv_path, "w",
    encoding="utf-8-sig",
    newline=""
) as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(all_services)

print(f"\n수집 완료: {len(all_services)}건")
print(f"JSON 저장: {json_path}")
print(f"CSV 저장: {csv_path}")
