import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
)

try:
    models = client.models.list()
    for m in models.data:
        if "llama-3.1" in m.id.lower() or "llama" in m.id.lower():
            print(m.id)
except Exception as e:
    print("Error:", e)
