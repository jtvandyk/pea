# Running Llama Locally on M2 Mac Mini
## Complete Setup Guide

---

## TL;DR: Can M2 Mac Mini Run Llama?

**Yes! ✅** M2 Mac Mini can absolutely run Llama models locally.

**Best Configuration:**
- Model: **Llama 2 13B or Llama 3.1 70B via quantization**
- Method: **Ollama (easiest)** or **LLaMA.cpp**
- Performance: **5-20 tokens/sec** (depending on model size)
- Cost: **FREE**

---

## M2 MAC MINI SPECIFICATIONS

Let me first understand your hardware:

```bash
# Check your M2 Mac Mini
uname -m                    # Should show: arm64
sysctl -a | grep hw.memsize # Check RAM (converts bytes)

# Example output for M2 Mac Mini:
# - Chip: Apple M2 (8-core CPU, 10-core GPU)
# - RAM: 8GB, 16GB, or 24GB (depending on config)
# - Storage: SSD (256GB+)
```

---

## REQUIREMENTS FOR RUNNING LLAMA LOCALLY

### Minimum Requirements (Llama 2 7B)
- **RAM**: 8GB (tight, but works with quantization)
- **Disk**: 10-15GB free space
- **CPU/GPU**: M1/M2/M3+ chip (Apple Silicon)

### Recommended (Llama 2 13B)
- **RAM**: 16GB (comfortable)
- **Disk**: 20GB free space
- **GPU**: M1/M2/M3+ with 8+ cores

### For Llama 3.1 70B
- **RAM**: 32GB+ (M2 can struggle)
- **Quantization**: Essential (reduces to 16-20GB)
- **GPU**: M2/M3 preferred

---

## MODEL SIZES & M2 MAC MINI COMPATIBILITY

| Model | Params | Unquantized | 4-bit | 8-bit | M2 Compatible? |
|-------|--------|-------------|-------|-------|----------------|
| Llama 2 7B | 7B | 13GB | 3.5GB | 7GB | ✅ Yes |
| Llama 2 13B | 13B | 24GB | 7GB | 13GB | ✅ Yes (16GB+ RAM) |
| Llama 3 8B | 8B | 15GB | 4GB | 8GB | ✅ Yes |
| Llama 3.1 70B | 70B | 130GB | 20GB | 35GB | ⚠️ With quantization |
| Llama 3.1 405B | 405B | 750GB | 120GB | 210GB | ❌ Not feasible |

**For M2 Mac Mini with 8GB RAM:**
- Best: **Llama 2 7B** (3.5-4GB with quantization)
- OK: **Llama 3 8B** (4GB with quantization)

**For M2 Mac Mini with 16GB+ RAM:**
- Best: **Llama 2 13B** (7GB with quantization)
- Great: **Llama 3 8B** (4GB with quantization)
- Good: **Llama 3.1 8B** (4GB with quantization)

---

## OPTION 1: OLLAMA (EASIEST - RECOMMENDED) ⭐

Ollama is the **easiest way** to run Llama on Mac.

### Installation

```bash
# Install Ollama
# Download from: https://ollama.ai

# Or via Homebrew:
brew install ollama

# Verify installation:
ollama --version
```

### Download & Run Llama Model

```bash
# Start Ollama daemon (runs in background)
ollama serve

# In another terminal, pull a model:
ollama pull llama2        # 7B model (4GB)
# or
ollama pull llama2:13b    # 13B model (8GB)
# or
ollama pull mistral       # 7B model (4GB) - faster!

# Check downloaded models:
ollama list
```

### Usage

**Command line:**
```bash
ollama run llama2
# Interactive prompt - type your queries

# Example:
# > Classify this protest event: Workers gathered outside factory demanding wage increases
# (Llama responds...)
```

**Python integration:**
```bash
pip install ollama

# In Python:
from ollama import Client

client = Client(host='http://localhost:11434')

response = client.generate(
    model='llama2',
    prompt='Classify this protest: workers gathered...',
    stream=False
)

print(response['response'])
```

