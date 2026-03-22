# Claude Code Implementation Guide
## Project: LLM-Powered Protest Event Classification (pea)

### Context
- Implements Halterman & Keith (2025) methodology
- Uses local Llama via Ollama (no cloud API keys required)
- See LLAMA_LOCAL_SETUP_M2_MAC.md for Ollama setup

### Project Structure
```
src/models/    - schemas, llm_classifier, batch_processor, ppi_estimator, quality_controller
src/utils/     - codebook_manager, prompt_builder
tests/         - one test file per module, all LLM calls mocked
configs/       - protest_codebook.yaml (Type III definitions)
data/          - raw/, processed/, predictions/ (contents git-ignored)
docs/          - reference guides
```

### LLM Setup
- Primary: local Llama via Ollama (model: llama3)
- Endpoint: http://localhost:11434/api/generate
- No API keys needed for local inference

### Code Standards
- Python 3.10+
- Type hints throughout
- Google-style docstrings
- Tests: pytest, mocked LLM calls only (no real Ollama calls in tests)
- Line length: 100

### Key Modules
1. `src/models/schemas.py` - Pydantic models
2. `src/utils/codebook_manager.py` - YAML codebook loader/validator
3. `src/utils/prompt_builder.py` - zero-shot, few-shot, CoT prompts
4. `src/models/llm_classifier.py` - Ollama-backed classifier
5. `src/models/batch_processor.py` - batch processing with error recovery
6. `src/models/ppi_estimator.py` - Prediction-Powered Inference
7. `src/models/quality_controller.py` - QC reporting
