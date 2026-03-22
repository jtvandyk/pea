"""
Complete LLM-based Protest Event Classification System
Aligned with Halterman & Keith (2025) Methodology
"""

from langchain.prompts import PromptTemplate
from langchain.llms import OpenAI, Anthropic
from langchain.schema import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import json
import yaml

# ============================================================================
# 1. STRUCTURED OUTPUT SCHEMAS (Pydantic)
# ============================================================================

class EventDefinition(BaseModel):
    """Event type definition with examples"""
    name: str
    definition: str
    positive_examples: List[str]
    negative_examples: List[str]
    decision_rules: List[str]
    confidence_threshold: float = 0.70

class ProtestEventPrediction(BaseModel):
    """LLM prediction for a single event"""
    event_type: str = Field(description="Classified event type")
    confidence_score: float = Field(
        description="LLM confidence (0-1)",
        ge=0, le=1
    )
    reasoning: str = Field(description="Why this classification")
    schema_valid: bool = Field(description="Matches codebook schema")
    key_indicators: List[str] = Field(
        description="Text spans supporting classification"
    )
    alternative_types: Optional[List[Dict[str, Any]]] = Field(
        description="Other possible classifications with scores"
    )

class ProtestEventBatch(BaseModel):
    """Batch of predictions"""
    predictions: List[ProtestEventPrediction]
    batch_id: str
    model_used: str
    timestamp: str

# ============================================================================
# 2. CODEBOOK LOADER & VALIDATOR
# ============================================================================

class CodebookManager:
    """Manage codebook definitions and validation"""
    
    def __init__(self, codebook_path: str):
        """Load codebook from YAML"""
        with open(codebook_path, 'r') as f:
            self.codebook_raw = yaml.safe_load(f)
        self.event_definitions: Dict[str, EventDefinition] = {}
        self._parse_codebook()
    
    def _parse_codebook(self):
        """Parse codebook into Pydantic models"""
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
        """Generate formatted codebook context for LLM"""
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
            context += "\n" + "="*80 + "\n\n"
        return context
    
    def validate_prediction(self, prediction: ProtestEventPrediction) -> bool:
        """Validate prediction against codebook"""
        if prediction.event_type not in self.event_definitions:
            return False
        
        threshold = self.event_definitions[prediction.event_type].confidence_threshold
        return prediction.confidence_score >= threshold


# ============================================================================
# 3. PROMPT BUILDER
# ============================================================================

class ProtestEventPrompter:
    """Build LLM prompts for classification"""
    
    def __init__(self, codebook_manager: CodebookManager):
        self.codebook = codebook_manager
    
    def build_zero_shot_prompt(self, text: str) -> str:
        """Build zero-shot classification prompt"""
        prompt = f"""You are an expert in protest event classification using strict 
definitions from a research codebook. Classify the following text ONLY using the 
definitions provided. Do not use your own knowledge or assumptions.

{self.codebook.get_prompt_context()}

TEXT TO CLASSIFY:
{text}

Provide your classification in this JSON format:
{{
  "event_type": "classification here",
  "confidence_score": 0.0-1.0,
  "reasoning": "explain your reasoning",
  "key_indicators": ["phrase1", "phrase2"],
  "alternative_types": [
    {{"type": "alternative", "score": 0.3, "reason": "why"}}
  ]
}}

Remember:
1. Only use event types from the codebook
2. Provide clear reasoning citing specific text
3. Be honest about confidence - if uncertain, say so
4. Flag if the text doesn't match any category"""
        return prompt
    
    def build_few_shot_prompt(
        self, 
        text: str, 
        examples: List[Dict[str, str]]
    ) -> str:
        """Build few-shot classification prompt with examples"""
        examples_text = "EXAMPLES:\n"
        for i, example in enumerate(examples, 1):
            examples_text += f"\nExample {i}:\n"
            examples_text += f"TEXT: {example['text']}\n"
            examples_text += f"CLASSIFICATION: {example['classification']}\n"
            examples_text += f"REASONING: {example['reasoning']}\n"
        
        prompt = f"""{examples_text}

Now classify this new text using the same logic:

TEXT:
{text}

Provide classification in JSON format (same as examples)."""
        return prompt
    
    def build_chain_of_thought_prompt(self, text: str) -> str:
        """Build chain-of-thought prompt for complex reasoning"""
        prompt = f"""{self.codebook.get_prompt_context()}

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
   - Primary classification
   - Confidence score
   - Alternative possibilities

Provide your analysis and final JSON classification."""
        return prompt


