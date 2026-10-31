import os, re, sys
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import pyrebase

BASE = "https://youngpa.sen.hs.kr"
LIST_URL = BASE + "/66884/subMenu.do"
DETAIL_URL = BASE + "/dggb/module/mlsv/selectMlsvDetailPopup.do"
SITE_ID = "SEI_00001241"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": LIST_URL}

KST = pytz.timezone("Asia/Seoul")


def clean_items(text):
    text = re.sub(r"\([^)]*\)", "", text)          # (알레르기 번호) 제거
    parts = re.split(r"[\n,]+", text)
    items = []
    for p in parts:
        p = re.sub(r"[0-9.\s]+$", "", p.strip())    # 끝에 붙은 알레르기 숫자 제거
        p = p.strip(" ·-*")
        if p:
            items.append(p)
    return items


def get_month_ids(session, year, month):
    """달력 화면에서 {날짜: 중식 mlsvId} 추출"""
    r = session.post(LIST_URL, headers=HEADERS, timeout=20, data={
        "viewType": "calendar", "siteId": SITE_ID, "arrMlsvId": "0",
        "srhMlsvYear": str(year), "srhMlsvMonth": f"{month:02d}",
    })
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    result = {}
    for td in soup.select(".calendar_schedule td"):
        m = re.match(r"\s*(\d{1,2})\b", td.get_text(" ", strip=True))
        if not m:
            continue
        day = int(m.group(1))
        for a in td.find_all("a"):
            if a.get_text(strip=True) == "중식":
                mm = re.search(r"fnDetail\('(\d+)'", a.get("onclick", ""))
                if mm:
                    result[f"{year}-{month:02d}-{day:02d}"] = mm.group(1)
    return result


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    # 1순위: '식단/메뉴/요리' 라벨 옆 칸
    for th in soup.find_all(["th", "dt"]):
        label = th.get_text(strip=True)
        if any(k in label for k in ("식단", "메뉴", "요리")):
            nxt = th.find_next(["td", "dd"])
            if nxt:
                items = clean_items(nxt.get_text("\n"))
                if items:
                    return items
    # 2순위: 가장 긴 텍스트 덩어리
    texts = [t.get_text("\n") for t in soup.find_all(["td", "dd", "p", "div"])]
    texts = [t for t in texts if len(t) > 10]
    if texts:
        return clean_items(max(texts, key=len))
    return []


def main():
    config = {
        "apiKey": os.environ["FIREBASE_API_KEY"],
        "authDomain": "cafeteria-system-966d8.firebaseapp.com",
        "databaseURL": os.environ["FIREBASE_DATABASE_URL"],
        "storageBucket": "cafeteria-system-966d8.appspot.com",
    }
    fb = pyrebase.initialize_app(config)
    auth = fb.auth()
    user = auth.sign_in_with_email_and_password(os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PW"])
    token = user["idToken"]
    db = fb.database()

    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    months = [(now.year, now.month)]
    months.append((now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1))

    session = requests.Session()
    ids = {}
    for y, m in months:
        try:
            ids.update(get_month_ids(session, y, m))
        except Exception as e:
            print(f"[경고] {y}-{m} 목록 실패: {e}")
    ids = {d: i for d, i in ids.items() if d >= today}
    print(f"대상 날짜 {len(ids)}개: {sorted(ids)[:5]} ...")

    menus = {}
    first = True
    for d, mid in sorted(ids.items()):
        try:
            r = session.post(DETAIL_URL, data={"mlsvId": mid}, headers=HEADERS, timeout=20)
            r.raise_for_status()
            if first:
                print("--- 첫 상세 응답(앞 1500자) ---")
                print(r.text[:1500])
                first = False
            items = parse_detail(r.text)
            if items:
                menus[d] = items
                print(d, items)
            else:
                print(d, "메뉴 못 찾음")
        except Exception as e:
            print(d, "실패:", e)

    if not menus:
        print("저장할 메뉴가 없습니다")
        sys.exit(1)
    db.child("menu").update(menus, token)
    print(f"저장 완료: {len(menus)}일")


if __name__ == "__main__":
    main()
