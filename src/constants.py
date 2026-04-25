"""
Shared constants for the PEA pipeline.

Centralises event type keys, confidence score mappings, and country
lookups that were previously duplicated across extractor.py,
processing.py, predictions.py, and web/app.py.
"""

import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]

CONFIGS_DIR: Path = _REPO_ROOT / "configs"

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

VALID_EVENT_TYPES: frozenset = frozenset(
    {
        "demonstration_march",
        "strike_boycott",
        "occupation_seizure",
        "confrontation",
        "petition_signature",
        "vigil",
        "hunger_strike",
        "riot",
    }
)

# ---------------------------------------------------------------------------
# Confidence score mappings
# ---------------------------------------------------------------------------

# Tier → float quality score.  Used in QC reports and statistical predictions.
CONF_FLOAT_SCORE: dict = {
    "high": 0.85,
    "medium": 0.70,
    "low": 0.50,
}

# Tier → integer ranking.  Used when choosing the better of two duplicate events.
CONF_RANK_SCORE: dict = {
    "high": 3,
    "medium": 2,
    "low": 1,
}

# ---------------------------------------------------------------------------
# Shared config paths
# ---------------------------------------------------------------------------

KEYWORDS_PATH: Path = CONFIGS_DIR / "keywords.yaml"

# ---------------------------------------------------------------------------
# Country data (loaded from configs/countries.yaml)
# ---------------------------------------------------------------------------


def _load_country_data() -> dict:
    """Load configs/countries.yaml and build lookup dicts."""
    _empty: dict = {
        "list": [],
        "iso2_to_name": {},
        "iso2_to_iso3": {},
        "iso2_to_fips": {},
        "target_names": frozenset(),
        "web_display": {},
    }
    try:
        with open(CONFIGS_DIR / "countries.yaml", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.error(
            "configs/countries.yaml not found — country lookups disabled; check your deployment"
        )
        return _empty
    except Exception as e:
        log.error("Could not load countries.yaml: %s", e, exc_info=True)
        return _empty

    countries = raw.get("countries", [])
    iso2_to_name: dict = {}
    iso2_to_iso3: dict = {}
    iso2_to_fips: dict = {}
    target_names: set = set()
    web_display: dict = {}

    for c in countries:
        iso2 = c.get("iso2", "")
        name = c.get("name", "")
        if not iso2:
            continue
        if name:
            iso2_to_name[iso2] = name
            if c.get("target"):
                web_display[name] = iso2
        if c.get("iso3"):
            iso2_to_iso3[iso2] = c["iso3"]
        if c.get("fips"):
            iso2_to_fips[iso2] = c["fips"]
        if c.get("target"):
            if name:
                target_names.add(name.lower())
            for alias in c.get("aliases", []):
                target_names.add(alias.lower())

    return {
        "list": countries,
        "iso2_to_name": iso2_to_name,
        "iso2_to_iso3": iso2_to_iso3,
        "iso2_to_fips": iso2_to_fips,
        "target_names": frozenset(target_names),
        "web_display": web_display,
    }


_COUNTRY_DATA = _load_country_data()

COUNTRY_LIST: list = _COUNTRY_DATA["list"]
ISO2_TO_NAME: dict = _COUNTRY_DATA["iso2_to_name"]
ISO2_TO_ISO3: dict = _COUNTRY_DATA["iso2_to_iso3"]
ISO2_TO_FIPS: dict = _COUNTRY_DATA["iso2_to_fips"]
TARGET_COUNTRY_NAMES: frozenset = _COUNTRY_DATA["target_names"]
# display name → ISO2, for UI dropdowns
WEB_COUNTRY_DISPLAY: dict = _COUNTRY_DATA["web_display"]
