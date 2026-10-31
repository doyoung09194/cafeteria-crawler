import os, re, sys
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

BASE = "https://youngpa.sen.hs.kr"
LIST_URL = BASE + "/66884/subMenu.do"
DETAIL_URL = BASE + "/dggb/module/mlsv/selectMlsvDetailPopup.do"
SITE_ID = "SEI_00001241"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": LIST_URL}
KST = pytz.timezone("Asia/Seoul")


def clean_items(text):
    text = re.sub(r"\([^)]*\)", "", text)
    items = []
    for p in re.split(r"[\n,]+", text):
        p = re.sub(r"[0-9.\s]+$", "", p.strip()).strip(" ·-*")
        if p:
            items.append(p)
    return items


def get_month_ids(session, year, month):
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
    for th in soup.find_all(["th", "dt"]):
        label = th.get_text(strip=True)
        if any(k in label for k in ("식단", "메뉴", "요리")):
            nxt = th.find_next(["td", "dd"])
            if nxt:
                items = clean_items(nxt.get_text("\n"))
                if items:
                    return items
    texts = [t.get_text("\n") for t in soup.find_all(["td", "dd", "p", "div"])]
    texts = [t for t in texts if len(t) > 10]
    return clean_items(max(texts, key=len)) if texts else []


def firebase_login():
    url = ("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key="
           + os.environ.get("FIREBASE_API_KEY", ""))
    r = requests.post(url, json={
        "email": os.environ.get("ADMIN_EMAIL", ""),
        "password": os.environ.get("ADMIN_PW", ""),
        "returnSecureToken": True,
    }, timeout=20)
    if not r.ok:
        print("로그인 실패:", r.status_code, r.text[:300])
        print("값 길이 확인:",
              len(os.environ.get("FIREBASE_API_KEY", "")),
              len(os.environ.get("ADMIN_EMAIL", "")),
              len(os.environ.get("ADMIN_PW", "")))
        r.raise_for_status()
    return r.json()["idToken"]


def main():
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
    for d, mid in sorted(ids.items()):
        try:
            r = session.post(DETAIL_URL, data={"mlsvId": mid}, headers=HEADERS, timeout=20)
            r.raise_for_status()
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

    token = firebase_login()
    db_url = os.environ["FIREBASE_DATABASE_URL"].rstrip("/")
    r = requests.patch(f"{db_url}/menu.json?auth={token}", json=menus, timeout=30)
    print("저장 응답:", r.status_code, r.text[:200])
    r.raise_for_status()
    print(f"저장 완료: {len(menus)}일")


if __name__ == "__main__":
    main()