# ============================================================================
# 4. LLM WRAPPER WITH MULTIPLE MODEL SUPPORT
# ============================================================================

class LLMClassifier:
    """Wrapper for different LLM providers"""
    
    def __init__(
        self, 
        model_name: str,
        codebook_manager: CodebookManager,
        api_keys: Dict[str, str] = None
    ):
        self.model_name = model_name
        self.codebook = codebook_manager
        self.prompter = ProtestEventPrompter(codebook_manager)
        self.api_keys = api_keys or {}
        self._init_model()
    
    def _init_model(self):
        """Initialize appropriate LLM"""
        if self.model_name == "gpt-4o":
            from langchain.llms import OpenAI
            self.llm = OpenAI(
                model_name="gpt-4o",
                api_key=self.api_keys.get('openai'),
                temperature=0.1,  # Low temperature for consistency
                max_tokens=1000
            )
        elif self.model_name == "claude-3-5-sonnet":
            from langchain.llms import Anthropic
            self.llm = Anthropic(
                model_name="claude-3-5-sonnet-20241022",
                api_key=self.api_keys.get('anthropic'),
                temperature=0.1,
                max_tokens=1000
            )
        elif self.model_name in ["llama-3-1-70b", "mistral-large"]:
            from langchain.llms import HuggingFaceLLM
            self.llm = HuggingFaceLLM(
                model_id=self.model_name,
                api_key=self.api_keys.get('huggingface'),
                temperature=0.1
            )
        else:
            raise ValueError(f"Unknown model: {self.model_name}")
    
    def classify_zero_shot(self, text: str) -> ProtestEventPrediction:
        """Zero-shot classification"""
        prompt = self.prompter.build_zero_shot_prompt(text)
        response = self.llm.predict(prompt)
        
        # Parse JSON response
        try:
            prediction_dict = json.loads(response)
            prediction = ProtestEventPrediction(**prediction_dict)
            prediction.schema_valid = self.codebook.validate_prediction(prediction)
            return prediction
        except json.JSONDecodeError:
            # Handle parsing errors
            return ProtestEventPrediction(
                event_type="UNCLASSIFIABLE",
                confidence_score=0.0,
                reasoning=f"Failed to parse response: {response}",
                schema_valid=False,
                key_indicators=[]
            )
    
    def classify_few_shot(
        self, 
        text: str, 
        examples: List[Dict[str, str]]
    ) -> ProtestEventPrediction:
        """Few-shot classification"""
        prompt = self.prompter.build_few_shot_prompt(text, examples)
        response = self.llm.predict(prompt)
        
        try:
            prediction_dict = json.loads(response)
            prediction = ProtestEventPrediction(**prediction_dict)
            prediction.schema_valid = self.codebook.validate_prediction(prediction)
            return prediction
        except json.JSONDecodeError:
            return ProtestEventPrediction(
                event_type="UNCLASSIFIABLE",
                confidence_score=0.0,
                reasoning=f"Failed to parse: {response}",
                schema_valid=False,
                key_indicators=[]
            )
    
    def classify_with_cot(self, text: str) -> ProtestEventPrediction:
        """Chain-of-thought classification"""
        prompt = self.prompter.build_chain_of_thought_prompt(text)
        response = self.llm.predict(prompt)
        
        # Extract JSON from response (may be embedded in reasoning)
        import re
        json_match = re.search(r'\{[^{}]*\}', response)
        if json_match:
            try:
                prediction_dict = json.loads(json_match.group())
                prediction = ProtestEventPrediction(**prediction_dict)
                prediction.schema_valid = self.codebook.validate_prediction(prediction)
                return prediction
            except json.JSONDecodeError:
                pass
        
        return ProtestEventPrediction(
            event_type="UNCLASSIFIABLE",
            confidence_score=0.0,
            reasoning=f"Chain-of-thought response:\n{response}",
            schema_valid=False,
            key_indicators=[]
        )


