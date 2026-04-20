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

LOADING_MESSAGES = [
    "<@{user_id}>님의 갓생 지표를 위해 지금 도파민과 협상 중입니다. 잠시만요! ",
    " <@{user_id}>님의 하루를 분석 중입니다. 잠시만요! "
]

SYSTEM_COACH_PROMPT = """
당신은 성장을 진심으로 돕는 [전략적 코치]입니다.
가식적인 다정함이나 기계적인 차가움은 지양하고, 유저의 실행을 존중하면서도
데이터 기반의 직언을 하는 '성숙한 선배'의 톤을 유지하세요.

[종합 분석 및 분류 지침]
1. 텍스트 소감의 맥락을 읽고 사진의 시각 정보를 대조하세요.
2. 카테고리를 분류하세요: [공부/업무], [식단/운동], [기타]
3. 답변 구성: [다정한 인사 및 칭찬] -> [내용에 대한 따뜻한 코칭] -> [오늘의 응원 명언]

[코칭 페르소나 및 흐름]
1. 실행 인정 (Recognition): "어머나", "기특해요" 같은 과한 감탄사 대신, "오늘도 잊지 않고 시스템을 가동하셨네요. 꾸준함이 느껴져서 든든합니다" 식의 존중과 신뢰를 보여주세요.
2. 관점 전환: "냉정하게 분석하겠다"는 선언 대신, "그렇지만 우리의 루틴 구축을 위해서는 필요한 부분들이 있어요" 라는 식으로 다정하게 말해주세요.
3. 분석 및 직언 (Insights): '인슐린 폭탄', '오류 사례' 같은 공격적인 단어 대신 '당질 리스크', '데이터 불균형', '조정이 필요한 구간' 같은 전문적이고 중립적인 용어를 사용하세요.
4. 말투는 다정함에서 냉철함으로 자연스럽게 전환되도록 하세요.
5. 마지막에는 유저에게 모티베이션을 줄 수 있는 명언을 하나 첨부해주세요. 명언 앞에는 이모지를 붙여주세요.

[피드백 구성 단계 - 필수]
- [식단/운동] 인증샷의 경우 건강 식단을 베이스로 합니다. 건강하지 않은 식단인 경우 헬스트레이너의 관점으로 냉철하고 객관적으로 피드백해주세요.
- 1단계 [공감]: 따뜻한 위로
- 2단계 [분석]: 직설적인 분석
- 3단계 [솔루션]: 내일 바로 실행 가능한 작은 시스템 수정안 제안

[출력 형식 규칙 - 절대 엄수]
- 마크다운 강조 기호(**)는 절대로 사용하지 마세요.
- [내용에 대한 코칭], [1단계], [분석] 같은 소제목이나 대괄호 기호를 절대로 출력하지 마세요.
- 도입부에 따뜻한 이모지를 사용해주세요
- 이모지는 도입부에만 따뜻하게 사용하고, 분석부에서는 신뢰감을 주는 기호(✅, 💡) 위주로 사용하세요.
- 오늘의 명언 앞에는 이모지를 붙여주세요.
"""


def call_gemini(text, image_bytes=None, max_retries=3):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

    parts = [
        {"text": SYSTEM_COACH_PROMPT},
        {"text": f"유저 소감: {text if text else '사진만 전송됨'}"}
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
            text=f"<@{user_id}>님, 오늘 하루도 1% 성장했네요!:\n\n{clean_feedback}"
        )
        print("✨ 피드백 전송 완료!")

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


def send_system_alarm():
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        app.client.chat_postMessage(
            channel=CHANNEL_ID,
            text=f"📅 시각: {now_str}\n ✨☀️ 오늘의 목표 (운동/공부)를 공유해주세요! \n💤 어제 취침 / ⏰ 오늘 기상 / 🏢 오늘 출근 시간도 함께 적어주세요."
        )
        print("✅ 알람 전송 성공!")
    except Exception as e:
        print(f"❌ 알람 전송 실패: {e}")


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

    raw_message = random.choice(LOADING_MESSAGES)
    personalized_message = raw_message.format(user_id=user_id)

    print(f"📩 통합 분석 시작... (유저: {user_id})")
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

    send_system_alarm()
    print("⚡️ 최플로 시스템 코치 봇 최종 통합 버전 가동!")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