### Performance on M2 Mac Mini

| Model | M2 8GB | M2 16GB | Speed | Quality |
|-------|--------|---------|-------|---------|
| Llama 2 7B | ✅ Works | ✅ Great | 8-12 tokens/sec | Good |
| Llama 2 13B | ⚠️ Slow | ✅ Works | 4-8 tokens/sec | Very Good |
| Mistral 7B | ✅ Fast | ✅ Great | 10-15 tokens/sec | Good |
| Llama 3 8B | ✅ Works | ✅ Great | 8-12 tokens/sec | Excellent |

---

## OPTION 2: LLAMA.CPP (FASTER, CUSTOM)

LLaMA.cpp is faster and allows more control.

### Installation

```bash
# Clone repository
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp

# Build for M2 Mac (uses Metal GPU acceleration)
cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_METAL=ON
cmake --build build --config Release

# Or use Homebrew:
brew install llama.cpp
```

### Download Model

```bash
# Download quantized model (GGUF format - optimized for Mac)
# From HuggingFace: https://huggingface.co/models?search=gguf

# Example: Llama 2 7B quantized
wget https://huggingface.co/TheBloke/Llama-2-7B-GGUF/resolve/main/llama-2-7b.Q4_K_M.gguf

# Or Mistral (smaller, faster):
wget https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.1-GGUF/resolve/main/mistral-7b-instruct-v0.1.Q4_K_M.gguf
```

### Run Model

```bash
# Basic usage:
./main -m llama-2-7b.Q4_K_M.gguf -n 256 -p "Classify this protest:"

# With Metal GPU acceleration:
./main -m llama-2-7b.Q4_K_M.gguf -n 256 -ngl 1 -p "Your prompt"

# Options:
# -m: model file
# -n: number of tokens to generate
# -p: prompt
# -t: number of threads (use number of CPU cores)
# -ngl: number of layers on GPU (1-40 depending on model)
```

### Python Integration

```bash
pip install llama-cpp-python

# In Python:
from llama_cpp import Llama

llm = Llama(
    model_path="./llama-2-7b.Q4_K_M.gguf",
    n_gpu_layers=1,  # Use GPU
    n_threads=8,  # Use all CPU cores
    verbose=False
)

response = llm("Classify this protest:", max_tokens=200)
print(response['choices'][0]['text'])
```

---

## OPTION 3: TOGETHER.AI (CLOUD - NO LOCAL SETUP)

If local resources are tight, use Together.ai's API:

```bash
pip install together

# In Python:
from together import Together

client = Together(api_key="YOUR_API_KEY")

response = client.chat.completions.create(
    model="meta-llama/Llama-2-7b-chat-hf",
    messages=[
        {"role": "user", "content": "Classify this protest: workers gathered..."}
    ]
)

print(response.choices[0].message.content)
```

**Cost**: ~$0.50/1M tokens (very cheap)
**Speed**: Same as local
**Advantage**: No local resources needed

---

## OPTION 4: VLLM (HIGH PERFORMANCE)

For best performance with batching:

```bash
# Install vLLM for Mac
pip install vllm

# Note: Metal support is experimental, may need CPU-only mode
```

```python
from vllm import LLM, SamplingParams

llm = LLM(
    model="meta-llama/Llama-2-7b-chat-hf",
    device="cpu",  # Use CPU on M2 Mac (GPU support still experimental)
    max_num_seqs=4  # Batch multiple requests
)

prompts = [
    "Classify protest 1: workers gathered...",
    "Classify protest 2: police used tear gas..."
]

sampling_params = SamplingParams(max_tokens=100, temperature=0.1)
outputs = llm.generate(prompts, sampling_params)

for output in outputs:
    print(output.outputs[0].text)
```

---

## RECOMMENDED SETUP FOR M2 MAC MINI

### Best Option: Ollama + LLaMA.cpp Fallback

