# LLM-Powered Protest Event Classification System
## Complete Implementation Package Aligned with Halterman & Keith (2025)

---

## 📦 PACKAGE CONTENTS

### Core Files (6 items, 1,700+ lines of code/documentation)

| File | Lines | Purpose |
|------|-------|---------|
| **QUICKSTART_GUIDE.md** | 340 | Start here! 5-minute quick start + troubleshooting |
| **LLM_IMPLEMENTATION_GUIDE.md** | 547 | Complete theory, implementation, best practices |
| **llm_protest_implementation.py** | 557 | Production-ready Python code (7 modules) |
| **protest_codebook_example.yaml** | 303 | Type III codebook with 6 core event types |
| **requirements.txt** | 59 | 30+ Python packages pre-configured |
| **Comprehensive_Meta_Codebook_Protest_Analysis.docx** | N/A | Reference (10+ datasets harmonized) |

---

## 🎯 WHAT THIS SOLVES

You have a **comprehensive meta codebook** synthesizing 10+ protest event datasets (ACLED, UCDP, SCAD, NAVCO, PolDem, FARPE, CAPT, etc.).

**Problem**: How do you USE this codebook with modern LLMs for classification?

**Solution**: This package shows you exactly how to:

1. **Restructure** your meta codebook into LLM-friendly "Type III" definitions
2. **Build prompts** for zero-shot, few-shot, and chain-of-thought classification
3. **Select models** (GPT-4o, Claude, Llama, Mistral) based on your constraints
4. **Process batches** efficiently with error handling
5. **Validate quality** and detect issues
6. **Generate valid statistics** that account for LLM classification errors

---

## 🚀 QUICK START (5 MINUTES)

```bash
# 1. Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."

# 2. Code
python -c "
from llm_protest_implementation import CodebookManager, LLMClassifier

codebook = CodebookManager('protest_codebook_example.yaml')
classifier = LLMClassifier('gpt-4o', codebook, {'openai': 'YOUR_KEY'})

text = 'Workers gathered outside factory demanding wage increases'
prediction = classifier.classify_zero_shot(text)
print(f'{prediction.event_type} (confidence: {prediction.confidence_score:.2f})')
"
# Output: Demonstration/March (confidence: 0.92)
```

**More details**: See QUICKSTART_GUIDE.md

---

## 📊 THE HALTERMAN & KEITH (2025) METHODOLOGY

### Key Insight: Codebook Conceptualization is First-Order

The paper identifies three types of definitions:

```
Type I (Surface)      → "Is this a protest?"
Type II (Dictionary)  → "A protest is when people gather to express demands"
Type III (Stipulative) → YOUR PRECISE OPERATIONAL DEFINITION
```

Your meta codebook provides **Type II** (excellent reference).

This package helps you create **Type III** (what LLMs need).

### The Three Critical Claims

**Claim 1**: Conceptualization > Model Quality
- Vague codebook = biased predictions (always)
- Better model doesn't fix vague definitions
- Better post-hoc methods don't fix vague definitions

**Claim 2**: Definition Types Matter
- Type I/II definitions can "fail silently" 
- LLMs generate plausible outputs even without clear definitions
- Type III fixes this through explicit operationalization

**Claim 3**: Prediction-Powered Inference Saves You
- Don't report raw LLM prevalences
- Use PPI to generate confidence intervals
- Now your statistics are valid despite misclassification

### The Complete Workflow

```
Background Concept → Type III Definition → LLM Prompt →
LLM Predictions → Prediction-Powered Inference →
Valid Statistics with Uncertainty Quantification
```

---

## 💻 TECH STACK OVERVIEW

### LLM Models (Choose 1)

| Model | Provider | Best For | Cost | HF? |
|-------|----------|----------|------|-----|
| **GPT-4o** | OpenAI | Development, highest accuracy | $15/1M tokens | ❌ |
| **Claude 3.5 Sonnet** | Anthropic | Production, excellent reasoning | $3/1M tokens | ❌ |
| **Llama 3.1 70B** | Meta/HF | Self-hosted, cost-free | FREE | ✅ |
| **Mistral Large** | Mistral | Balanced cost/performance | $0.24/1M tokens | ✅ |

