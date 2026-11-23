"""Sanity check: confirm the OpenAI API key works. Never prints the key itself."""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Reply with exactly: Connection OK"}],
)

print(response.choices[0].message.content)