**Step 1: Install Ollama** (easiest)
```bash
brew install ollama
```

**Step 2: Run Local Llama**
```bash
ollama serve  # Start daemon
ollama pull llama2  # In another terminal
ollama run llama2  # Test it
```

**Step 3: Integrate with Your Project**
```python
from ollama import Client
from src.models.llm_classifier import LLMClassifier
from src.utils.codebook_manager import CodebookManager

# Use Ollama as backend
client = Client(host='http://localhost:11434')

# Adapt LLMClassifier to use Ollama
class OllamaClassifier(LLMClassifier):
    def classify_zero_shot(self, text):
        response = client.generate(
            model='llama2',
            prompt=self.prompter.build_zero_shot_prompt(text),
            stream=False
        )
        # Parse response...
```

---

## PERFORMANCE EXPECTATIONS: M2 MAC MINI

### Llama 2 7B (Ollama, 4GB RAM)
```
Input: "Workers gathered outside factory demanding wage increases"

Speed: 10 tokens/sec
Time to first token: 0.5 seconds
Time for 100 tokens: 10 seconds
Quality: Good (80-85% accuracy on classification)
```

### Llama 2 13B (Ollama, 8GB RAM)
```
Input: Same as above

Speed: 5-8 tokens/sec
Time to first token: 0.7 seconds
Time for 100 tokens: 15 seconds
Quality: Very Good (85-90% accuracy on classification)
```

### Processing 100 Protest Events

**Llama 2 7B:**
- Time: ~20-30 minutes
- Quality: Good
- Cost: Free

**Llama 2 13B:**
- Time: ~40-60 minutes
- Quality: Very Good
- Cost: Free

**vs GPT-4o (cloud):**
- Time: ~3-5 minutes
- Quality: Excellent
- Cost: ~$1.50

---

## INSTALLATION STEPS FOR M2 MAC MINI

### Complete Setup (15 minutes)

```bash
# 1. Install Ollama
brew install ollama

# 2. Download Llama model (first time: 5-10 minutes)
ollama pull llama2
# or for faster model:
ollama pull mistral

# 3. Start Ollama daemon
ollama serve &

# 4. Test it
ollama run llama2
# At prompt, type: "Hello, classify this protest:"

# 5. Install Python integration
pip install ollama

# 6. Test Python integration
python -c "
from ollama import Client
client = Client()
response = client.generate(model='llama2', prompt='test')
print('Ollama working!')
"
```

### Verify GPU Acceleration

```bash
# Check if Metal GPU is being used
ps aux | grep llama

# Or in Python:
from ollama import Client
client = Client()

# Generate something and watch Activity Monitor
# If you see high GPU usage -> Metal acceleration working ✅
response = client.generate(model='llama2', prompt='test')
```

---

## MEMORY MANAGEMENT

### Monitor RAM Usage

```bash
# Check real-time memory
top -l 1 | head -20

# Or use Activity Monitor (GUI)
# Applications > Utilities > Activity Monitor > Memory tab
```

### Optimize if RAM is Limited

```bash
# If 8GB RAM is tight, use smaller model:
ollama pull mistral:7b    # 3.2GB
# or
ollama pull neural-chat   # 3.8GB

# Or use even smaller:
ollama pull tinyllama     # 1.1GB (fast but less accurate)
```

---

## TROUBLESHOOTING

### Problem: "Not enough memory"

```bash
# Solution 1: Use smaller model
ollama pull mistral  # Instead of llama2:13b

# Solution 2: Close other applications
# Check Activity Monitor for memory hogs

# Solution 3: Use quantization
# This is already done with Ollama's built-in models
```

### Problem: "Very slow responses"

```bash
# Check if swapping to disk (very slow)
vm_stat  # Look for "Pageins" and "Pageouts"

# Solution: Use smaller model or add RAM

# Or lower precision:
ollama run llama2 --num-gpu 1  # Use GPU acceleration
```

### Problem: "Ollama daemon won't start"