**Recommendation**: Start with GPT-4o for validation, switch to Claude/Llama for production.

### Python Ecosystem

```
LangChain      → Unified LLM interface
Pydantic       → Type-safe JSON schemas
Transformers   → Local model loading
vLLM           → Fast batch inference
SciPy/Stats    → Statistical inference
```

---

## 🔧 CORE MODULES (in llm_protest_implementation.py)

### 1. **ProtestEventPrediction** (Pydantic)
Structured output schema ensuring LLM responses match your codebook

```python
event_type: str           # e.g., "Demonstration/March"
confidence_score: float   # 0.0-1.0
reasoning: str            # Why this classification
key_indicators: List[str] # Supporting text phrases
alternative_types: Optional[List]  # Other possibilities
```

### 2. **CodebookManager**
Loads, validates, and manages your YAML codebook definitions

```python
codebook = CodebookManager('protest_codebook_example.yaml')
context = codebook.get_prompt_context()  # Formatted for LLM
valid = codebook.validate_prediction(pred)  # Checks schema
```

### 3. **ProtestEventPrompter**
Builds three types of prompts automatically

```python
zeroshot_prompt = prompter.build_zero_shot_prompt(text)
fewshot_prompt = prompter.build_few_shot_prompt(text, examples)
cot_prompt = prompter.build_chain_of_thought_prompt(text)
```

### 4. **LLMClassifier**
Multi-model support with unified interface

```python
classifier = LLMClassifier('gpt-4o', codebook, api_keys)
pred = classifier.classify_zero_shot(text)
pred = classifier.classify_few_shot(text, examples)
pred = classifier.classify_with_cot(text)
```

### 5. **BatchProcessor**
Efficiently process hundreds/thousands of events

```python
processor = BatchProcessor(classifier)
predictions = processor.process_events(texts, method='zero_shot')
df = processor.to_dataframe(predictions)
```

### 6. **PredictionPoweredInference** (⭐ CRITICAL)
Generate valid statistics accounting for LLM misclassification

```python
ppi = PredictionPoweredInference(predictions)
result = ppi.estimate_prevalence('Demonstration')
# {estimate: 0.42, ci_lower: 0.38, ci_upper: 0.47}
```

### 7. **QualityController**
Monitor classification quality in real-time

```python
qc = QualityController(predictions)
report = qc.generate_quality_report()
# Flags issues: schema violations, low confidence, etc.
```

---

## 📋 EXAMPLE CODEBOOK (protest_codebook_example.yaml)

Includes 6 core event types ready for LLM classification:

1. **Demonstration/March** - Peaceful ≥2 people gathering
2. **Strike/Boycott** - Organized work/consumption refusal
3. **Riot** - Violent collective property destruction/assault
4. **Occupation/Seizure** - Multi-hour space occupation
5. **Confrontation** - Direct non-violent obstruction
6. **Petition/Signature** - Organized formal demands

Each type includes:
- ✅ Clear Type III definition
- ✅ 3+ positive examples with reasoning
- ✅ 3+ negative examples explaining what ISN'T this type
- ✅ Decision rules for ambiguous cases
- ✅ Confidence threshold (0.65-0.80)
- ✅ Cross-reference to ACLED/PolDem/FARPE

---

## 🎓 LEARNING PATH

### For Impatient Researchers (30 minutes)
1. Read QUICKSTART_GUIDE.md (5 min)
2. Skim protest_codebook_example.yaml (10 min)
3. Run the code example (10 min)
4. Look at llm_protest_implementation.py docstrings (5 min)

### For Thorough Implementation (2-3 hours)
1. Read LLM_IMPLEMENTATION_GUIDE.md fully (1 hour)
2. Review Halterman & Keith (2025) paper (30 min)
3. Study protest_codebook_example.yaml deeply (30 min)
4. Walk through llm_protest_implementation.py (30 min)

