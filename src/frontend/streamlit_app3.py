"""
Stockelper Streamlit Chatbot (SSE delta streaming)
참조: src/routers/base.py, src/routers/models.py, src/routers/stock.py, src/main.py

기능
- /health 헬스체크
- /stock/chat SSE 스트리밍 수신
  - type=progress: 단계/상태 표시
  - type=delta: 토큰 단위(문자 단위) 스트리밍 → 실시간 메시지 렌더
  - type=final: 최종 메시지 + trading_action 수신 → 저장/표시
  - [DONE]: 스트림 종료
"""

import json
import time
import requests
import streamlit as st
from uuid import uuid4
from typing import Dict, Any, Generator, Tuple, Optional


DEFAULT_SERVER_URL = "http://localhost:21009"


def sse_chat(server_url: str, payload: Dict[str, Any]) -> Generator[Tuple[str, Optional[str], Optional[Dict]], None, None]:
    """/stock/chat SSE 스트리밍 호출 (동기)
    Yields: (event_type, content, extra)
      - ("progress", step, status)
      - ("delta", token, None)
      - ("final", message, full_json)
      - ("done", None, None)
      - ("error", message, None)
    """
    try:
        # 사전 헬스체크(실패해도 본요청 시도)
        try:
            requests.get(f"{server_url}/health", timeout=10)
        except Exception:
            pass

        with requests.post(
            f"{server_url}/stock/chat",
            json=payload,
            headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json; charset=utf-8",
            },
            stream=True,
            timeout=(10, 300),  # (connect, read)
        ) as resp:
            resp.raise_for_status()

            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                # SSE 표준 접두사 처리
                if line.startswith("data: "):
                    data_content = line[6:]
                    if data_content == "[DONE]":
                        yield ("done", None, None)
                        break
                    try:
                        obj = json.loads(data_content)
                    except json.JSONDecodeError:
                        # 비표준 라인은 건너뜀
                        continue

                    # progress 이벤트
                    if obj.get("type") == "progress" or (obj.get("step") and obj.get("status")):
                        yield ("progress", obj.get("step"), obj.get("status"))
                        continue

                    # delta 토큰
                    if obj.get("type") == "delta":
                        yield ("delta", obj.get("token", ""), None)
                        continue

                    # final
                    if obj.get("type") == "final":
                        yield ("final", obj.get("message"), obj)
                        continue
                # 기타 라인은 무시
    except requests.exceptions.ReadTimeout as e:
        yield ("error", f"응답 읽기 시간이 초과되었습니다: {e}", None)
    except requests.exceptions.ConnectTimeout as e:
        yield ("error", f"서버 연결 시간이 초과되었습니다: {e}", None)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        yield ("error", f"서버 오류가 발생했습니다: {status}", None)
    except requests.exceptions.ConnectionError as e:
        yield ("error", f"서버에 연결할 수 없습니다: {e}", None)
    except Exception as e:
        yield ("error", f"API 호출 중 오류가 발생했습니다: {e}", None)


def setup_page():
    st.set_page_config(page_title="Stockelper Chatbot", page_icon="📈", layout="wide")
    st.sidebar.title("📈 Stockelper")
    st.sidebar.caption("SSE delta streaming chatbot")

    # 서버 URL 설정
    server_url = st.sidebar.text_input("LLM Server URL", value=DEFAULT_SERVER_URL)
    if "server_url" not in st.session_state:
        st.session_state.server_url = server_url
    elif st.session_state.server_url != server_url:
        st.session_state.server_url = server_url

    # 헬스체크 버튼
    if st.sidebar.button("Check Health"):
        try:
            r = requests.get(f"{st.session_state.server_url}/health", timeout=10)
            st.sidebar.success(f"Health: {r.status_code} {r.text}")
        except Exception as e:
            st.sidebar.error(f"Health check failed: {e}")

    # 초기화 버튼
    if st.sidebar.button("Clear Session"):
        clear_session()
        st.rerun()


def init_session():
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"}
        ]
    if "pending_trading_action" not in st.session_state:
        st.session_state.pending_trading_action = None


