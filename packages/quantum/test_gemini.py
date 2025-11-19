from google import genai
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Create client
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

# Test call
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Explain portfolio diversification in one sentence"
)

print("✅ Gemini is working!")
print(f"Response: {response.text}")