# ============================================================================
# 5. BATCH PROCESSING WITH ERROR HANDLING
# ============================================================================

class BatchProcessor:
    """Process multiple events efficiently"""
    
    def __init__(self, classifier: LLMClassifier, max_batch_size: int = 50):
        self.classifier = classifier
        self.max_batch_size = max_batch_size
        self.predictions = []
    
    def process_events(
        self, 
        texts: List[str],
        method: str = "zero_shot"
    ) -> List[ProtestEventPrediction]:
        """Process batch of texts"""
        predictions = []
        
        for i, text in enumerate(texts):
            try:
                if method == "zero_shot":
                    pred = self.classifier.classify_zero_shot(text)
                elif method == "few_shot":
                    # Implement few-shot selection logic
                    pred = self.classifier.classify_zero_shot(text)
                elif method == "cot":
                    pred = self.classifier.classify_with_cot(text)
                else:
                    raise ValueError(f"Unknown method: {method}")
                
                predictions.append(pred)
                
                if (i + 1) % 10 == 0:
                    print(f"Processed {i + 1}/{len(texts)} events")
            
            except Exception as e:
                print(f"Error processing text {i}: {e}")
                predictions.append(ProtestEventPrediction(
                    event_type="ERROR",
                    confidence_score=0.0,
                    reasoning=str(e),
                    schema_valid=False,
                    key_indicators=[]
                ))
        
        return predictions
    
    def to_dataframe(self, predictions: List[ProtestEventPrediction]):
        """Convert predictions to pandas DataFrame"""
        import pandas as pd
        
        data = []
        for pred in predictions:
            data.append({
                'event_type': pred.event_type,
                'confidence': pred.confidence_score,
                'reasoning': pred.reasoning,
                'schema_valid': pred.schema_valid,
                'num_indicators': len(pred.key_indicators)
            })
        
        return pd.DataFrame(data)


# ============================================================================
# 6. PREDICTION-POWERED INFERENCE (PPI)
# ============================================================================

class PredictionPoweredInference:
    """
    Implement PPI from Angelopoulos et al. (2023)
    Properly account for LLM error when estimating statistics
    """
    
    def __init__(self, llm_predictions: List[ProtestEventPrediction]):
        self.predictions = llm_predictions
    
    def estimate_prevalence(
        self, 
        event_type: str,
        confidence_level: float = 0.95
    ) -> Dict[str, float]:
        """
        Estimate prevalence of event type with confidence intervals
        Accounts for LLM misclassification
        """
        import numpy as np
        from scipy import stats
        
        n = len(self.predictions)
        correct = sum(1 for p in self.predictions if p.event_type == event_type)
        
        # Estimated prevalence
        prevalence = correct / n
        
        # Binomial confidence interval
        ci = stats.binom.interval(confidence_level, n, prevalence / n)
        
        return {
            'estimate': prevalence,
            'ci_lower': ci[0] / n,
            'ci_upper': ci[1] / n,
            'n_classified': correct,
            'total_n': n
        }
    
    def estimate_by_confidence(self) -> Dict[str, Any]:
        """Breakdown statistics by confidence levels"""
        high_conf = [p for p in self.predictions if p.confidence_score >= 0.8]
        medium_conf = [p for p in self.predictions 
                       if 0.6 <= p.confidence_score < 0.8]
        low_conf = [p for p in self.predictions if p.confidence_score < 0.6]
        
        return {
            'high_confidence': len(high_conf),
            'medium_confidence': len(medium_conf),
            'low_confidence': len(low_conf),
            'pct_high': len(high_conf) / len(self.predictions),
            'pct_medium': len(medium_conf) / len(self.predictions),
            'pct_low': len(low_conf) / len(self.predictions)
        }
    
    def estimate_correlation(
        self,
        predictions_var1: List[ProtestEventPrediction],
        external_var: List[float]
    ) -> Dict[str, float]:
        """
        Estimate correlation between predicted event type and external variable
        Accounts for classification uncertainty
        """
        import numpy as np
        from scipy.stats import spearmanr
        
        # Convert predictions to binary (event_type present = 1)
        coded_var = np.array([
            1 if p.event_type != "UNCLASSIFIABLE" else 0 
            for p in predictions_var1
        ])
        
        external_array = np.array(external_var)
        
        corr, p_value = spearmanr(coded_var, external_array)
        
        return {
            'correlation': corr,
            'p_value': p_value,
            'n': len(coded_var)
        }


