"""Sanity check: confirm the Gemini API key works."""
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Reply with exactly: Connection OK",
)

print(response.text)
