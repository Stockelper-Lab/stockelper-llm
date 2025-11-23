import json
import re
from typing import Any
import httpx
from langchain_core.output_parsers import StrOutputParser
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class JsonOutputParser(StrOutputParser):
    response_schema: object

    def __init__(self, response_schema: object):
        super().__init__(response_schema=response_schema)

    def parse(self, llm_output: str):
        text = super().parse(llm_output)

        # </think> 이전의 모든 문자열 제거
        if "</think>" in text:
            think_pattern = r".*</think>"
            text = re.sub(think_pattern, "", text, flags=re.DOTALL)

        if "```json" in text:
            pattern = r"```json(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                text = match.group(1)

        text = text.replace("\\'", "'")
        structured_output = json.loads(text)
        self.response_schema.model_validate(structured_output)
        return structured_output


class PerplexityChat(BaseChatModel):
    model: str = "perplexity/sonar"
    base_url: str = ""
    api_key: str = ""
    max_timeout: int = 60

    def _llm_type(self) -> str:
        return "perplexity-chat"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        user_text = messages[-1].content if messages else ""
        with httpx.Client(base_url=self.base_url, timeout=self.max_timeout) as client:
            resp = client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": user_text}],
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            message = AIMessage(content=content, response_metadata={"citations": citations})
            generation = ChatGeneration(message=message)
            return ChatResult(generations=[generation])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        user_text = messages[-1].content if messages else ""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.max_timeout) as client:
            resp = await client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": user_text}],
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            message = AIMessage(
                content=content,
                additional_kwargs={},
                response_metadata={
                    "citations": citations,
                    "model_name": self.model,
                },
                usage_metadata={
                    "input_tokens": data["usage"]["prompt_tokens"],
                    "output_tokens": data["usage"]["completion_tokens"],
                    "total_tokens": data["usage"]["total_tokens"],
                },
            )
            generation = ChatGeneration(message=message)
            return ChatResult(generations=[generation])