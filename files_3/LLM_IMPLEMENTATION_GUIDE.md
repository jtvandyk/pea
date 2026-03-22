# LLM-Powered Protest Event Classification: Complete Implementation Guide
## Aligned with Halterman & Keith (2025) Methodology

---

## TABLE OF CONTENTS
1. [Theoretical Foundations](#theoretical-foundations)
2. [Codebook Preparation](#codebook-preparation)
3. [Tech Stack Setup](#tech-stack-setup)
4. [Implementation Workflow](#implementation-workflow)
5. [Model Selection Guide](#model-selection-guide)
6. [Prompt Engineering](#prompt-engineering)
7. [Quality Control](#quality-control)
8. [Prediction-Powered Inference](#prediction-powered-inference)
9. [Troubleshooting & Best Practices](#troubleshooting--best-practices)

---

## THEORETICAL FOUNDATIONS

### Why Your Meta Codebook Matters (Halterman & Keith, 2025)

The paper identifies a critical gap in LLM-era computational social science:

**Problem**: Researchers skip the conceptualization step when using LLMs
- LLMs can "fail silently" by generating plausible labels without clear definitions
- Vague definitions → biased predictions → biased downstream statistics
- Post-hoc bias correction CANNOT fix conceptualization errors

**Solution**: Explicit, detailed codebook as first-order requirement
- **Type I (Surface form)**: "Is this a protest?"
- **Type II (Dictionary)**: Definitions from existing literature
- **Type III (Stipulative)**: Precise operational definitions for YOUR research

YOUR META CODEBOOK = Type II (excellent reference point)
YOUR LLM CODEBOOK = Type III (what you need to create)

### The Three-Step Workflow

```
Background Concept     Codebook Definition      LLM Prompting
(e.g., "protest")  →  (What exactly?)      →  (How to ask LLM?)
                                               ↓
                                         LLM Predictions
                                               ↓
                                    Prediction-Powered Inference
                                    (Account for LLM errors)
                                               ↓
                                    Valid Downstream Statistics
```

---

## CODEBOOK PREPARATION

### Step 1: Identify Core Event Types

From your meta codebook, select 6-12 PRIMARY event types (avoid overload):

```yaml
MINIMAL SET (6 types):
- Demonstration/March (peaceful, ≥2 people, public demand)
- Strike (organized work stoppage)
- Riot (violent, destructive)
- Occupation (sit-in, property seizure)
- Petition/Signature Drive (formal demand collection)
- Confrontation (direct action, non-violent confrontation)

EXTENDED SET (12 types):
[Add more specific categories based on your research needs]
```

### Step 2: Write Type III Stipulative Definitions

For EACH type, document:

```yaml
event_type_name:
  
  definition: |
    [Clear, operationalized definition in 2-3 sentences]
    [Include minimum thresholds (# people, duration)]
    [Specify geographic component (physical space)]
    [Note temporal component (when event starts/ends)]
  
  positive_examples:
    - "Exact quote or paraphrase from text showing this event"
    - "Another clear example with specific details"
    - "Third example showing borderline but clearly this type"
  
  negative_examples:
    - "Example of what this is NOT - explain why"
    - "Common confusion - explain difference"
    - "Overlapping category - explain distinction"
  
  decision_rules:
    - "IF [condition A], THEN classify as [type]"
    - "IF uncertain between Type X and Type Y, prioritize Type X because..."
    - "Edge case: If [unusual situation], then..."
  
  confidence_threshold: 0.70  # Min confidence score needed
  
  codebook_source_datasets:
    - "ACLED Event Type: [X]"
    - "PolDem Classification: [Y]"
    - "FARPE Precedent: [Z]"
```

### Step 3: Create Negative Cases Guide

Document what DOESN'T count:

```yaml
non_events:
  - "Violence between individuals unrelated to political goals"
  - "Consumer shopping boycott for personal reasons (not organized)"
  - "Social media discussion without physical assembly"
  - "News report ABOUT a protest (not the protest itself)"
```

---

## TECH STACK SETUP

### Quick Start (30 minutes)

```bash
# 1. Create virtual environment
python -m venv protest_llm_env
source protest_llm_env/bin/activate

# 2. Install core packages
pip install -r requirements.txt

# 3. Set up API keys
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export HUGGINGFACE_API_KEY="hf_..."

# 4. Download models (if using local)
python -m spacy download en_core_web_sm

# 5. Create directory structure
mkdir -p data/{raw,processed}
mkdir -p configs
mkdir -p notebooks
mkdir -p outputs
```

### Key Packages Explained

| Package | Purpose | Why You Need It |
|---------|---------|-----------------|
| `langchain` | LLM abstraction layer | Switch models without code changes |
| `pydantic` | Data validation | Ensure LLM output matches schema |
| `transformers` | Load HF models locally | Run open models without API |
| `vllm` | Fast LLM inference | Process batches efficiently |
| `ppi-python` | Prediction-powered inference | Account for LLM errors in stats |

---

## IMPLEMENTATION WORKFLOW

### Phase 1: Development & Testing (Your Codebook)

```python
from src.llm_classifier import LLMClassifier, CodebookManager
import json

# Load codebook
codebook = CodebookManager('configs/protest_codebook.yaml')

# Initialize classifier (start with GPT-4o for highest quality)
classifier = LLMClassifier(
    model_name='gpt-4o',
    codebook_manager=codebook,
    api_keys={'openai': YOUR_KEY}
)

# Test on known examples
test_texts = [
    "500 workers gathered outside factory demanding wage increases",
    "Individual punched in bar fight over sports team",
    "Activists blocked highway for 2 hours protesting climate policy"
]

for text in test_texts:
    pred = classifier.classify_zero_shot(text)
    print(f"Text: {text}")
    print(f"Classification: {pred.event_type}")
    print(f"Confidence: {pred.confidence_score}")
    print(f"Reasoning: {pred.reasoning}\n")
```

### Phase 2: Batch Processing (Small Dataset)

```python
from src.batch_processor import BatchProcessor
import pandas as pd

# Load your data
df = pd.read_csv('data/raw/protest_events.csv')

# Process batch
processor = BatchProcessor(classifier, max_batch_size=50)
predictions = processor.process_events(
    df['description'].tolist(),
    method='zero_shot'  # Start with zero-shot
)

# Convert to dataframe
results_df = processor.to_dataframe(predictions)
results_df.to_csv('data/predictions/batch_1_results.csv')
```

### Phase 3: Quality Control

```python
from src.quality_controller import QualityController
import json

# Check quality
qc = QualityController(predictions)
quality_report = qc.generate_quality_report()

print(json.dumps(quality_report, indent=2))

# IF quality issues:
# - Improve codebook definitions
# - Switch to better model (GPT-4o > Claude > Llama)
# - Use chain-of-thought prompting
# - Add few-shot examples
```

### Phase 4: Statistical Inference (Halterman's Key Contribution)

```python
from src.ppi import PredictionPoweredInference

# Initialize PPI with predictions
ppi = PredictionPoweredInference(predictions)

# Get prevalence with confidence intervals
prevalence = ppi.estimate_prevalence(
    event_type='Demonstration/March',
    confidence_level=0.95
)

print(f"Estimated prevalence: {prevalence['estimate']:.1%}")
print(f"95% CI: [{prevalence['ci_lower']:.1%}, {prevalence['ci_upper']:.1%}]")
# This accounts for LLM classification errors!
```

---

## MODEL SELECTION GUIDE

### Quick Decision Tree

```
Do you have GPU infrastructure?
├─ YES: Can I allocate 40GB+ VRAM?
│  ├─ YES: Use Llama 3.1 70B locally (free, excellent quality)
│  └─ NO: Use Llama 2 70B or Mistral 8x22B
├─ NO: What's your budget per 1M tokens?
   ├─ Budget-insensitive: Use GPT-4o (best accuracy, cost: $15/1M)
   ├─ $1-5 budget: Use Claude 3.5 Sonnet ($3/1M, excellent reasoning)
   ├─ <$1 budget: Use Mistral Large ($0.24/1M)
   └─ $0 budget: Use Llama via API (Together AI, Replicate)
```

### Per-Model Configuration

#### GPT-4o (RECOMMENDED FOR INITIAL DEVELOPMENT)

```python
classifier = LLMClassifier(
    model_name='gpt-4o',
    codebook_manager=codebook,
    api_keys={'openai': os.getenv('OPENAI_API_KEY')},
    temperature=0.1,  # Low for consistency
    max_tokens=1000
)
```

**Advantages**: Highest accuracy, best reasoning, handles edge cases
**Disadvantages**: API costs, rate limits, closed source
**Cost**: ~$0.015 per 1000 classified events (small codebook)
**Use for**: Initial development, validation, small datasets

#### Claude 3.5 Sonnet (RECOMMENDED FOR PRODUCTION)

```python
classifier = LLMClassifier(
    model_name='claude-3-5-sonnet',
    codebook_manager=codebook,
    api_keys={'anthropic': os.getenv('ANTHROPIC_API_KEY')},
    temperature=0.1,
    max_tokens=1000
)
```

**Advantages**: Excellent reasoning, thoughtful errors, reliable
**Disadvantages**: Slightly slower than GPT-4o
**Cost**: ~$0.003 per 1000 classified events
**Use for**: Production, when budget matters

#### Llama 3.1 70B (RECOMMENDED FOR SELF-HOSTED)

```python
# Option A: Via Together.ai (easy, cloud-hosted)
from together import Together

client = Together(api_key=os.getenv('TOGETHER_API_KEY'))
classifier = LLMClassifier(
    model_name='llama-3-1-70b',
    codebook_manager=codebook,
    provider='together'
)

# Option B: Self-hosted (requires GPU)
from vllm import LLM, SamplingParams

llm = LLM(model="meta-llama/Llama-3.1-70b", dtype="bfloat16")
sampling_params = SamplingParams(temperature=0.1, max_tokens=1000)
```

**Advantages**: Open source, no API costs, strong performance
**Disadvantages**: Requires compute resources
**Cost**: ~$0 (self-hosted) or $0.50/1M tokens (together.ai)
**Use for**: Large-scale production, cost-sensitive projects

---

## PROMPT ENGINEERING

### Prompt Template Hierarchy

#### LEVEL 1: Zero-Shot (Simplest, Fast)

```
You are a protest event classifier using strict definitions.

[CODEBOOK DEFINITIONS]

TEXT: [your text]

Classify using JSON format.
```

**When to use**: Initial testing, simple events
**Success rate**: 60-75% (depends on codebook clarity)

#### LEVEL 2: Few-Shot (Better Accuracy)

```
[CODEBOOK DEFINITIONS]

EXAMPLES:
Example 1: "500 workers gathered..." → Demonstration/March (confidence: 0.95)
Example 2: "Bar fight broke out..." → Not a Protest Event (confidence: 0.98)

TEXT: [your text]

Classify using same logic.
```

**When to use**: Medium difficulty events, diverse dataset
**Success rate**: 75-85%

#### LEVEL 3: Chain-of-Thought (Best Quality)

```
Think step-by-step:

1. IDENTIFY KEY ELEMENTS:
   - Who? (individuals, groups, organizations)
   - What? (activities, tactics)
   - Why? (goals, demands)
   - Where/When? (location, duration)

2. MATCH TO DEFINITIONS:
   - Which types could fit?
   - Which indicators present?

3. APPLY DECISION RULES:
   - Check edge cases
   - Resolve ambiguities

4. CLASSIFY:
   - Primary type
   - Confidence
   - Alternatives

[CODEBOOK + TEXT]
```

**When to use**: Complex events, edge cases, high stakes
**Success rate**: 85-95%
**Cost**: 2-3x more tokens

---

## QUALITY CONTROL

### Pre-Deployment Checklist

- [ ] Codebook validated by domain experts (≥2 people)
- [ ] 100 test events manually classified and compared to LLM
- [ ] Agreement rate ≥80% on high-confidence predictions
- [ ] Agreement rate ≥70% on all predictions
- [ ] Schema validity rate ≥95%
- [ ] ≥90% of predictions have confidence scores ≥0.70

### During Deployment

```python
# Monitor quality in real-time
from src.quality_controller import QualityController

qc = QualityController(predictions_batch)
report = qc.generate_quality_report()

if report['schema_validity']['flag_for_review']:
    # Alert: >10% invalid schemas
    print("ALERT: Schema validity issue detected")
    
if report['confidence_distribution']['median_confidence'] < 0.65:
    # Alert: Low average confidence
    print("ALERT: Low confidence predictions")
    # Action: Improve codebook or switch models
```

---

## PREDICTION-POWERED INFERENCE

### Why This Matters (Halterman's Core Contribution)

Without PPI:
```
LLM predicts: 45% of events are Demonstrations
You report: "45% are demonstrations"
Reality: LLM misclassifies ~15% (false positives + false negatives)
Your estimate: BIASED
```

With PPI:
```
LLM predicts: 45% are Demonstrations
PPI accounts for: ~15% error rate
Validated estimate: 42% are demonstrations [38%-47% 95% CI]
Your estimate: UNBIASED + UNCERTAINTY QUANTIFIED
```

### Implementation

```python
from src.ppi import PredictionPoweredInference

ppi = PredictionPoweredInference(llm_predictions)

# Estimate prevalence with confidence intervals
results = ppi.estimate_prevalence('Demonstration/March', confidence_level=0.95)
print(f"Proportion: {results['estimate']:.1%} [{results['ci_lower']:.1%}, {results['ci_upper']:.1%}]")

# Estimate correlation with external variable
correlation = ppi.estimate_correlation(predictions, income_levels)
print(f"Correlation with income: r={correlation['correlation']:.3f} (p<{correlation['p_value']:.4f})")

# Note: Results account for LLM classification uncertainty!
```

---

## TROUBLESHOOTING & BEST PRACTICES

### Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Low agreement with manual annotations | Vague codebook definitions | Rewrite Type III definitions with explicit thresholds |
| Uneven performance across event types | Imbalanced training examples | Add more examples for underrepresented types |
| Many "UNCLASSIFIABLE" predictions | Codebook missing categories | Add new event types or "Other" category |
| Model hallucination (making up details) | Too open-ended prompt | Add explicit constraints: "Only use text provided" |
| High API costs | Processing too much text | Increase batch size, use cheaper model (Mistral) |
| Slow processing | Using expensive chain-of-thought | Switch to few-shot or zero-shot for obvious events |

### Best Practices

1. **Start with GPT-4o** for development to validate your approach
2. **Test on 100 events first** before processing thousands
3. **Manual validation is essential** - check a random sample of 50 predictions
4. **Version your codebook** - track changes as you refine definitions
5. **Document all assumptions** - why certain events classified as they are
6. **Use prediction-powered inference** - don't report raw LLM prevalences
7. **Report confidence intervals** - show uncertainty explicitly
8. **Be honest about limitations** - acknowledge codebook gaps
9. **Consider domain expertise** - have subject experts review edge cases
10. **Test for regional bias** - does model perform differently across geographies?

### Ethical Considerations

- **Representation**: Does codebook reflect all types of protest equally?
- **Bias**: Does model misclassify certain types more than others?
- **Transparency**: Are you disclosing use of LLMs in methods?
- **Consent**: For new archival events, consider research ethics
- **Access**: Can your work be replicated by researchers without expensive APIs?

---

## FINAL CHECKLIST

Before publishing results:

- [ ] Codebook is publicly available
- [ ] LLM model choice is documented and justified
- [ ] Prompt template is provided in appendix
- [ ] Manual validation results reported
- [ ] Agreement statistics (% agreement, Cohen's kappa, etc.)
- [ ] All prevalence estimates use PPI-corrected confidence intervals
- [ ] Limitations section addresses LLM uncertainties
- [ ] Code is reproducible (all hyperparameters specified)
- [ ] Dataset (or representative sample) is available
- [ ] Raw and processed data separated clearly

---

## REFERENCES & RESOURCES

### Key Papers
- Halterman & Keith (2025): "What is a protest anyway?" [Codebook conceptualization]
- Angelopoulos et al. (2023): "Prediction-Powered Inference" [Statistical foundation]
- Keith et al. (2023): "Uncertainty Quantification in Generative Models" [LLM uncertainty]

### Codebook Examples
- [Your expanded meta codebook] - Use as starting point
- ACLED Codebook (v.2023)
- PolDem Documentation
- FARPE Protocol

### Tools & Libraries
- LangChain: https://python.langchain.com/
- Pydantic: https://docs.pydantic.dev/
- vLLM: https://vllm.readthedocs.io/
- PPI Python: https://github.com/aangelopoulos/ppi_py

