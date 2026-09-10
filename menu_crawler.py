import requests
from bs4 import BeautifulSoup
import pyrebase
from datetime import datetime
import os
import pytz

config = {
    "apiKey": os.environ.get("FIREBASE_API_KEY"),
    "authDomain": "cafeteria-system-966d8.firebaseapp.com",
    "databaseURL": os.environ.get("FIREBASE_DATABASE_URL"),
    "storageBucket": "cafeteria-system-966d8.appspot.com"
}

firebase = pyrebase.initialize_app(config)
db = firebase.database()

KST = pytz.timezone('Asia/Seoul')
now = datetime.now(KST)
today = now.strftime('%Y-%m-%d')
today_display = now.strftime('%Y.%m.%d')

# 목록형 페이지에서 오늘 날짜 메뉴 찾기
url = f"https://youngpa.sen.hs.kr/66884/subMenu.do?viewType=list&searchMonth={now.strftime('%Y%m')}"
headers = {"User-Agent": "Mozilla/5.0"}

response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.text, 'html.parser')

rows = soup.find_all('tr')
found = False
for row in rows:
    cells = row.find_all('td')
    if cells and today_display in cells[0].text:
        menu_text = cells[3].text.strip()
        items = [item.strip() for item in menu_text.split(',')]
        db.child("menu").child(today).set(items)
        print(f"Firebase 저장 완료! ({today})")
        for item in items:
            print(f"  - {item}")
        found = True
        break

if not found:
    print(f"오늘({today_display}) 급식 정보 없음")