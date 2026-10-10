import json
import os

from google import genai
from pydantic import BaseModel


class AIProvider:
    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY")
        self.model_name = os.getenv("AI_MODEL", "gemini-2.5-flash")

    @staticmethod
    def _extract_json(text: str) -> str:
        if not text:
            return text

        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            match = str(stripped).strip("`")
            if match.lower().startswith("json"):
                match = match[4:].lstrip()
            return match.strip()

        return stripped

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

            raw_text = self._extract_json(response.text)
            return schema_class.model_validate_json(raw_text)
        except Exception as e:
            raise RuntimeError(f"AI Provider failed: {str(e)}")

    def generate_code(self, prompt: str, schema_class: type[BaseModel]) -> BaseModel:
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
            return schema_class.model_validate_json(self._extract_json(response.text))
        except Exception as e:
            raise RuntimeError(f"AI Provider failed: {str(e)}")

    def generate_test_cases(self, prompt: str, schema_class: type[BaseModel]) -> BaseModel:
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

            raw_text = self._extract_json(response.text)
            json.loads(raw_text)
            return schema_class.model_validate_json(raw_text)
        except Exception as e:
            raise RuntimeError(f"AI Provider failed: {str(e)}")
