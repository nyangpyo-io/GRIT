import os
import requests
import random
import base64
import time
import queue
from datetime import datetime
import threading
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

if not SLACK_BOT_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN이 설정되지 않았습니다.")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
if not CHANNEL_ID:
    raise ValueError("CHANNEL_ID가 설정되지 않았습니다.")

app = App(token=SLACK_BOT_TOKEN)

retry_queue = queue.Queue()

MORNING_LOADING_MESSAGES = [
    "<@{user_id}>님의 오늘 하루를 설계 중입니다. 잠시만요! 🌅",
    "<@{user_id}>님의 갓생 플랜을 검토 중입니다. 잠시만요! ☀️"
]

MORNING_COACH_PROMPT = """
당신은 성장을 진심으로 돕는 [전략적 코치]입니다.
유저가 하루를 시작하며 올린 오늘의 목표와 수면 패턴을 보고,
따뜻하지만 실질적인 응원과 조언을 건네는 '성숙한 선배'의 톤을 유지하세요.

[입력 데이터 분석 지침]
1. 유저가 올린 오늘의 목표/계획을 파악하세요.
2. 어제 취침 시간, 오늘 기상 시간, 출근 시간이 있다면 수면 패턴을 분석하세요.
3. 답변 구성: [따뜻한 아침 인사] -> [수면 패턴 코멘트] -> [오늘 목표 응원 및 실행 팁] -> [오늘의 응원 한마디]

[코칭 페르소나 및 흐름]
1. 아침 인사: 과한 감탄사 없이 "오늘도 계획을 세우고 하루를 시작하는 모습이 든든합니다" 식의 신뢰와 존중을 보여주세요.
2. 수면 패턴: 수면이 부족하거나 불규칙하면 부드럽게 짚어주세요. 데이터가 없으면 생략하세요.
3. 목표 응원: 목표가 너무 많거나 비현실적이면 우선순위 조정을 제안하세요. 현실적이면 실행 팁을 한 가지 제안하세요.
4. 말투는 따뜻함과 실용성이 균형을 이루도록 하세요.
5. 마지막에는 오늘 하루를 힘차게 시작할 수 있는 짧은 응원 한마디를 붙여주세요. 앞에 이모지를 붙여주세요.

[출력 형식 규칙 - 절대 엄수]
- 마크다운 강조 기호(**)는 절대로 사용하지 마세요.
- [따뜻한 아침 인사], [1단계] 같은 소제목이나 대괄호 기호를 절대로 출력하지 마세요.
- 도입부에 따뜻한 이모지를 사용해주세요.
- 이모지는 도입부에만 따뜻하게 사용하고, 분석부에서는 신뢰감을 주는 기호(✅, 💡) 위주로 사용하세요.
- 오늘의 응원 한마디 앞에는 이모지를 붙여주세요.
"""


def call_gemini(text, image_bytes=None, max_retries=3):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

    parts = [
        {"text": MORNING_COACH_PROMPT},
        {"text": f"유저 메시지: {text if text else '내용 없음'}"}
    ]

    if image_bytes:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(image_bytes).decode()
            }
        })

    payload = {"contents": [{"parts": parts}]}

    for attempt in range(max_retries):
        resp = requests.post(url, json=payload)
        result = resp.json()

        if "candidates" in result:
            return result["candidates"][0]["content"]["parts"][0]["text"]

        error_code = result.get("error", {}).get("code")

        if error_code in (503, 429, 500) and attempt < max_retries - 1:
            wait_time = 5 * (attempt + 1)
            print(f"⚠️ Gemini 일시적 오류 (시도 {attempt + 1}/{max_retries}), {wait_time}초 후 재시도...")
            time.sleep(wait_time)
            continue

        if error_code in (503, 429, 500):
            raise Exception("OVERLOAD")

        raise Exception(f"OTHER:{result}")

    raise Exception("OVERLOAD")