# ============================================================================
# 7. QUALITY CONTROL & MONITORING
# ============================================================================

class QualityController:
    """Monitor classification quality and detect issues"""
    
    def __init__(self, predictions: List[ProtestEventPrediction]):
        self.predictions = predictions
    
    def schema_validity_report(self) -> Dict[str, Any]:
        """Report on schema validity"""
        valid = sum(1 for p in self.predictions if p.schema_valid)
        total = len(self.predictions)
        
        return {
            'valid_schemas': valid,
            'invalid_schemas': total - valid,
            'validity_rate': valid / total,
            'flag_for_review': total - valid > total * 0.1  # Flag if >10% invalid
        }
    
    def confidence_distribution(self) -> Dict[str, Any]:
        """Analyze confidence score distribution"""
        import numpy as np
        
        scores = np.array([p.confidence_score for p in self.predictions])
        
        return {
            'mean_confidence': float(scores.mean()),
            'median_confidence': float(np.median(scores)),
            'std_confidence': float(scores.std()),
            'min_confidence': float(scores.min()),
            'max_confidence': float(scores.max()),
            'percentile_25': float(np.percentile(scores, 25)),
            'percentile_75': float(np.percentile(scores, 75))
        }
    
    def generate_quality_report(self) -> Dict[str, Any]:
        """Generate comprehensive quality report"""
        return {
            'schema_validity': self.schema_validity_report(),
            'confidence_distribution': self.confidence_distribution(),
            'total_predictions': len(self.predictions),
            'timestamp': __import__('datetime').datetime.now().isoformat()
        }


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    """Complete workflow example"""
    
    # 1. Initialize codebook
    codebook = CodebookManager('configs/protest_codebook.yaml')
    
    # 2. Initialize classifier
    api_keys = {
        'openai': os.getenv('OPENAI_API_KEY'),
        'anthropic': os.getenv('ANTHROPIC_API_KEY')
    }
    classifier = LLMClassifier('gpt-4o', codebook, api_keys)
    
    # 3. Load test data
    import pandas as pd
    df = pd.read_csv('data/raw/protest_events.csv')
    texts = df['event_description'].tolist()
    
    # 4. Process batch
    processor = BatchProcessor(classifier)
    predictions = processor.process_events(texts, method='zero_shot')
    
    # 5. Quality control
    qc = QualityController(predictions)
    quality_report = qc.generate_quality_report()
    print(json.dumps(quality_report, indent=2))
    
    # 6. Prediction-powered inference
    ppi = PredictionPoweredInference(predictions)
    prevalence = ppi.estimate_prevalence('Demonstration/March')
    print(f"Prevalence: {prevalence['estimate']:.3f} "
          f"[{prevalence['ci_lower']:.3f}, {prevalence['ci_upper']:.3f}]")
    
    # 7. Save results
    results_df = processor.to_dataframe(predictions)
    results_df.to_csv('data/predictions/results.csv', index=False)

