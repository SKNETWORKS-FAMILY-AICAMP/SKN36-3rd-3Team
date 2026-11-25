import re
import json
import unicodedata

AREA_CODES = {'044', '063', '041', '010', '051', '062', '043', '02', '064', '031', '042', '032', '055', '033', '052', '054', '050', '053', '070', '080', '061'}

def parse_values(value):

    if isinstance(value, list):
        return value

    if value is None:
        return []

    text = str(value).strip()

    if text.lower() in ["", "nan", "none", "null"]:
        return []

    try:
        parsed = json.loads(text)

        if isinstance(parsed, list):
            return parsed

    except (ValueError, TypeError):
        pass

    return [text]


def normalize_phone(value):

    text = str(value).strip()

    if not re.fullmatch(r"[\d\s\-().]+", text):
        return None

    digits = re.sub(r"\D", "", text)

    # 서울 및 일반 지역번호
    for area in sorted(AREA_CODES, key=len, reverse=True):

        if digits.startswith(area):

            rest = digits[len(area):]

            if len(rest) in (7, 8):

                return (
                    f"{area}-{rest[:-4]}-{rest[-4:]}"
                )

    # 대표번호
    if re.fullmatch(r"1[568]\d{6}", digits):
        return f"{digits[:4]}-{digits[4:]}"

    return None


def extract_improved_contacts(raw_value):

    phones = []
    review = []

    for value in parse_values(raw_value):

        text = unicodedata.normalize(
            "NFKC", str(value)
        ).strip()

        # URL은 전화번호 추출 대상에서 제외
        if re.search(
            r"https?://|www\.",
            text,
            flags=re.I
        ):
            continue

        # 축약 전화번호 처리
        parts = re.split(r"[,/;\n]+", text)

        previous = None

        for part in parts:

            part = part.strip()

            if not part:
                continue

            phone = normalize_phone(part)

            if phone:
                phones.append(phone)
                previous = phone
                continue

            # 063-430-2913, 2915 형식
            if (
                previous
                and re.fullmatch(r"\d{4}", part)
            ):
                candidate = (
                    previous.rsplit("-", 1)[0]
                    + "-" + part
                )

                review.append({
                    "candidate": candidate,
                    "raw": text,
                    "reason": "축약 번호 복원"
                })

                continue

            # 범위 표현, 지역번호 누락, 단축번호
            if re.search(r"\d", part):

                review.append({
                    "raw": part,
                    "reason": "추가 형식 검토 필요"
                })

    return {
        "phones": list(dict.fromkeys(phones)),
        "review": review
    }

