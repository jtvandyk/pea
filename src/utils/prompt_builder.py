"""
Prompt builder for protest event classification.
Supports zero-shot, few-shot, and chain-of-thought prompting strategies.
"""

from typing import List, Dict
from src.utils.codebook_manager import CodebookManager


class ProtestEventPrompter:
    """Build LLM prompts for protest event classification."""

    def __init__(self, codebook_manager: CodebookManager):
        self.codebook = codebook_manager

    def build_zero_shot_prompt(self, text: str) -> str:
        valid_types = list(self.codebook.event_definitions.keys())
        valid_types_str = ", ".join(f'"{t}"' for t in valid_types)
        return f"""You are an expert in protest event classification using strict \
definitions from a research codebook. Classify the following text ONLY using the \
definitions provided. Do not use your own knowledge or assumptions.

{self.codebook.get_prompt_context()}

TEXT TO CLASSIFY:
{text}

IMPORTANT: The "event_type" field MUST be exactly one of these values (copy exactly):
{valid_types_str}

If the text does not match any category, use "UNCLASSIFIABLE".

Provide your classification as a JSON object (no other text, just JSON):
{{
  "event_type": "exact_type_key_here",
  "confidence_score": 0.0,
  "reasoning": "explain your reasoning",
  "key_indicators": ["phrase1", "phrase2"],
  "alternative_types": []
}}"""

    def build_few_shot_prompt(self, text: str, examples: List[Dict[str, str]]) -> str:
        examples_text = "EXAMPLES:\n"
        for i, example in enumerate(examples, 1):
            examples_text += f"\nExample {i}:\n"
            examples_text += f"TEXT: {example['text']}\n"
            examples_text += f"CLASSIFICATION: {example['classification']}\n"
            examples_text += f"REASONING: {example['reasoning']}\n"

        return f"""{examples_text}

Now classify this new text using the same logic:

TEXT:
{text}

Provide classification in JSON format (same as examples)."""

    def build_chain_of_thought_prompt(self, text: str) -> str:
        valid_types = list(self.codebook.event_definitions.keys())
        valid_types_str = ", ".join(f'"{t}"' for t in valid_types)
        return f"""{self.codebook.get_prompt_context()}

TEXT TO CLASSIFY:
{text}

Think through this step-by-step:

1. IDENTIFY KEY ELEMENTS:
   - Who is acting? (individuals, groups, organizations)
   - What are they doing? (activities, tactics)
   - Why are they doing it? (goals, demands)
   - Where/When? (location, duration, timing)

2. MATCH TO DEFINITIONS:
   - Which event types could this match?
   - Which key indicators are present?
   - Which are absent?

3. APPLY DECISION RULES:
   - Check edge cases
   - Resolve ambiguities
   - Consider alternatives

4. MAKE CLASSIFICATION:
   IMPORTANT: "event_type" MUST be exactly one of: {valid_types_str}
   End your response with ONLY this JSON object:
   {{
     "event_type": "exact_type_key_here",
     "confidence_score": 0.0,
     "reasoning": "your reasoning",
     "key_indicators": ["phrase1", "phrase2"],
     "alternative_types": []
   }}"""
