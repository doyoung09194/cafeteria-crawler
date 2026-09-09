import serial
import csv
import os
from datetime import datetime

PORT = 'COM6'
BAUD = 115200
FILE = 'cafeteria_data.csv'

if not os.path.exists(FILE):
    with open(FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['날짜', '시간', '구역', '거리(cm)', '혼잡여부'])

print("데이터 수집 시작! 종료하려면 Ctrl+C")

ser = serial.Serial(PORT, BAUD)

try:
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        print(line)  # 디버그용
        if '구역 |' in line and '거리:' in line and '혼잡:' in line:
            try:
                now = datetime.now()
                zone = 'A' if 'A구역' in line else 'B'
                distance = line.split('거리:')[1].split('cm')[0].strip()
                crowded = line.split('혼잡:')[1].strip()
                with open(FILE, 'a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        now.strftime('%Y-%m-%d'),
                        now.strftime('%H:%M:%S'),
                        zone,
                        distance,
                        crowded
                    ])
                print(f"저장됨 | {zone}구역 | 거리: {distance}cm | 혼잡: {crowded}")
            except:
                pass
except KeyboardInterrupt:
    print("수집 종료!")
    ser.close()