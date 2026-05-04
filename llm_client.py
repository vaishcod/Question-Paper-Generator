import os
from openai import OpenAI
import requests

PROVIDER = "OPENROUTER"

def get_client(api_key: str) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1"
    )

def get_available_models(api_key: str) -> list:
    if not api_key:
        return []
    try:
        req = requests.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        if req.status_code == 200:
            return req.json().get("data", [])
    except Exception as e:
        print(f"Error fetching models: {e}")
    return []

def generate_text(prompt: str, api_key: str, model_id: str = "mistralai/mistral-7b-instruct") -> str:
    if not api_key:
        raise ValueError("API Key is missing. Please configure your OpenRouter API Key in settings.")
        
    client = get_client(api_key)
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    return response.choices[0].message.content
