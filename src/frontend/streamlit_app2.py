import streamlit as st
import requests
import json
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
import sseclient
import io

# 페이지 설정
st.set_page_config(
    page_title="Stockelper AI 챗봇",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 스타일링
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        border-left: 4px solid #1f77b4;
    }
    .user-message {
        background-color: #e3f2fd;
        border-left-color: #2196f3;
    }
    .assistant-message {
        background-color: #f5f5f5;
        border-left-color: #4caf50;
    }
    .progress-message {
        background-color: #fff3e0;
        border-left-color: #ff9800;
        font-style: italic;
    }
    .error-message {
        background-color: #ffebee;
        border-left-color: #f44336;
        color: #c62828;
    }
    .trading-action {
        background-color: #e8f5e8;
        border: 2px solid #4caf50;
        border-radius: 0.5rem;
        padding: 1rem;
        margin: 1rem 0;
    }
    .sidebar-info {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

class StockelperChatbot:
    def __init__(self):
        self.api_base_url = "http://localhost:21009"
        self.chat_endpoint = f"{self.api_base_url}/stock/chat"
        self.health_endpoint = f"{self.api_base_url}/health"
        
        # 세션 상태 초기화
        if "messages" not in st.session_state:
            st.session_state.messages = []
        if "thread_id" not in st.session_state:
            st.session_state.thread_id = str(uuid.uuid4())
        if "user_id" not in st.session_state:
            st.session_state.user_id = 1
        if "is_streaming" not in st.session_state:
            st.session_state.is_streaming = False
        if "last_trading_action" not in st.session_state:
            st.session_state.last_trading_action = None

    def check_server_health(self) -> bool:
        """서버 상태 확인"""
        try:
            response = requests.get(self.health_endpoint, timeout=5)
            return response.status_code == 200
        except:
            return False

    def send_chat_request(self, message: str, human_feedback: Optional[bool] = None) -> requests.Response:
        """채팅 요청 전송"""
        payload = {
            "user_id": st.session_state.user_id,
            "thread_id": st.session_state.thread_id,
            "message": message,
            "human_feedback": human_feedback
        }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        }
        
        return requests.post(
            self.chat_endpoint,
            json=payload,
            headers=headers,
            stream=True,
            timeout=300
        )

    def parse_sse_event(self, event_data: str) -> Optional[Dict[str, Any]]:
        """SSE 이벤트 데이터 파싱"""
        try:
            if event_data.strip() == "[DONE]":
                return {"type": "done"}
            return json.loads(event_data)
        except json.JSONDecodeError:
            return None

    def stream_chat_response(self, message: str, human_feedback: Optional[bool] = None):
        """스트리밍 채팅 응답 처리"""
        st.session_state.is_streaming = True
        
        # 사용자 메시지 추가
        if message and not human_feedback:
            st.session_state.messages.append({
                "role": "user",
                "content": message,
                "timestamp": datetime.now()
            })

        # 응답 컨테이너 생성
        response_container = st.empty()
        progress_container = st.empty()
        
        current_response = ""
        current_progress = ""
        
        try:
            response = self.send_chat_request(message, human_feedback)
            
            if response.status_code != 200:
                st.error(f"API 요청 실패: {response.status_code}")
                return
            
            # SSE 클라이언트로 스트리밍 처리
            client = sseclient.SSEClient(response)
            
            for event in client.events():
                if event.data:
                    parsed_data = self.parse_sse_event(event.data)
                    
                    if not parsed_data:
                        continue
                    
                    if parsed_data.get("type") == "done":
                        break
                    
                    elif parsed_data.get("type") == "progress":
                        # 진행상황 표시
                        step = parsed_data.get("step", "")
                        status = parsed_data.get("status", "")
                        current_progress = f"🔄 {step} - {status}"
                        progress_container.markdown(f'<div class="progress-message">{current_progress}</div>', unsafe_allow_html=True)
                    
                    elif parsed_data.get("type") == "delta":
                        # 토큰 단위 스트리밍
                        token = parsed_data.get("token", "")
                        current_response += token
                        response_container.markdown(f'<div class="chat-message assistant-message">{current_response}</div>', unsafe_allow_html=True)
                    
                    elif parsed_data.get("type") == "final":
                        # 최종 응답 처리
                        final_message = parsed_data.get("message", current_response)
                        subgraph = parsed_data.get("subgraph", {})
                        trading_action = parsed_data.get("trading_action")
                        error = parsed_data.get("error")
                        
                        if error:
                            st.error(f"오류 발생: {error}")
                            return
                        
                        # 최종 메시지 저장
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": final_message,
                            "timestamp": datetime.now(),
                            "subgraph": subgraph,
                            "trading_action": trading_action
                        })
                        
                        # 트레이딩 액션 저장
                        if trading_action:
                            st.session_state.last_trading_action = trading_action
                        
                        # 진행상황 메시지 제거
                        progress_container.empty()
                        
                        # 최종 응답 표시
                        response_container.markdown(f'<div class="chat-message assistant-message">{final_message}</div>', unsafe_allow_html=True)
                        
                        break
        
        except Exception as e:
            st.error(f"스트리밍 중 오류 발생: {str(e)}")
            progress_container.empty()
        
        finally:
            st.session_state.is_streaming = False

    def display_trading_action(self, trading_action: Dict[str, Any], show_buttons: bool = False, button_key_suffix: str = ""):
        """트레이딩 액션 표시"""
        if not trading_action:
            return
        
        st.markdown('<div class="trading-action">', unsafe_allow_html=True)
        st.markdown("### 📊 투자 추천 액션")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("종목코드", trading_action.get("stock_code", "N/A"))
        
        with col2:
            order_side = trading_action.get("order_side", "N/A")
            side_emoji = "📈" if order_side == "buy" else "📉"
            st.metric("주문구분", f"{side_emoji} {order_side.upper()}")
        
        with col3:
            order_type = trading_action.get("order_type", "N/A")
            st.metric("주문유형", order_type.upper())
        
        with col4:
            quantity = trading_action.get("order_quantity", 0)
            st.metric("수량", f"{quantity:,}주")
        
        if trading_action.get("order_price"):
            st.metric("주문가격", f"{trading_action['order_price']:,}원")
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # 사용자 피드백 버튼 (show_buttons가 True일 때만 표시)
        if show_buttons:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ 승인", key=f"approve_trading_{button_key_suffix}"):
                    self.handle_trading_feedback(True)
            with col2:
                if st.button("❌ 거절", key=f"reject_trading_{button_key_suffix}"):
                    self.handle_trading_feedback(False)

    def handle_trading_feedback(self, approved: bool):
        """트레이딩 피드백 처리"""
        feedback_message = "거래를 승인합니다." if approved else "거래를 거절합니다."
        st.success(f"피드백 전송: {feedback_message}")
        
        # 피드백을 서버로 전송
        self.stream_chat_response("", human_feedback=approved)
        
        # 트레이딩 액션 초기화
        st.session_state.last_trading_action = None

    def display_chat_history(self):
        """채팅 히스토리 표시"""
        for message in st.session_state.messages:
            timestamp = message["timestamp"].strftime("%H:%M:%S")
            
            if message["role"] == "user":
                st.markdown(f'''
                <div class="chat-message user-message">
                    <strong>👤 사용자</strong> <small>({timestamp})</small><br>
                    {message["content"]}
                </div>
                ''', unsafe_allow_html=True)
            
            else:  # assistant
                st.markdown(f'''
                <div class="chat-message assistant-message">
                    <strong>🤖 Stockelper AI</strong> <small>({timestamp})</small><br>
                    {message["content"]}
                </div>
                ''', unsafe_allow_html=True)
                
                # 트레이딩 액션이 있으면 표시 (히스토리에서는 버튼 없이)
                if message.get("trading_action"):
                    self.display_trading_action(message["trading_action"], show_buttons=False)

    def render_sidebar(self):
        """사이드바 렌더링"""
        with st.sidebar:
            st.markdown('<div class="sidebar-info">', unsafe_allow_html=True)
            st.markdown("### 📊 Stockelper AI")
            st.markdown("주식 투자 전문 AI 어시스턴트")
            st.markdown('</div>', unsafe_allow_html=True)
            
            # 서버 상태 확인
            server_status = self.check_server_health()
            status_color = "🟢" if server_status else "🔴"
            status_text = "온라인" if server_status else "오프라인"
            st.markdown(f"**서버 상태:** {status_color} {status_text}")
            
            # 세션 정보
            st.markdown("### 📋 세션 정보")
            st.text(f"사용자 ID: {st.session_state.user_id}")
            st.text(f"스레드 ID: {st.session_state.thread_id[:8]}...")
            st.text(f"메시지 수: {len(st.session_state.messages)}")
            
            # 새 대화 시작
            if st.button("🔄 새 대화 시작"):
                st.session_state.messages = []
                st.session_state.thread_id = str(uuid.uuid4())
                st.session_state.last_trading_action = None
                st.rerun()
            
            # 채팅 히스토리 다운로드
            if st.session_state.messages:
                chat_history = json.dumps(st.session_state.messages, default=str, ensure_ascii=False, indent=2)
                st.download_button(
                    label="💾 채팅 히스토리 다운로드",
                    data=chat_history,
                    file_name=f"chat_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json"
                )

    def run(self):
        """메인 애플리케이션 실행"""
        # 헤더
        st.markdown('<h1 class="main-header">📈 Stockelper AI 챗봇</h1>', unsafe_allow_html=True)
        
        # 사이드바 렌더링
        self.render_sidebar()
        
        # 서버 상태 확인
        if not self.check_server_health():
            st.error("🔴 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.")
            st.info("서버 주소: http://localhost:21009")
            return
        
        # 채팅 히스토리 표시
        if st.session_state.messages:
            st.markdown("### 💬 채팅 히스토리")
            self.display_chat_history()
        
        # 대기 중인 트레이딩 액션 표시
        if st.session_state.last_trading_action:
            st.markdown("### ⚠️ 대기 중인 투자 액션")
            self.display_trading_action(st.session_state.last_trading_action, show_buttons=True, button_key_suffix="pending")
        
        # 채팅 입력
        st.markdown("### 💭 메시지 입력")
        
        # 스트리밍 중일 때는 입력 비활성화
        disabled = st.session_state.is_streaming
        
        user_input = st.text_area(
            "질문을 입력하세요:",
            placeholder="예: 삼성전자에 대한 투자전략을 추천해줘",
            disabled=disabled,
            key="user_input"
        )
        
        col1, col2 = st.columns([1, 4])
        
        with col1:
            send_button = st.button(
                "📤 전송",
                disabled=disabled or not user_input.strip(),
                type="primary"
            )
        
        with col2:
            if st.session_state.is_streaming:
                st.info("🔄 응답을 생성 중입니다...")
        
        # 메시지 전송
        if send_button and user_input.strip():
            self.stream_chat_response(user_input.strip())
            st.rerun()
        
        # 예시 질문 버튼들
        if not st.session_state.messages:
            st.markdown("### 💡 예시 질문")
            example_questions = [
                "삼성전자에 대한 투자전략을 추천해줘",
                "현재 시장 상황을 분석해줘",
                "KOSPI 200 종목 중 추천 종목은?",
                "반도체 섹터 전망은 어떤가요?"
            ]
            
            cols = st.columns(2)
            for i, question in enumerate(example_questions):
                with cols[i % 2]:
                    if st.button(question, key=f"example_{i}", disabled=disabled):
                        self.stream_chat_response(question)
                        st.rerun()

# 애플리케이션 실행
if __name__ == "__main__":
    chatbot = StockelperChatbot()
    chatbot.run()