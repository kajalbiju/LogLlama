import os

import logllama
from anthropic import Anthropic
from google import genai
from openai import OpenAI

logllama.init(
    api_key=os.environ["LOGLLAMA_API_KEY"],
    endpoint="http://127.0.0.1:8000",
    service_name="real-token-test",
    environment="local",
)

# A provider runs only when its key is set, so you can test one provider now and add the others later.
prompt = "Reply with one word: hello"
ran = []

with logllama.context(route="/real-test", conversation_id="real-1"):
    if os.getenv("OPENAI_API_KEY"):
        openai_client = logllama.wrap_openai(OpenAI())
        openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
        )
        ran.append("openai")

    if os.getenv("ANTHROPIC_API_KEY"):
        anthropic_client = logllama.wrap_anthropic(Anthropic())
        anthropic_client.messages.create(
            model="claude-haiku-5-5",
            max_tokens=5,
            messages=[{"role": "user", "content": prompt}],
        )
        ran.append("anthropic")

    if os.getenv("GEMINI_API_KEY"):
        gemini_client = logllama.wrap_gemini(genai.Client())
        gemini_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        ran.append("gemini")

logllama.flush()
stats = logllama.transport_stats()
print(f"ran: {', '.join(ran) or 'nothing (no provider keys set)'}")
print(f"events: sent={stats['sent']} failed={stats['failed']} dropped={stats['dropped']}")
