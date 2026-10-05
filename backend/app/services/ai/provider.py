import os
from google import genai
from pydantic import BaseModel, ValidationError
import json

class AIProvider:
    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY")
        self.model_name = os.getenv("AI_MODEL", "gemini-2.5-flash")
        
    def analyze_requirement(self, prompt: str, schema_class: type[BaseModel]) -> BaseModel:
        if not self.api_key:
            raise ValueError("AI_API_KEY is missing. Please configure it in .env")

        client = genai.Client(api_key=self.api_key)
        try:
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": schema_class,
                },
            )
            
            raw_text = response.text
            # Use Pydantic to validate and parse
            return schema_class.model_validate_json(raw_text)
        except Exception as e:
            raise RuntimeError(f"AI Provider failed: {str(e)}")
