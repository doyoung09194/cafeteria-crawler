"""기상청 단기예보 + 에어코리아 미세먼지 → Firebase RTDB(/weather) 저장

저장 형태 (점심시간 12~13시 기준):
  /weather/updated = "2026-11-13T09:40:00+09:00"
  /weather/days/2026-11-14 = { temp: 8.5, pop: 30, code: 2, dust: 1 }
    temp  : 12시·13시 기온 평균(℃)
    pop   : 12시·13시 강수확률 최댓값(%)
    code  : 하늘 상태(WMO 코드로 변환: 0 맑음, 2 구름 많음, 3 흐림, 63 비, 67 비/눈, 73 눈, 81 소나기)
    dust  : 미세먼지 등급(0 좋음, 1 보통, 2 나쁨, 3 매우 나쁨) — 오늘은 실측, 그 외는 예보

환경변수: KMA_KEY, AIR_KEY, FIREBASE_API_KEY, FIREBASE_DATABASE_URL, ADMIN_EMAIL, ADMIN_PW
키는 Encoding/Decoding 어느 쪽이든 상관없습니다(%가 있으면 자동으로 되돌립니다).
"""
import math
import os
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import unquote

import pytz
import requests

from menu_crawler import firebase_login

KST = pytz.timezone("Asia/Seoul")
LAT, LON = 37.53, 127.12               # 송파구 풍납동 (학교 근처)
HOURS = ("1200", "1300")               # 점심시간
STATIONS = ["송파구", "강동구"]          # 에어코리아 측정소(앞에서부터 시도)
REGION = "서울"                         # 미세먼지 예보 지역
BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]   # 단기예보 발표 시각

KMA_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
AIR_REALTIME_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
AIR_FORECAST_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMinuDustFrcstDspth"

GRADE_BY_NAME = {"좋음": 0, "보통": 1, "나쁨": 2, "매우나쁨": 3}


def clean_key(k):
    k = (k or "").strip()
    return unquote(k) if "%" in k else k


def to_grid(lat, lon):
    """위경도 → 기상청 격자(nx, ny)"""
    RE, GRID = 6371.00877, 5.0
    SLAT1, SLAT2, OLON, OLAT = 30.0, 60.0, 126.0, 38.0
    XO, YO = 43, 136
    d = math.pi / 180.0
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * d, SLAT2 * d, OLON * d, OLAT * d
    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = math.pow(sf, sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / math.pow(ro, sn)
    ra = math.tan(math.pi * 0.25 + lat * d * 0.5)
    ra = re * sf / math.pow(ra, sn)
    theta = lon * d - olon
    if theta > math.pi:
        theta -= 2 * math.pi
    if theta < -math.pi:
        theta += 2 * math.pi
    theta *= sn
    x = math.floor(ra * math.sin(theta) + XO + 0.5)
    y = math.floor(ro - ra * math.cos(theta) + YO + 0.5)
    return int(x), int(y)


def base_datetime(now):
    """지금 받을 수 있는 가장 최근 발표 시각 (발표 후 15분 뒤부터 제공)"""
    t = now - timedelta(minutes=15)
    cands = [h for h in BASE_HOURS if h <= t.hour]
    if cands:
        return t.strftime("%Y%m%d"), f"{cands[-1]:02d}00"
    y = t - timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def call_json(url, params):
    r = requests.get(url, params=params, timeout=30)
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"JSON이 아닌 응답 {r.status_code}: {r.text[:200]}")
    head = data.get("response", {}).get("header", {})
    if head.get("resultCode") not in ("00", "0", None):
        raise RuntimeError(f"API 오류 {head.get('resultCode')}: {head.get('resultMsg')}")
    return data["response"]["body"]


def items_of(body):
    items = body.get("items")
    if isinstance(items, dict):
        items = items.get("item")
    return items or []


def sky_code(sky, pty):
    pty = int(pty or 0)
    if pty == 1:
        return 63
    if pty == 2:
        return 67
    if pty == 3:
        return 73
    if pty == 4:
        return 81
    return {1: 0, 3: 2, 4: 3}.get(int(sky or 1), 2)


def parse_kma(items):
    """단기예보 항목 → {날짜: {temp, pop, code}}"""
    by = {}
    for it in items:
        if it.get("fcstTime") not in HOURS:
            continue
        d = it["fcstDate"]
        d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        by.setdefault(d, {}).setdefault(it["category"], []).append(it["fcstValue"])
    out = {}
    for d, c in by.items():
        if "TMP" not in c:
            continue
        temps = [float(v) for v in c["TMP"]]
        pops = [float(v) for v in c.get("POP", [])]
        pty = max([int(float(v)) for v in c.get("PTY", ["0"])])
        sky = max([int(float(v)) for v in c.get("SKY", ["1"])])
        out[d] = {
            "temp": round(sum(temps) / len(temps), 1),
            "pop": int(max(pops)) if pops else 0,
            "code": sky_code(sky, pty),
        }
    return out


