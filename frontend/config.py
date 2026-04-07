from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BACKEND_URL = os.getenv("AGENTIC_BACKEND_URL", "http://localhost:8000")
DEFAULT_HTTP_TIMEOUT_SECONDS = float(os.getenv("AGENTIC_HTTP_TIMEOUT_SECONDS", "60"))

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"

EXAMPLE_DATASETS = [
    {
        "label": "Retail Sales",
        "filename": "retail_sales.csv",
        "description": "Good for profiling, cleaning, and raw-vs-cleaned comparison demos.",
    },
    {
        "label": "Support Tickets",
        "filename": "support_tickets.csv",
        "description": "Useful for operational analytics and triage workflows.",
    },
    {
        "label": "Marketing Leads",
        "filename": "marketing_leads.csv",
        "description": "Best fit for segmentation and chart-generation demos.",
    },
]

DEMO_PROMPTS = [
    (
        "Profile retail sales",
        "I uploaded retail_sales.csv. Profile the dataset, highlight the main quality risks, and recommend a safe cleaning plan.",
    ),
    (
        "Compare raw vs cleaned",
        "Compare retail_sales.csv with analysis/retail_sales_cleaned.csv and export a concise markdown report with the main differences.",
    ),
    (
        "Segment marketing leads",
        "Use marketing_leads.csv to create a useful segmentation, explain the segments, and generate a supporting visualization.",
    ),
]