### For Publication-Ready Work (1 week)
1. Develop codebook (2-3 days)
2. Test on 100 events (1 day)
3. Refine based on validation (1-2 days)
4. Scale to full dataset (1 day)
5. Generate PPI estimates (1 day)

---

## ⚡ CRITICAL SUCCESS FACTORS

### ✅ DO THIS

1. **Invest in codebook definitions**
   - Write Type III definitions, not Type I
   - Include explicit examples of what IS and ISN'T
   - Add decision rules for edge cases

2. **Start with best model**
   - Use GPT-4o for initial development
   - Test on 100-500 events first
   - Compare to manual annotations

3. **Use Prediction-Powered Inference**
   - Don't report raw LLM prevalences
   - Use PPI to generate confidence intervals
   - This makes your statistics valid

4. **Document everything**
   - Record codebook versions
   - Note any refinements
   - Report quality metrics

### ❌ DON'T DO THIS

1. **Skip codebook work** ("I'll fix it with a better model")
   - Won't work - misclassifications propagate
   - Model quality doesn't fix conceptual problems

2. **Use naive averaging** ("45% are demonstrations")
   - This is BIASED
   - Use PPI instead

3. **Report only accuracy metrics** ("92% agreement")
   - Tell us about specific disagreement patterns
   - Which types are hardest?

4. **Ignore low confidence predictions** ("Just filter them out")
   - Use PPI to account for them properly
   - Don't artificially improve accuracy by deleting hard cases

---

## 📚 REFERENCES & RESOURCES

