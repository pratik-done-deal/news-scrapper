import json
import logging
from typing import Optional

from groq import Groq
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

SECTORS = [
    "D2C", "Edtech", "Fintech", "Gaming", "Agency", "Marketplace",
    "SaaS", "Others", "AI/Deeptech/IoT", "Healthcare Services",
    "Hospitality/Restaurants", "IT Services/Products", "B2B Services", "Renewables/EV",
]

SUB_SECTORS = {
    "D2C": ["Apparel", "B&P", "Personal Care", "F&B", "Footwear", "Healthcare", "H&H", "Jewellery", "Consumer Goods", "Others"],
    "Fintech": ["Insurance", "Lending/Wealthtech", "Payments", "Personal Finance", "Regulation Tech", "Others"],
    "Others": ["Agritech", "Automobile", "Crypto/Blockchain", "Cybersecurity", "Logistics", "Manufacturing/Exports", "Marketplace", "Media", "Real Estate/Proptech", "Sports/Fitness-tech"],
}

EXTRACTION_PROMPT = """\
You are an expert financial analyst extracting structured deal information from M&A and business news.

Extract the following fields and return ONLY valid JSON:

- buyer: Name of the acquiring company or investor (null if not applicable)
- seller: Name of the company being acquired or asset being sold (null if not applicable)
- deal_value: Monetary value as stated in the article, e.g. "$2.5 billion" (null if not mentioned)
- sector: Must be exactly one of: {sectors}
- sub_sector: Only required when sector is "D2C", "Fintech", or "Others".
  - If sector is "D2C", choose from: {d2c_sub}
  - If sector is "Fintech", choose from: {fintech_sub}
  - If sector is "Others", choose from: {others_sub}
  - For all other sectors, set to null
- country: Primary country where the deal is happening
- deal_type: One of — acquisition, merger, joint_venture, funding_round, divestiture, partnership, other
- summary: A 2–3 sentence natural language summary of the deal written for a business analyst. Include who is involved, what is happening, the deal value if known, and why it matters.

Title: {title}
Content: {content}
"""


class DealData(BaseModel):
    buyer: Optional[str] = None
    seller: Optional[str] = None
    deal_value: Optional[str] = None
    sector: Optional[str] = None
    sub_sector: Optional[str] = None
    country: Optional[str] = None
    deal_type: Optional[str] = None
    summary: Optional[str] = None

    @field_validator("sector")
    @classmethod
    def validate_sector(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # case-insensitive match
        for s in SECTORS:
            if s.lower() == v.lower():
                return s
        return "Others"

    @field_validator("sub_sector")
    @classmethod
    def validate_sub_sector(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        all_sub = [s for subs in SUB_SECTORS.values() for s in subs]
        for s in all_sub:
            if s.lower() == v.lower():
                return s
        return "Others"

    @field_validator("deal_type")
    @classmethod
    def normalise_deal_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {
            "acquisition", "merger", "joint_venture",
            "funding_round", "divestiture", "partnership", "other",
        }
        return v.lower() if v.lower() in allowed else "other"


class DealExtractor:
    def __init__(self, client: Groq, model: str):
        self.client = client
        self.model = model

    def extract(self, title: Optional[str], content: Optional[str]) -> Optional[DealData]:
        try:
            prompt = EXTRACTION_PROMPT.format(
                sectors=", ".join(SECTORS),
                d2c_sub=", ".join(SUB_SECTORS["D2C"]),
                fintech_sub=", ".join(SUB_SECTORS["Fintech"]),
                others_sub=", ".join(SUB_SECTORS["Others"]),
                title=title or "(no title)",
                content=(content or "")[:4000],
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            raw = json.loads(response.choices[0].message.content)
            return DealData(**raw)
        except Exception as e:
            logger.error(f"Extraction LLM call failed: {e}")
            return None