def fetch_kma(key, now):
    nx, ny = to_grid(LAT, LON)
    bd, bt = base_datetime(now)
    print(f"기상청: 격자 {nx},{ny} 발표 {bd} {bt}")
    body = call_json(KMA_URL, {
        "serviceKey": key, "pageNo": 1, "numOfRows": 1500, "dataType": "JSON",
        "base_date": bd, "base_time": bt, "nx": nx, "ny": ny,
    })
    days = parse_kma(items_of(body))
    print("기상청 날짜:", ", ".join(sorted(days)) or "없음")
    return days


def grade_pm(pm10, pm25):
    g10 = 0 if pm10 is None else 0 if pm10 <= 30 else 1 if pm10 <= 80 else 2 if pm10 <= 150 else 3
    g25 = 0 if pm25 is None else 0 if pm25 <= 15 else 1 if pm25 <= 35 else 2 if pm25 <= 75 else 3
    return max(g10, g25)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_air_now(key):
    """오늘 미세먼지: 측정소 최신 실측값 → 등급"""
    for st in STATIONS:
        try:
            body = call_json(AIR_REALTIME_URL, {
                "serviceKey": key, "returnType": "json", "numOfRows": 24, "pageNo": 1,
                "stationName": st, "dataTerm": "DAILY", "ver": "1.3",
            })
        except Exception as e:
            print(f"[경고] 측정소 {st} 실패: {e}")
            continue
        for it in items_of(body):           # 최신순
            p10, p25 = num(it.get("pm10Value")), num(it.get("pm25Value"))
            if p10 is not None or p25 is not None:
                print(f"에어코리아 실측({st} {it.get('dataTime')}): PM10 {p10} PM2.5 {p25}")
                return grade_pm(p10, p25)
    return None


def fetch_air_forecast(key, today):
    """오늘~모레 미세먼지 예보 등급 {날짜: 등급}"""
    grades = {}
    for code in ("PM10", "PM25"):
        body = call_json(AIR_FORECAST_URL, {
            "serviceKey": key, "returnType": "json", "numOfRows": 100, "pageNo": 1,
            "searchDate": today, "InformCode": code,
        })
        latest = {}
        for it in items_of(body):           # 같은 날짜는 가장 늦게 발표된 것만
            d = it.get("informData")
            if d and (d not in latest or it.get("dataTime", "") > latest[d].get("dataTime", "")):
                latest[d] = it
        for d, it in latest.items():
            m = re.search(REGION + r"\s*:\s*([^,]+)", it.get("informGrade", ""))
            if m and m.group(1).strip() in GRADE_BY_NAME:
                g = GRADE_BY_NAME[m.group(1).strip()]
                grades[d] = max(grades.get(d, 0), g)
    print("에어코리아 예보:", grades or "없음")
    return grades


def main():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    kma_key, air_key = clean_key(os.environ.get("KMA_KEY")), clean_key(os.environ.get("AIR_KEY"))

    days = {}
    if kma_key:
        try:
            for d, v in fetch_kma(kma_key, now).items():
                days.setdefault(d, {}).update(v)
        except Exception as e:
            print("[경고] 기상청 실패:", e)
    else:
        print("[경고] KMA_KEY 없음")

    if air_key:
        try:
            for d, g in fetch_air_forecast(air_key, today).items():
                days.setdefault(d, {})["dust"] = g
        except Exception as e:
            print("[경고] 미세먼지 예보 실패:", e)
        try:
            g = fetch_air_now(air_key)
            if g is not None:
                days.setdefault(today, {})["dust"] = g
        except Exception as e:
            print("[경고] 미세먼지 실측 실패:", e)
    else:
        print("[경고] AIR_KEY 없음")

    if not days:
        print("저장할 데이터가 없습니다")
        sys.exit(1)

    token = firebase_login()
    db_url = os.environ["FIREBASE_DATABASE_URL"].rstrip("/")
    old = {}
    try:
        r = requests.get(f"{db_url}/weather/days.json", timeout=30)
        if r.ok and isinstance(r.json(), dict):
            old = r.json()
    except Exception as e:
        print("[경고] 기존 데이터 읽기 실패:", e)

    merged = {d: v for d, v in old.items() if d >= today}      # 지난 날짜는 버림
    for d, v in days.items():
        merged.setdefault(d, {}).update(v)

    payload = {"updated": now.isoformat(), "days": merged}
    r = requests.put(f"{db_url}/weather.json?auth={token}", json=payload, timeout=30)
    print("저장 응답:", r.status_code, r.text[:200])
    r.raise_for_status()
    print(f"저장 완료: {len(merged)}일 ({', '.join(sorted(merged))})")


if __name__ == "__main__":
    main()
