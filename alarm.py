import os
import sys
from pathlib import Path
from slack_sdk import WebClient
from google import genai
from dotenv import load_dotenv
import re
from datetime import datetime
import pytz


load_dotenv(override=True)



# 2. 환경 변수 및 설정
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 3. 클라이언트 초기화
# API 키가 없는 경우를 대비한 예외 처리
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY가 설정되지 않았습니다. .env 파일이나 환경 변수를 확인하세요.")
    sys.exit(1)

client_ai = genai.Client(api_key=GEMINI_API_KEY)
client_slack = WebClient(token=SLACK_BOT_TOKEN)

def get_current_time_kst():
    """현재 한국 시간(KST)을 반환합니다."""
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    return now.strftime("%Y년 %m월 %d일 (%a) %H:%M")

def get_motivation(job_type):
    base_instruction = (
        "너는 센스 넘치는 스타트업 게임 회사 마케터야. "
        "오글거리는 자기계발서 문구, '자네', '하라' 같은 말투는 절대 쓰지 마. "
        "동료에게 말하듯 '해요'체나 '죠'체를 사용해줘. "
        "중요: 별표(**)나 큰따옴표 같은 마킹 기호를 절대로 쓰지 말고 순수 텍스트만 출력해."
        "별표(*), 별표(**), 별표(***), 괄호(), 해설, 이유 등 부연설명은 절대로 넣지 않는다."
        
    )

    prompts = {
        "morning": " 아침 10시야. 스터디원들에게 과하지 않게 끈기를 북돋아주는 응원 1줄 ",
        "evening": "오늘 하루 목표를 완수한 사람들에게 성취감과 꾸준함의 가치를 전하는 따뜻한 격려 멘트 1줄",
        "weekly": "새로운 한 주를 시작하며 장기적인 성장을 꿈꾸게 하는 강력한 동기부여 멘트 1줄",
        "monthly": "새로운 달을 맞이하며 어제보다 나은 내일을 다짐하게 하는 영감을 주는 문구 1줄",
        "tuesday": "함께 모여 공부하는 오프라인 모임의 즐거움과 시너지를 강조하는 밝은 멘트 1줄"
    }
    
    try:
        # 최신 google-genai SDK 방식
        response = client_ai.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompts.get(job_type, "오늘도 당신의 꾸준함을 응원합니다! 🔥")
        )
        # [핵심] 정규표현식으로 모든 별표(*)를 강제로 제거합니다.
        raw_text = response.text.strip()
        cleaned_text = re.sub(r'\*', '', raw_text) 
        
        # 혹시 따옴표로 감싸는 버릇이 있다면 그것도 제거
        cleaned_text = cleaned_text.replace('"', '').replace('\"', '')
        return cleaned_text
    except Exception as e:
        print(f"AI 멘트 생성 실패: {e}")
        return "작은 습관이 모여 위대한 결과를 만듭니다. 오늘도 화이팅! 🚀"

def send_alarm(job_type):
    """지정된 타입에 맞춰 슬랙 메시지를 전송합니다."""
    quote = get_motivation(job_type)
    current_time = get_current_time_kst()
    
    messages = {
        "morning": f"🕐 {current_time}\n\n✨ {quote}\n\n☀️ 오늘의 목표 (운동/공부)를 공유해주세요!\n💤 어제 취침 / ⏰ 오늘 기상 / 🏢 오늘 출근 시간도 함께 적어주세요.",
        "evening": f"🕐 {current_time}\n\n🌙 {quote}\n\n📸 오늘 하루는 어떠셨나요? 댓글로 사진과 오늘 하루 소감을 남겨주세요.",
        "weekly": f"🕐 {current_time}\n\n📅 {quote}\n\n이번 주 주간 단위 목표는 무엇인가요?",
        "monthly": f"🕐 {current_time}\n\n🗓️ {quote}\n\n새로운 달의 월간 단위 목표를 설정해봅시다!",
        "tuesday": f"🕐 {current_time}\n\n📢 오늘은 오프라인 스터디 모임!\n오후 7시에 모여서 함께 성장해요! 🚀"
    }
    
    try:
        client_slack.chat_postMessage(channel=SLACK_CHANNEL_ID, text=messages.get(job_type, "알림이 도착했습니다."))
        print(f"{job_type} 알림 전송 완료! ({current_time})")
    except Exception as e:
        print(f"슬랙 메시지 전송 실패: {e}")

if __name__ == "__main__":
    # 터미널에서 입력받은 인자값에 따라 알림 종류 결정 (기본값: morning)
    job = sys.argv[1] if len(sys.argv) > 1 else "morning"
    send_alarm(job)
