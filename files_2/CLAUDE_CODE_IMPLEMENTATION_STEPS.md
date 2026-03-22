# Claude Code Implementation: Step-by-Step Guide
## Your Complete Roadmap for Building with Claude Code + GitHub

---

## ⚡ BEFORE YOU START: 5-MINUTE CHECKLIST

You need these three things ready:

- [ ] **GitHub Account** with a repository (create: https://github.com/new)
- [ ] **Claude Code** installed (or Claude Code in VS Code)
- [ ] **API Keys** for at least one LLM (OpenAI, Anthropic, or HuggingFace)

Once you have these, follow the steps below.

---

## STEP 1: GITHUB REPOSITORY SETUP (15 minutes)

### 1A: Create Repository on GitHub

```bash
# Visit: https://github.com/new

# Fill in:
# Repository name: protest-llm-classifier
# Description: LLM-powered protest event classification with Halterman & Keith methodology
# Public (recommended for open science)
# Add README (yes)
# Add .gitignore: Python
```

### 1B: Clone Repository Locally

```bash
# Copy the HTTPS clone URL from GitHub
# It will look like: https://github.com/YOUR_USERNAME/protest-llm-classifier.git

# In your terminal:
git clone https://github.com/YOUR_USERNAME/protest-llm-classifier.git
cd protest-llm-classifier
```

### 1C: Copy All Files from /mnt/user-data/outputs/

```bash
# Download these files:
# - README.md
# - QUICKSTART_GUIDE.md
# - LLM_IMPLEMENTATION_GUIDE.md
# - llm_protest_implementation.py
# - protest_codebook_example.yaml
# - requirements.txt
# - GITHUB_AND_CLAUDE_CODE_SETUP.md
# - MASTER_IMPLEMENTATION_ROADMAP.md

# Copy them to your repository directory

# Create directory structure
mkdir -p src/{models,utils,prompts}
mkdir -p data/{raw,processed,predictions}
mkdir -p notebooks tests configs docs .github/workflows

# Move files to configs/
mv protest_codebook_example.yaml configs/
cp llm_protest_implementation.py src/models/

# Move docs
mv *GUIDE.md docs/
mv *ROADMAP.md docs/

# Keep setup files in root
# README.md, requirements.txt, .gitignore should be in root
```

### 1D: Initial Git Commit

```bash
git add .
git commit -m "Initial commit: project structure and documentation"
git push origin main
```

---

## STEP 2: INSTALL CLAUDE CODE (10 minutes)

### Option A: Claude Code CLI (Recommended)

```bash
# macOS/Linux:
curl -fsSL https://get.anthropic.com/claude-code | bash

# Windows (PowerShell):
irm https://get.anthropic.com/claude-code | iex

# Verify installation:
claude-code --version

# Should output something like:
# Claude Code CLI v1.0.0
```

### Option B: VS Code Extension

```bash
# Install VS Code extension
code --install-extension Anthropic.claude-code

# Or search for "Claude Code" in VS Code Extensions
```

### Option C: Claude.ai Web Interface

```bash
# Go to https://claude.ai
# Look for "Claude Code" button
# Connect to your GitHub repository
```

---

## STEP 3: AUTHENTICATE CLAUDE CODE WITH GITHUB (5 minutes)

```bash
# Login to Claude Code
claude-code auth login

# Follow prompts:
# 1. Sign in with your Anthropic account
# 2. Authorize GitHub access
# 3. Select your repository

# Verify connection:
claude-code auth check
# Should show: "Authenticated ✓"
```

---

## STEP 4: SET UP ENVIRONMENT (10 minutes)

### 4A: Create Python Virtual Environment

```bash
# Create venv
python -m venv venv

# Activate (macOS/Linux):
source venv/bin/activate

# Activate (Windows):
venv\Scripts\activate

# Verify:
which python  # Should show path to venv/bin/python
```

### 4B: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt

# This will take a few minutes (30+ packages)
```

### 4C: Create .env File

```bash
# Copy example to .env
cp .env.example .env

# Edit .env with your API keys:
nano .env  # or use your favorite editor

# Add your keys:
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

---

## STEP 5: INITIALIZE CLAUDE CODE PROJECT (5 minutes)

```bash
# Initialize Claude Code in your repository
claude-code init

# It will ask:
# 1. Project name: protest-llm-classifier
# 2. Description: LLM-powered protest event classification
# 3. Link GitHub repo: [your repo URL]

# Verify:
ls -la .claude/
# Should contain: implementation-guide.md, config.json
```

---

## STEP 6: CREATE IMPLEMENTATION GUIDE FOR CLAUDE CODE (10 minutes)

Create `.claude/implementation-guide.md`:

```bash
cat > .claude/implementation-guide.md << 'GUIDE'
# Claude Code Implementation Guide

## Project: LLM-Powered Protest Event Classification

### Core Requirements
- Python 3.9+
- Type hints everywhere (mypy strict mode)
- Google-style docstrings
- >80% test coverage
- Pydantic for data validation

### Modules to Implement

#### 1. src/models/llm_classifier.py (Priority: HIGH)
- LLMClassifier class
- Support: gpt-4o, claude-3-5-sonnet, llama-3-1-70b, mistral-large
- Methods: classify_zero_shot(), classify_few_shot(), classify_with_cot()
- Returns: ProtestEventPrediction (Pydantic model)

#### 2. src/utils/codebook_manager.py (Priority: HIGH)
- CodebookManager class
- Load YAML codebooks
- Validate predictions against schema
- Format codebook for LLM prompts
- Methods: load(), validate_prediction(), get_prompt_context()

#### 3. src/models/batch_processor.py (Priority: HIGH)
- BatchProcessor class
- Process multiple events efficiently
- Error handling and recovery
- Progress tracking
- Methods: process_events(), to_dataframe()

#### 4. src/models/ppi_estimator.py (Priority: MEDIUM)
- PredictionPoweredInference class
- Estimate prevalence with confidence intervals
- Handle misclassification uncertainty
- Methods: estimate_prevalence(), estimate_correlation()

#### 5. src/utils/prompt_builder.py (Priority: MEDIUM)
- PromptBuilder class
- Zero-shot prompts
- Few-shot prompts
- Chain-of-thought prompts
- Methods: build_zero_shot(), build_few_shot(), build_cot()

#### 6. tests/ (Priority: HIGH)
- test_classifier.py: Unit tests for LLMClassifier
- test_codebook.py: Unit tests for CodebookManager
- test_batch.py: Unit tests for BatchProcessor
- test_ppi.py: Unit tests for PPI
- All tests use mocks (no real API calls)

### Codebook Location
- Main: configs/protest_codebook.yaml
- Already has 6 event types with examples

### Critical: Schema Compliance
All predictions MUST include:
- event_type: str (e.g., "Demonstration/March")
- confidence_score: float (0.0-1.0)
- reasoning: str (explanation of classification)
- key_indicators: List[str] (supporting text phrases)
- schema_valid: bool (matches codebook)

### Testing Strategy
- Use pytest
- Mock LLM responses with fixtures
- NO real API calls in tests
- Target coverage: >80%

### Code Style
- Line length: 100 characters
- Type hints: mypy strict mode
- Format: black
- Lint: flake8

GUIDE

git add .claude/implementation-guide.md
git commit -m "docs: add claude code implementation guide"
git push origin main
```

---

## STEP 7: HAVE CLAUDE CODE IMPLEMENT CORE MODULES (30-60 minutes)

### 7A: Implement LLMClassifier

```bash
# Create feature branch
git checkout -b feat/implement-llm-classifier

# Have Claude implement it
claude-code implement \
  --file src/models/llm_classifier.py \
  --description "Implement LLMClassifier class supporting GPT-4o, Claude, Llama, Mistral with zero-shot, few-shot, and chain-of-thought methods"

# Claude will:
# 1. Read implementation-guide.md
# 2. Read codebook requirements
# 3. Generate implementation
# 4. Ask for approval
# 5. Commit with: feat(classifier): implement LLMClassifier

# Review the code:
git diff

# Accept and push:
git add src/models/llm_classifier.py
git commit -m "feat(classifier): implement LLMClassifier with multi-model support"
git push origin feat/implement-llm-classifier
```

### 7B: Implement CodebookManager

```bash
git checkout -b feat/implement-codebook-manager

claude-code implement \
  --file src/utils/codebook_manager.py \
  --description "Implement CodebookManager class to load YAML codebooks, validate predictions, and format for LLM prompts"

git add src/utils/codebook_manager.py
git commit -m "feat(codebook): implement CodebookManager"
git push origin feat/implement-codebook-manager
```

### 7C: Implement BatchProcessor

```bash
git checkout -b feat/implement-batch-processor

claude-code implement \
  --file src/models/batch_processor.py \
  --description "Implement BatchProcessor class for efficient batch processing with error handling and progress tracking"

git add src/models/batch_processor.py
git commit -m "feat(batch): implement BatchProcessor"
git push origin feat/implement-batch-processor
```

### 7D: Implement PPIEstimator

```bash
git checkout -b feat/implement-ppi

claude-code implement \
  --file src/models/ppi_estimator.py \
  --description "Implement PredictionPoweredInference class for statistically valid estimates accounting for LLM misclassification. Use scipy.stats for confidence intervals."

git add src/models/ppi_estimator.py
git commit -m "feat(ppi): implement PredictionPoweredInference"
git push origin feat/implement-ppi
```

### 7E: Implement PromptBuilder

```bash
git checkout -b feat/implement-prompts

claude-code implement \
  --file src/utils/prompt_builder.py \
  --description "Implement PromptBuilder class for zero-shot, few-shot, and chain-of-thought prompts. Use codebook definitions."

git add src/utils/prompt_builder.py
git commit -m "feat(prompts): implement PromptBuilder"
git push origin feat/implement-prompts
```

---

## STEP 8: CREATE PULL REQUESTS & MERGE (30 minutes)

### For Each Branch:

```bash
# 1. Go to GitHub
# https://github.com/YOUR_USERNAME/protest-llm-classifier

# 2. Click "Pull requests" → "New pull request"

# 3. Select:
#    - Base: main
#    - Compare: feat/implement-llm-classifier

# 4. Add description:
#    - What: Implement LLMClassifier class
#    - Why: Core module for classification
#    - Testing: Works with all 4 LLM models

# 5. Create pull request

# 6. Once approved (by you), click "Merge pull request"

# Back in terminal:
git checkout main
git pull origin main
```

Repeat for all 5 features.

---

## STEP 9: HAVE CLAUDE CODE GENERATE TESTS (30-45 minutes)

### 9A: Generate Tests for Each Module

```bash
git checkout -b feat/add-tests

# Generate comprehensive tests
claude-code test \
  --source src/ \
  --output tests/ \
  --generate-tests \
  --mock-llm-calls

# This creates:
# - tests/test_classifier.py (20+ tests)
# - tests/test_codebook.py (15+ tests)
# - tests/test_batch.py (15+ tests)
# - tests/test_ppi.py (10+ tests)
# - tests/conftest.py (fixtures)

# Total: >80% coverage

# Verify tests pass:
pytest tests/ -v --cov=src --cov-report=html
```

### 9B: Create __init__.py Files

```bash
# Claude Code should create these, but if not:
touch src/__init__.py
touch src/models/__init__.py
touch src/utils/__init__.py
touch tests/__init__.py
```

### 9C: Commit and Push Tests

```bash
git add tests/
git commit -m "test: add comprehensive unit tests with >80% coverage"
git push origin feat/add-tests

# Create PR and merge
```

---

## STEP 10: GENERATE DOCUMENTATION (20-30 minutes)

### 10A: Generate API Documentation

```bash
git checkout -b docs/add-api-docs

claude-code docs \
  --source src/ \
  --output docs/API.md \
  --format markdown \
  --include-examples

# This creates:
# - docs/API.md (complete API reference)
# - docs/examples.md (usage examples)
```

### 10B: Create Example Notebook

```bash
# Create Jupyter notebook template
cat > notebooks/01_development.ipynb << 'NOTEBOOK'
{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# Development Notebook\n",
    "## Testing LLM Protest Event Classification\n"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "source": [
    "import os\n",
    "from dotenv import load_dotenv\n",
    "load_dotenv()\n",
    "\n",
    "# Test on single event\n",
    "from src.models.llm_classifier import LLMClassifier\n",
    "from src.utils.codebook_manager import CodebookManager\n",
    "\n",
    "codebook = CodebookManager('configs/protest_codebook_example.yaml')\n",
    "classifier = LLMClassifier('gpt-4o', codebook, {'openai': os.getenv('OPENAI_API_KEY')})\n",
    "\n",
    "text = 'Workers gathered outside factory demanding wage increases'\n",
    "prediction = classifier.classify_zero_shot(text)\n",
    "print(f'{prediction.event_type}: {prediction.confidence_score:.2f}')\n"
   ]
  }
 ],
 "metadata": {},
 "nbformat": 4,
 "nbformat_minor": 4
}
NOTEBOOK

git add notebooks/01_development.ipynb
git add docs/API.md
git commit -m "docs: add API documentation and example notebook"
git push origin docs/add-api-docs

# Create PR and merge
```

---

## STEP 11: SET UP CI/CD PIPELINE (15 minutes)

### 11A: Copy GitHub Actions Workflows

```bash
# Create workflows directory
mkdir -p .github/workflows

# Copy test workflow from GITHUB_AND_CLAUDE_CODE_SETUP.md PART 6
cat > .github/workflows/tests.yml << 'WORKFLOW'
name: Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']

    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    - run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pytest pytest-cov
    - run: pytest tests/ -v --cov=src --cov-report=xml
    - uses: codecov/codecov-action@v3
WORKFLOW

# Copy lint workflow
cat > .github/workflows/lint.yml << 'WORKFLOW'
name: Lint

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    - run: |
        pip install black flake8 mypy
    - run: black --check src/ tests/
    - run: flake8 src/ tests/
    - run: mypy src/
WORKFLOW

git add .github/workflows/
git commit -m "ci: add GitHub Actions workflows for testing and linting"
git push origin main
```

### 11B: Enable Branch Protection

```bash
# Go to GitHub: Settings → Branches
# Add rule for "main" branch
# Enable:
# - Require pull request reviews
# - Require status checks to pass
# - Require branches to be up to date
```

---

## STEP 12: VALIDATE WITH SAMPLE DATA (30 minutes)

### 12A: Create Sample Test Data

```bash
# Create sample protest events
cat > data/raw/sample_events.csv << 'DATA'
id,text,date,location
1,Workers gathered outside factory demanding wage increases,2024-03-15,Detroit
2,Police used tear gas against peaceful protesters,2024-03-16,Seattle
3,Environmental activists occupied city plaza for 3 weeks,2024-03-17,Portland
4,Union called strike shutting down production,2024-03-18,Chicago
5,Youth broke storefront windows during protest,2024-03-19,Minneapolis
DATA
```

### 12B: Run Validation Script

```bash
python -c "
from src.models.llm_classifier import LLMClassifier
from src.utils.codebook_manager import CodebookManager
from src.models.batch_processor import BatchProcessor
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()

# Load data
df = pd.read_csv('data/raw/sample_events.csv')

# Initialize
codebook = CodebookManager('configs/protest_codebook_example.yaml')
classifier = LLMClassifier('gpt-4o', codebook, {'openai': os.getenv('OPENAI_API_KEY')})

# Process
processor = BatchProcessor(classifier)
predictions = processor.process_events(df['text'].tolist(), method='zero_shot')

# Save results
results_df = processor.to_dataframe(predictions)
results_df.to_csv('data/predictions/sample_results.csv', index=False)
print(f'Classified {len(predictions)} events')
print(results_df.head())
"
```

### 12C: Review Results

```bash
# Check predictions
cat data/predictions/sample_results.csv

# Expected output:
# event_type,confidence,reasoning,num_indicators
# Demonstration/March,0.95,Peaceful gathering with demands,3
# ...
```

---

## STEP 13: HAVE CLAUDE CODE REFACTOR & OPTIMIZE (20 minutes)

```bash
git checkout -b perf/optimize-code

# Ask Claude to improve code
claude-code refactor \
  --target src/ \
  --improvements "improve type hints, add docstrings, optimize batch processing"

# Claude will improve:
# - Type hints
# - Docstrings
# - Code organization
# - Performance

git add src/
git commit -m "refactor: improve type hints and documentation"
git push origin perf/optimize-code

# Create PR and merge
```

---

## STEP 14: CREATE RELEASE (10 minutes)

```bash
git checkout main
git pull origin main

# Create version tag
git tag -a v0.1.0 -m "Initial release: complete LLM-powered protest event classification system"
git push origin v0.1.0

# Go to GitHub: Releases
# Click "Create release"
# Select v0.1.0
# Add release notes:
# - LLMClassifier with multi-model support
# - CodebookManager with validation
# - BatchProcessor for scaling
# - PPI for valid statistics
# - Complete test suite (>80% coverage)
# - Full API documentation
```

---

## STEP 15: CONTINUOUS IMPROVEMENT (Ongoing)

### Monitor Quality

```bash
# Check code coverage
pytest tests/ --cov=src --cov-report=html

# View at: htmlcov/index.html
```

### Add Features

```bash
# For each new feature:
git checkout -b feat/your-feature-name
claude-code implement --feature "description"
git push origin feat/your-feature-name
# Create PR and merge
```

### Fix Issues

```bash
# For bugs:
git checkout -b fix/bug-name
claude-code debug --error "description"
git push origin fix/bug-name
# Create PR and merge
```

---

## QUICK COMMAND REFERENCE

### Claude Code Commands

```bash
# Setup
claude-code auth login
claude-code init

# Development
claude-code implement --file src/models/xyz.py
claude-code analyze src/
claude-code refactor src/

# Testing
claude-code test src/ --generate-tests
claude-code coverage

# Documentation
claude-code docs src/
claude-code readme-generate

# Debugging
claude-code debug --error "error message"

# Code Review
claude-code review feat/my-branch

# Quality
claude-code lint src/
claude-code format src/
```

### Git Commands

```bash
# Branches
git checkout -b feat/new-feature
git push origin feat/new-feature
git checkout main
git pull origin main

# Commits
git add .
git commit -m "type(scope): message"
git push origin branch-name

# Tags
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

---

## EXPECTED TIMELINE

| Step | Time | What Happens |
|------|------|-------------|
| 1-3 | 30 min | Repository setup |
| 4-6 | 30 min | Environment & authentication |
| 7 | 60 min | Claude Code implements 5 modules |
| 8 | 30 min | Create PRs and merge |
| 9 | 45 min | Generate tests |
| 10 | 30 min | Generate documentation |
| 11 | 15 min | Set up CI/CD |
| 12 | 30 min | Validate with sample data |
| 13 | 20 min | Optimize code |
| 14 | 10 min | Create release |

**Total: ~5 hours for complete implementation**

---

## TROUBLESHOOTING

### Claude Code Won't Authenticate

```bash
# Clear cache
rm ~/.claude/credentials.json

# Re-authenticate
claude-code auth login --force
```

### GitHub Push Fails

```bash
# Check SSH key
ssh -T git@github.com

# Or use HTTPS with token
git remote set-url origin https://<token>@github.com/USER/REPO.git
```

### Tests Fail

```bash
# Run locally first
pytest tests/ -v

# Check Python version (3.9+)
python --version

# Install missing dependencies
pip install -r requirements.txt -U
```

### Claude Code Doesn't Create Expected Code

```bash
# Provide more detail in implementation-guide.md
# Add example code or expected interface
# Try again with more specific description
```

---

## SUCCESS CHECKLIST

- [ ] GitHub repo created and cloned
- [ ] Claude Code installed and authenticated
- [ ] All dependencies installed
- [ ] 5 core modules implemented
- [ ] All tests passing (>80% coverage)
- [ ] Documentation generated
- [ ] CI/CD workflows running
- [ ] Sample data validated
- [ ] Code refactored and optimized
- [ ] v0.1.0 released
- [ ] Ready for production use

---

## NEXT STEPS AFTER IMPLEMENTATION

Once this is complete:

1. **Test on Real Data**: Use your actual protest event dataset
2. **Refine Codebook**: Adjust definitions based on results
3. **Validate Manually**: Check 100+ events by hand
4. **Generate Statistics**: Use PPI for valid estimates
5. **Publish Results**: Share with research community

---

## GET HELP

- **Claude Code Docs**: https://docs.anthropic.com/claude-code
- **GitHub Help**: https://docs.github.com
- **Project Docs**: See docs/API.md after implementation

**You're ready to build! Start with Step 1.** 🚀

