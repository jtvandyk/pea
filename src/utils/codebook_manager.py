"""
Codebook loader and validator.
Manages YAML codebook definitions and validates LLM predictions against them.
"""

import yaml
from typing import Dict
from src.models.schemas import EventDefinition, ProtestEventPrediction


class CodebookManager:
    """Load, manage, and validate against codebook definitions."""

    def __init__(self, codebook_path: str):
        with open(codebook_path, 'r') as f:
            self.codebook_raw = yaml.safe_load(f)
        self.event_definitions: Dict[str, EventDefinition] = {}
        self._parse_codebook()

    def _parse_codebook(self):
        for event_type, details in self.codebook_raw['event_types'].items():
            self.event_definitions[event_type] = EventDefinition(
                name=event_type,
                definition=details['definition'],
                positive_examples=details.get('positive_examples', []),
                negative_examples=details.get('negative_examples', []),
                decision_rules=details.get('decision_rules', []),
                confidence_threshold=details.get('confidence_threshold', 0.70)
            )

    def get_prompt_context(self) -> str:
        """Return formatted codebook string for inclusion in LLM prompts."""
        context = "EVENT TYPE DEFINITIONS:\n\n"
        for event_type, definition in self.event_definitions.items():
            context += f"TYPE: {event_type}\n"
            context += f"DEFINITION: {definition.definition}\n"
            context += "POSITIVE EXAMPLES:\n"
            for ex in definition.positive_examples:
                context += f"  - {ex}\n"
            context += "NEGATIVE EXAMPLES:\n"
            for ex in definition.negative_examples:
                context += f"  - {ex}\n"
            context += "DECISION RULES:\n"
            for rule in definition.decision_rules:
                context += f"  - {rule}\n"
            context += "\n" + "=" * 80 + "\n\n"
        return context

    def validate_prediction(self, prediction: ProtestEventPrediction) -> bool:
        """Return True if prediction matches a known event type above its confidence threshold."""
        if prediction.event_type not in self.event_definitions:
            return False
        threshold = self.event_definitions[prediction.event_type].confidence_threshold
        return prediction.confidence_score >= threshold
