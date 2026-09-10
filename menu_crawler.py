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
today = datetime.now(KST).strftime('%Y-%m-%d')

# 메인 페이지에서 크롤링
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
        
        db.child("menu").child(today).set(items)
        print(f"Firebase 저장 완료! ({today})")
        for item in items:
            print(f"  - {item}")
        break