"""
LLM classifier for protest events.
Supports local Llama (via Ollama) and can be extended to other providers.
Model initialisation is deferred until the LLM setup stage.
"""

import json
from typing import List, Dict, Optional

from src.models.schemas import ProtestEventPrediction
from src.utils.codebook_manager import CodebookManager
from src.utils.prompt_builder import ProtestEventPrompter


def _unclassifiable(reason: str) -> ProtestEventPrediction:
    return ProtestEventPrediction(
        event_type="UNCLASSIFIABLE",
        confidence_score=0.0,
        reasoning=reason,
        schema_valid=False,
        key_indicators=[],
    )


class LLMClassifier:
    """
    Classify protest events using a language model.

    Supported model_name values:
      - "llama"  : local Ollama endpoint (default, no API key required)

    Additional providers (OpenAI, Anthropic) can be wired in later by
    extending _init_model().
    """

    def __init__(
        self,
        model_name: str,
        codebook_manager: CodebookManager,
        api_keys: Optional[Dict[str, str]] = None,
        ollama_model: str = "llama2",
        ollama_base_url: str = "http://localhost:11434",
    ):
        self.model_name = model_name
        self.codebook = codebook_manager
        self.prompter = ProtestEventPrompter(codebook_manager)
        self.api_keys = api_keys or {}
        self.ollama_model = ollama_model
        self.ollama_base_url = ollama_base_url
        self.llm = self._init_model()

    def _init_model(self):
        """Return a callable that accepts a prompt string and returns a string."""
        if self.model_name == "llama":
            return self._call_ollama
        if self.model_name in ("claude", "openai", "azure"):
            return self._call_cloud
        raise ValueError(
            f"Unknown model '{self.model_name}'. "
            "Supported: 'claude', 'openai', 'azure', 'llama'."
        )

    def _call_ollama(self, prompt: str) -> str:
        """Send prompt to local Ollama server via the ollama Python client."""
        from ollama import Client

        client = Client(host=self.ollama_base_url)
        response = client.generate(
            model=self.ollama_model,
            prompt=prompt,
            stream=False,
        )
        return response["response"]

    def _call_cloud(self, prompt: str) -> str:
        """Send prompt to a cloud LLM (claude/openai/azure) via extractor._call_llm."""
        from src.acquisition.extractor import _call_llm

        result = _call_llm(
            system="You are an expert protest event classifier. Return only valid JSON.",
            user=prompt,
            model=self.ollama_model,  # ollama_model field reused as model/deployment name
            api_key=self.api_keys.get(self.model_name, ""),
            provider=self.model_name,
        )
        return result or ""

    def _parse_response(self, response: str) -> dict:
        """Extract the outermost JSON object from an LLM response string."""
        # Try direct parse first (clean response)
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            pass
        # Find the last { ... } block (handles preamble/postamble text)
        start = response.rfind("{")
        end = response.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(response[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"No JSON found in response: {response[:200]}")

    def _to_prediction(
        self, response: str, _retry: bool = True
    ) -> ProtestEventPrediction:
        try:
            data = self._parse_response(response)
            pred = ProtestEventPrediction(**data)
            pred.schema_valid = self.codebook.validate_prediction(pred)
            return pred
        except Exception as e:
            if _retry:
                # One retry — LLMs occasionally add unexpected preamble
                retry_response = self.llm(
                    "Return ONLY the JSON object from your previous response, "
                    "with no other text:\n\n" + response
                )
                return self._to_prediction(retry_response, _retry=False)
            return _unclassifiable(f"Parse error: {e} | Raw: {response[:300]}")

    def classify_zero_shot(self, text: str) -> ProtestEventPrediction:
        prompt = self.prompter.build_zero_shot_prompt(text)
        return self._to_prediction(self.llm(prompt))

    def classify_few_shot(
        self, text: str, examples: List[Dict[str, str]]
    ) -> ProtestEventPrediction:
        prompt = self.prompter.build_few_shot_prompt(text, examples)
        return self._to_prediction(self.llm(prompt))

    def classify_with_cot(self, text: str) -> ProtestEventPrediction:
        prompt = self.prompter.build_chain_of_thought_prompt(text)
        return self._to_prediction(self.llm(prompt))