def process_feedback(user_id, user_text, image_bytes, thread_ts, retry_count=0):
    try:
        clean_feedback = call_gemini(user_text, image_bytes).replace("**", "")
        app.client.chat_postMessage(
            channel=CHANNEL_ID,
            thread_ts=thread_ts,
            text=f"<@{user_id}>님, 오늘 하루도 응원합니다!\n\n{clean_feedback}"
        )
        print("✨ 아침 피드백 전송 완료!")

    except Exception as e:
        err_str = str(e)
        if err_str == "OVERLOAD":
            if retry_count >= 3:
                print(f"❌ 최대 재시도 초과, 포기 (유저: {user_id})")
                app.client.chat_postMessage(
                    channel=CHANNEL_ID,
                    thread_ts=thread_ts,
                    text="⚠️ 반복 오류로 인해 피드백 전송에 실패했습니다. 나중에 다시 시도해주세요."
                )
                return

            print(f"⚠️ 과부하 에러 → 큐에 추가 (유저: {user_id}, 시도: {retry_count + 1}/3)")
            app.client.chat_postMessage(
                channel=CHANNEL_ID,
                thread_ts=thread_ts,
                text="⚠️ 시스템 과부하 에러 ㅠ_ㅠ 30초 후 자동으로 다시 시도할게요!"
            )
            retry_queue.put({
                "user_id": user_id,
                "user_text": user_text,
                "image_bytes": image_bytes,
                "thread_ts": thread_ts,
                "retry_after": time.time() + 30,
                "retry_count": retry_count + 1
            })
        else:
            app.client.chat_postMessage(
                channel=CHANNEL_ID,
                thread_ts=thread_ts,
                text="⚠️ 시스템 오류가 발생했습니다 ㅠ_ㅠ"
            )
            print(f"❌ 기타 에러: {err_str}")


def retry_worker():
    print("🔄 재시도 워커 시작!")
    while True:
        try:
            item = retry_queue.get(timeout=5)

            wait = item["retry_after"] - time.time()
            if wait > 0:
                print(f"⏳ {wait:.0f}초 후 재시도 예정 (유저: {item['user_id']})")
                time.sleep(wait)

            retry_count = item.get("retry_count", 0)
            print(f"🔄 자동 재시도 중... ({retry_count}/3) (유저: {item['user_id']})")
            process_feedback(
                item["user_id"],
                item["user_text"],
                item["image_bytes"],
                item["thread_ts"],
                retry_count
            )
        except queue.Empty:
            continue
        except Exception as e:
            print(f"❌ 재시도 워커 에러: {e}")


def send_morning_alarm():
    try:
        now = datetime.now()
        date_str = now.strftime("%Y년 %m월 %d일 (%a) %H:%M")
        app.client.chat_postMessage(
            channel=CHANNEL_ID,
            text=f"📅 {date_str}\n\n☀️ 좋은 아침입니다! 오늘의 목표와 계획을 공유해주세요!\n💤 어제 취침 / ⏰ 오늘 기상 / 🏢 출근 시간도 함께 적어주세요."
        )
        print("✅ 아침 알람 전송 성공!")
    except Exception as e:
        print(f"❌ 아침 알람 전송 실패: {e}")


@app.event("message")
def handle_message_events(event, say):
    if event.get("channel") != CHANNEL_ID:
        return

    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return

    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    user_id = event['user']
    user_text = event.get('text', "").strip()
    files = event.get('files', [])

    if not user_text and not files:
        return

    raw_message = random.choice(MORNING_LOADING_MESSAGES)
    personalized_message = raw_message.format(user_id=user_id)

    print(f"📩 아침 목표 분석 시작... (유저: {user_id})")
    say(f"🧐 {personalized_message}", thread_ts=thread_ts)

    image_bytes = None
    if files:
        try:
            file_url = files[0]['url_private']
            img_resp = requests.get(file_url, headers={'Authorization': f'Bearer {SLACK_BOT_TOKEN}'})
            if img_resp.status_code == 200:
                image_bytes = img_resp.content
                print("🖼️ 이미지 데이터 병합 완료")
        except Exception as e:
            print(f"⚠️ 사진 처리 오류: {e}")

    threading.Thread(
        target=process_feedback,
        args=(user_id, user_text, image_bytes, thread_ts),
        daemon=True
    ).start()


if __name__ == "__main__":
    threading.Thread(target=retry_worker, daemon=True).start()

    send_morning_alarm()
    print("⚡️ 아침 코치 봇 가동!")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