### Essential Papers
- **Halterman & Keith (2025)**: "What is a protest anyway?" [[arXiv:2510.03541](https://arxiv.org/html/2510.03541v1)]
  - Core methodology for this project
  
- **Angelopoulos et al. (2023)**: "Prediction-Powered Inference" [[arXiv:2309.08574](https://arxiv.org/abs/2309.08574)]
  - Statistical foundation for PPI

### Libraries & Documentation
- **LangChain**: https://python.langchain.com/
- **Pydantic**: https://docs.pydantic.dev/
- **OpenAI API**: https://platform.openai.com/docs/
- **Anthropic Claude**: https://docs.anthropic.com/

### Protest Event Datasets (Reference)
- **ACLED**: https://acleddata.com/
- **UCDP**: https://ucdp.uu.se/
- **SCAD**: https://www.strausscenter.org/scad.html
- **NAVCO**: https://navco.org/

---

## 🆘 TROUBLESHOOTING

### "LLM predictions don't match my manual annotations"
→ Your codebook definitions need work. Add more specificity.

### "High confidence predictions are wrong"
→ Use chain-of-thought prompting. More reasoning = better decisions.

### "API costs are too high"
→ Switch to Llama 3.1 70B via Together.ai (~$0.50/1M tokens).

### "I get many 'UNCLASSIFIABLE' predictions"
→ Add categories to your codebook or evaluate if those texts should be excluded.

### "How do I report my results?"
→ Use Prediction-Powered Inference for prevalence estimates with 95% CIs.

See **QUICKSTART_GUIDE.md** for more troubleshooting.

---

## 🔐 BEST PRACTICES

1. **Version control your codebook**
   - Track changes as you refine definitions
   - Document why specific definitions were chosen
   
2. **Validate on sample before scaling**
   - Run on 100 events, check manual agreement
   - Don't process 100,000 events with untested approach
   
3. **Monitor quality metrics continuously**
   - Track schema validity rate
   - Monitor confidence distribution
   - Flag when metrics degrade
   
4. **Use confidence scores appropriately**
   - Don't threshold them out (use PPI instead)
   - Visualize distribution to find patterns
   
5. **Combine with domain expertise**
   - Have subject experts review edge cases
   - Document disagreements and why they occur
   
6. **Be transparent about limitations**
   - Acknowledge LLM error rates
   - Report uncertainty in estimates
   - Discuss potential biases

---

## 📄 FILE DESCRIPTIONS

### QUICKSTART_GUIDE.md
Your entry point. 5-minute quick start showing:
- Environment setup
- Single-event classification
- Batch processing
- Quality control
- Statistical inference
- Model recommendations
- Troubleshooting

### LLM_IMPLEMENTATION_GUIDE.md
Comprehensive 547-line guide covering:
- Theory (Halterman & Keith methodology)
- Codebook restructuring
- All 7 tech stack components
- 3 types of LLM prompts
- Model selection decision tree
- Implementation workflow (Phase 1-4)
- Quality control procedures
- PPI explained
- Best practices & ethics

### llm_protest_implementation.py
Production-ready Python code (557 lines):
- Pydantic schemas for type safety
- CodebookManager for loading definitions
- ProtestEventPrompter for building prompts
- LLMClassifier supporting 4 models
- BatchProcessor for scaling
- PredictionPoweredInference (the key!)
- QualityController for monitoring
- Complete usage example

### protest_codebook_example.yaml
Type III codebook (303 lines):
- 6 core event types fully specified
- Positive/negative examples for each
- Decision rules for ambiguity
- Edge case guidance
- QC checklist
- Non-event exclusions
- General coding rules

### requirements.txt
Python dependencies (59 lines):
- LLM APIs: OpenAI, Anthropic, HuggingFace
- Data: Pandas, NumPy, Pydantic
- Statistics: SciPy, Statsmodels
- Inference: vLLM, Transformers, Torch
- Testing: Pytest, etc.

### Comprehensive_Meta_Codebook_Protest_Analysis.docx
Reference document synthesizing:
- 10+ protest event datasets
- Harmonization strategies
- Variable definitions across systems
- Actor typologies
- Best practices

---

## 🎯 SUCCESS METRICS

You'll know this is working when:

- ✅ Your Type III definitions are crystal clear
- ✅ Manual validation shows 80%+ agreement on high-confidence predictions
- ✅ Quality control report flags <5% schema violations
- ✅ Confidence scores align with actual accuracy (high conf → high accuracy)
- ✅ PPI confidence intervals are reasonable widths (~±5% around estimate)
- ✅ Edge cases are resolved consistently
- ✅ You can document why each classification was made

---

## 🤝 NEXT STEPS

1. **Read QUICKSTART_GUIDE.md** (5 min)
2. **Customize protest_codebook_example.yaml** for your needs (1-2 hours)
3. **Set up environment and test on 10 events** (15 min)
4. **Run quality control on 100 events** (1 hour)
5. **Scale to your full dataset** (depends on size)

---

## 📞 SUPPORT

- **Code issues**: Check `llm_protest_implementation.py` docstrings
- **Theory questions**: Read Section 1-2 of `LLM_IMPLEMENTATION_GUIDE.md`
- **Codebook issues**: Review `protest_codebook_example.yaml` edge cases section
- **Statistical questions**: See Angelopoulos et al. (2023) on PPI
- **Model questions**: See model comparison table in `QUICKSTART_GUIDE.md`

---

## 📜 CITATION

If you use this implementation, please cite:

```bibtex
@article{halterman_keith_2025,
  title={What is a protest anyway? {C}odebook conceptualization is still a first-order concern in {LLM-era} classification},
  author={Halterman, Andrew and Keith, Katherine A.},
  journal={arXiv preprint arXiv:2510.03541},
  year={2025}
}

@misc{proteclassif_package,
  title={LLM-Powered Protest Event Classification System},
  author={Your Name},
  year={2026},
  note={Implementation aligned with Halterman \& Keith (2025)}
}
```

---

## 📝 LICENSE

This implementation package is provided as-is for research purposes.

The methodological foundation (Halterman & Keith 2025) and statistical innovation (Prediction-Powered Inference) are open science contributions.

---

**Ready to get started? Begin with QUICKSTART_GUIDE.md!**

