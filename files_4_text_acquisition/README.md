# Protest Event Analysis Pipeline

End-to-end pipeline for collecting and extracting structured protest event data
from news sources, with a focus on **Global South and non-Western contexts**.

---

## Architecture

```
GDELT DOC API  →  Full-text Scraper  →  Translator  →  Claude LLM  →  JSONL / CSV
(discovery)       (newspaper3k/BS4)     (langdetect     (extraction)   (output)
                                         + deep-
                                         translator)
```

### The 5 stages

| Stage | Module | What it does |
|-------|--------|-------------|
| 1. Discovery | `gdelt_discovery.py` | Queries GDELT DOC API for candidate article URLs filtered by country and keywords |
| 2. Scraping | `scraper.py` | Fetches full article text using newspaper3k with BeautifulSoup fallback |
| 3. Translation | `translator.py` | Detects language; translates non-English text via Google Translate (free tier) |
| 4. Extraction | `extractor.py` | Sends article text to Claude for structured protest event extraction |
| 5. Storage | `storage.py` | Saves events as JSONL (append-friendly), CSV (spreadsheet-ready), and run summary JSON |

---

## Setup

### 1. Create a virtual environment (recommended)
```bash
python -m venv venv
source venv/bin/activate    # macOS/Linux
venv\Scripts\activate       # Windows
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set your Anthropic API key
Create a `.env` file in this directory:
```
ANTHROPIC_API_KEY=sk-ant-...
```
Or export it in your shell:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Usage

### Basic run — last 7 days, key Global South countries
```bash
python pipeline.py
```

### Custom query and countries
```bash
python pipeline.py \
  --query "protest demonstration strike" \
  --countries ZA,NG,KE,GH,ET \
  --days 14
```

### Larger run, more articles
```bash
python pipeline.py \
  --query "protest strike rally march" \
  --countries IN,PK,BD,LK,NP \
  --days 30 \
  --max-articles 200 \
  --output-dir ./output/south_asia
```

### Skip translation (faster, if you only want English sources)
```bash
python pipeline.py --countries ZA,NG,GH --no-translate
```

---

## Country Codes (Global South focus)

### Africa
| Code | Country | Code | Country |
|------|---------|------|---------|
| ZA | South Africa | NG | Nigeria |
| KE | Kenya | ET | Ethiopia |
| GH | Ghana | TZ | Tanzania |
| UG | Uganda | SN | Senegal |
| ZW | Zimbabwe | SD | Sudan |

### Asia & Middle East
| Code | Country | Code | Country |
|------|---------|------|---------|
| IN | India | PK | Pakistan |
| BD | Bangladesh | ID | Indonesia |
| PH | Philippines | MM | Myanmar |
| TH | Thailand | VN | Vietnam |
| EG | Egypt | IQ | Iraq |

### Latin America
| Code | Country | Code | Country |
|------|---------|------|---------|
| BR | Brazil | MX | Mexico |
| CO | Colombia | AR | Argentina |
| PE | Peru | VE | Venezuela |

---

## Output Files

Each pipeline run creates timestamped files in `./output/`:

```
output/
├── events_20240321_143022.jsonl    # one event per line (primary output)
├── events_20240321_143022.csv      # spreadsheet-friendly
├── summary_20240321_143022.json    # run metadata + counts
└── all_events.jsonl                # cumulative — all runs appended here
```

### Event Schema

Each extracted event contains these fields:

| Field | Description |
|-------|-------------|
| `event_date` | Date of protest (YYYY-MM-DD) |
| `country` | Country where protest occurred |
| `city` | City/town |
| `region` | State or province |
| `event_type` | protest / strike / riot / march / etc. |
| `organizer` | Organization that called the event |
| `participant_groups` | Demographics/groups who participated |
| `claims` | List of demands or grievances |
| `crowd_size` | Numeric or descriptive estimate |
| `state_response` | Police/military response type |
| `arrests` | Number or description of arrests |
| `fatalities` | Deaths reported |
| `injuries` | Injuries reported |
| `outcome` | How the event ended |
| `confidence` | LLM's confidence: high / medium / low |
| `article_url` | Source article URL |
| `source_language` | Original language of article |

---

## Notes on Global South Coverage

**GDELT's strengths for this use case:**
- Monitors local-language sources in 100+ languages
- Covers regional African, Asian, and Latin American outlets
- Updated every 15 minutes — near real-time

**Known limitations:**
- Over-represents English-language and wire service coverage
- Some countries (esp. sub-Saharan Africa) have sparser coverage
- GDELT's own event coding has noise — this pipeline uses it only for discovery

**To improve coverage for specific regions:**
- Add regional sources manually (see `scraper.py` — you can feed it URLs directly)
- Use the `--query` parameter with local-language keywords (GDELT translates these)
- Consider supplementing with ReliefWeb API for humanitarian crisis contexts

---

## Extending the Pipeline

### Add a new data source
Edit `gdelt_discovery.py` or create a new discovery module (e.g. `reliefweb_discovery.py`)
that returns article dicts with the same schema.

### Customize the extraction schema
Edit the `SYSTEM_PROMPT` in `extractor.py` to add, remove, or rename fields.
The schema is fully configurable.

### Run on a schedule
```bash
# Add to crontab — run daily at 6am
0 6 * * * cd /path/to/protest_pipeline && python pipeline.py >> logs/cron.log 2>&1
```