def clear_session():
    st.session_state.session_id = str(uuid4())
    st.session_state.messages = [
        {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"}
    ]
    st.session_state.pending_trading_action = None


def display_messages():
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"], unsafe_allow_html=True)


def get_step_icon(step: str) -> str:
    if not step:
        return "⚙️"
    if "Agent" in step:
        return "🤖"
    if any(t in step for t in ["search", "analysis", "predict", "analize", "analysis_stock", "korean_stock_chart_analysis"]):
        return "🔧"
    if step == "supervisor":
        return "👨‍💼"
    return "⚙️"


def chat_once(query: str):
    # 사용자 메시지 반영
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    # SSE 호출 및 실시간 렌더링
    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        message_placeholder = st.empty()
        generated_text = ""
        running: Dict[str, Dict] = {}

        payload = {
            "user_id": 1,
            "thread_id": st.session_state.session_id,
            "message": query,
        }

        with st.spinner("분석 중..."):
            for etype, content, extra in sse_chat(st.session_state.server_url, payload):
                if etype == "progress":
                    step, status = content, extra
                    # running table 업데이트
                    icon = get_step_icon(step)
                    if status == "start":
                        running[step] = {"icon": icon, "status": "진행중"}
                    elif status == "end":
                        running.pop(step, None)
                    # 표시
                    if running:
                        lines = [f"{info['icon']} **{s}** 🔄 *{info['status']}*" for s, info in running.items()]
                        status_placeholder.markdown("\n\n".join(lines))
                    else:
                        status_placeholder.empty()

                elif etype == "delta":
                    token = content or ""
                    generated_text += token
                    message_placeholder.markdown(generated_text, unsafe_allow_html=True)

                elif etype == "final":
                    final_message = content or generated_text
                    status_placeholder.empty()
                    message_placeholder.markdown(final_message, unsafe_allow_html=True)
                    st.session_state.messages.append({"role": "assistant", "content": final_message})
                    # trading_action 저장
                    if extra and extra.get("trading_action"):
                        st.session_state.pending_trading_action = extra["trading_action"]
                    break

                elif etype == "error":
                    status_placeholder.empty()
                    message_placeholder.error(content)
                    break

                elif etype == "done":
                    # 종료 신호 (final 전에 오면 누적 텍스트를 최종으로 사용)
                    if generated_text:
                        message_placeholder.markdown(generated_text, unsafe_allow_html=True)
                        st.session_state.messages.append({"role": "assistant", "content": generated_text})
                    break


def handle_trading_confirmation():
    action = st.session_state.pending_trading_action
    if not action:
        return

    with st.chat_message("assistant"):
        st.write("💡 거래 제안이 들어왔습니다:")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**종목코드**: {action.get('stock_code', 'N/A')}")
            st.write(f"**거래유형**: {action.get('order_side', 'N/A')}")
        with col2:
            st.write(f"**주문타입**: {action.get('order_type', 'N/A')}")
            st.write(f"**수량**: {action.get('order_quantity', 'N/A')}")
        if action.get('order_price') is not None:
            st.write(f"**가격**: {action.get('order_price')}")

        ok, cancel = st.columns(2)
        with ok:
            if st.button("✅ 예(승인)"):
                process_feedback(True)
                return
        with cancel:
            if st.button("❌ 아니오(거부)"):
                process_feedback(False)
                return


def process_feedback(feedback: bool):
    # 확인 후 pending 액션 제거
    st.session_state.pending_trading_action = None

    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        message_placeholder = st.empty()
        generated_text = ""
        running: Dict[str, Dict] = {}

        payload = {
            "user_id": 1,
            "thread_id": st.session_state.session_id,
            "message": st.session_state.messages[-1]["content"],  # 마지막 어시스턴트 메시지
            "human_feedback": feedback,
        }

        with st.spinner("거래 처리 중..."):
            for etype, content, extra in sse_chat(st.session_state.server_url, payload):
                if etype == "progress":
                    step, status = content, extra
                    icon = get_step_icon(step)
                    if status == "start":
                        running[step] = {"icon": icon, "status": "처리중"}
                    elif status == "end":
                        running.pop(step, None)
                    if running:
                        lines = [f"{info['icon']} **{s}** 🔄 *{info['status']}*" for s, info in running.items()]
                        status_placeholder.markdown("\n\n".join(lines))
                    else:
                        status_placeholder.empty()

                elif etype == "delta":
                    token = content or ""
                    generated_text += token
                    message_placeholder.markdown(generated_text, unsafe_allow_html=True)

                elif etype == "final":
                    final_message = content or generated_text
                    status_placeholder.empty()
                    message_placeholder.markdown(final_message, unsafe_allow_html=True)
                    st.session_state.messages.append({"role": "assistant", "content": final_message})
                    break

                elif etype == "error":
                    status_placeholder.empty()
                    message_placeholder.error(content)
                    break

                elif etype == "done":
                    if generated_text:
                        message_placeholder.markdown(generated_text, unsafe_allow_html=True)
                        st.session_state.messages.append({"role": "assistant", "content": generated_text})
                    break


def main():
    setup_page()
    init_session()
    st.title("Stockelper 챗봇 (SSE delta streaming)")

    # 기존 대화 표시
    display_messages()

    # 입력창
    if q := st.chat_input("메시지를 입력하세요…"):
        chat_once(q)
        st.rerun()

    # 거래 확인 섹션
    handle_trading_confirmation()


if __name__ == "__main__":
    main()