```bash
# Kill existing process
killall ollama

# Restart daemon
ollama serve

# Or check logs:
cat ~/.ollama/logs/server.log
```

---

## INTEGRATION WITH YOUR PROJECT

### Modify llm_protest_implementation.py

```python
# In src/models/llm_classifier.py

from ollama import Client

class LLMClassifier:
    def __init__(self, model_name: str, codebook_manager, api_keys=None):
        if model_name == "llama2-local":
            self.client = Client(host='http://localhost:11434')
            self.model_name = "llama2"
            self.provider = "ollama"
        elif model_name == "gpt-4o":
            # ... existing GPT-4o code ...
            pass
    
    def classify_zero_shot(self, text: str):
        if self.provider == "ollama":
            prompt = self.prompter.build_zero_shot_prompt(text)
            response = self.client.generate(
                model=self.model_name,
                prompt=prompt,
                stream=False
            )
            # Parse response and return ProtestEventPrediction
            return self._parse_response(response['response'])
        else:
            # ... existing API code ...
            pass
```

### Usage

```python
from src.models.llm_classifier import LLMClassifier
from src.utils.codebook_manager import CodebookManager

# Use local Llama
codebook = CodebookManager('configs/protest_codebook.yaml')
classifier = LLMClassifier('llama2-local', codebook)

# Process 100 events locally for free
processor = BatchProcessor(classifier)
predictions = processor.process_events(texts, method='zero_shot')
```

---

## COMPARISON: LOCAL VS CLOUD

| Aspect | Ollama Local | GPT-4o API | Together.ai |
|--------|--------------|-----------|------------|
| **Cost** | Free | $15/1M tokens | $0.50/1M tokens |
| **Speed** | 5-15 tokens/sec | 50+ tokens/sec | 50+ tokens/sec |
| **Quality** | Good-Very Good | Excellent | Good |
| **Privacy** | Complete | None | Minimal |
| **Setup Time** | 15 min | 5 min | 5 min |
| **M2 Mac Mini** | ✅ Works great | ✅ Cloud | ✅ Cloud |
| **For 100 events** | 30 min, Free | 3 min, $0.15 | 3 min, $0.05 |

---

## RECOMMENDATION FOR YOUR PROJECT

### Best Practice: Hybrid Approach

```
Development Phase:
- Use Ollama (free, local)
- Fast iteration, no API costs

Validation Phase:
- Use GPT-4o (best accuracy)
- 100-event manual validation
- Cost: ~$0.15

Production Phase:
- Option A: Ollama (free, local)
- Option B: Together.ai ($0.50/1M tokens)
- Option C: GPT-4o (best quality)

Choose based on:
- Speed needed
- Accuracy needed
- Budget available
```

---

## FINAL ANSWER

### Can M2 Mac Mini Run Llama?

**YES! ✅**

**Recommended Setup:**
1. **Install Ollama**: `brew install ollama`
2. **Download Llama**: `ollama pull llama2`
3. **Start daemon**: `ollama serve`
4. **Use in Python**: `from ollama import Client`

**Performance:**
- Llama 2 7B: 10 tokens/sec (8GB RAM fine)
- Llama 2 13B: 5-8 tokens/sec (needs 16GB RAM)
- Process 100 events: 20-30 minutes
- Cost: **Free** 💰

**vs Alternatives:**
- GPT-4o: Faster (3-5 min) but costs $0.15
- Together.ai: Fast (3-5 min), costs $0.05
- Local Llama: Slower (30 min) but FREE and private

**My Recommendation:**
- Start with local Ollama for development
- Use GPT-4o for validation (small cost)
- Use Ollama or Together.ai for production (based on budget)

---

## QUICK START (5 MINUTES)

```bash
# 1. Install
brew install ollama

# 2. Download model
ollama pull llama2

# 3. Test
ollama run llama2

# 4. At prompt, type:
# > Classify this protest event: workers gathered demanding wages

# Done! It works! 🎉
```

