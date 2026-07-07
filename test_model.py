import os

from dotenv import load_dotenv
from strands import Agent
from strands.models.litellm import LiteLLMModel

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")

if not api_key:
    raise ValueError("OPENROUTER_API_KEY was not found in the .env file.")

model = LiteLLMModel(
    model_id="openrouter/openrouter/free",
    client_args={
        "api_key": api_key,
        "api_base": "https://openrouter.ai/api/v1",
    },
    params={
        "max_tokens": 256,
    },
)

agent = Agent(model=model, tools=[])

response = agent("Say hello and tell me what model you are in one sentence.")
print(response)
