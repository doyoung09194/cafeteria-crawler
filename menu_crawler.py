import requests
from bs4 import BeautifulSoup
import pyrebase
from datetime import datetime
import os
import pytz

# Firebase 설정
config = {
    "apiKey": "AIzaSyALBfzc6-eYDiLqNKIJ6FxueVd_eS0B2DY",  # admin.js의 API_KEY와 같은 값 (따옴표는 남기세요)
    "authDomain": "cafeteria-system-966d8.firebaseapp.com",
    "databaseURL": os.environ.get("FIREBASE_DATABASE_URL"),
    "storageBucket": "cafeteria-system-966d8.appspot.com"
}

firebase = pyrebase.initialize_app(config)
db = firebase.database()

# 관리자 계정으로 로그인 (menu는 관리자만 쓸 수 있어요)
auth = firebase.auth()
user = auth.sign_in_with_email_and_password(
    os.environ["ADMIN_EMAIL"],
    os.environ["ADMIN_PW"]
)
token = user["idToken"]

# 한국 시간
KST = pytz.timezone('Asia/Seoul')
today = datetime.now(KST).strftime('%Y-%m-%d')

# 크롤링
url = "https://youngpa.sen.hs.kr/"
headers = {"User-Agent": "Mozilla/5.0"}

response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.text, 'html.parser')

links = soup.find_all('a', href=lambda x: x and '66884' in str(x))
for link in links:
    text = link.text.strip()
    if len(text) > 20:
        menu = text.split('(')[0].strip()
        items = [item.strip() for item in menu.split(',')]

        db.child("menu").child(today).set(items, token)
        print(f"Firebase 저장 완료! ({today})")
        for item in items:
            print(f"  - {item}")
        break
