import json
import logging
import time
from typing import Optional

from pydantic import BaseModel, field_validator

from ..llm_client import GeminiChatClient

logger = logging.getLogger(__name__)

LLM_REQUEST_DELAY_SECONDS = 10

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
You are a financial analyst extracting structured deal data from M&A and business news. Return ONLY valid JSON.

Rules:
- Extract announced, in-talks and pending-approval deals too, not just closed ones — note the status in `summary`.
- If the article is not about a deal (product launch, earnings, leadership change), return every field as null.
- Company names: clean trading name only, no legal suffixes ("Pvt. Ltd.", "Ltd.", "Inc.", "Corp.", "LLP").

Fields:
- buyer: the acquirer; for funding rounds, the investor(s), comma-separated. Null if none.
- seller: the company being acquired; for funding rounds, the company receiving the investment. Null if none.
- target_company: the company whose shares/stake/assets change hands when it is neither buyer nor seller — stake sales, block deals, secondaries (investor X sells shares of listed company Y → seller=X, target_company=Y). Null otherwise.
- deal_value: as stated in the article, e.g. "$2.5 billion". Null if not mentioned.
- sector: exactly one of: {sectors}
- sub_sector: only when sector is D2C ({d2c_sub}); Fintech ({fintech_sub}); Others ({others_sub}). Null for all other sectors.
- country: primary country where the deal is happening.
- deal_type: one of funding_round (any seed/Series round or PE/VC fund close), acquisition, merger, joint_venture, divestiture, partnership, other.
- summary: 2–3 sentences for a business analyst — who is involved, what is happening, the value if known, closed vs pending, and why it matters.

EXAMPLES (article → output)

1. Pending acquisition — "Reliance Industries in talks to acquire Mandhana Retail Ventures for ₹900 crore"; advanced discussions on the Being Human fashion retailer, subject to due diligence and board approvals.
{{"buyer": "Reliance Industries", "seller": "Mandhana Retail Ventures", "target_company": null, "deal_value": "₹900 crore", "sector": "D2C", "sub_sector": "Apparel", "country": "India", "deal_type": "acquisition", "summary": "Reliance Industries is in advanced talks to acquire Mandhana Retail Ventures, the fashion retailer behind Being Human, for approximately ₹900 crore. The deal is not yet closed and remains subject to due diligence and board approvals. It would strengthen Reliance's position in fashion retail if completed."}}

2. Funding round — "Fintech startup Slice raises $220 million in Series B led by Tiger Global"; Insight Partners and Blume Ventures participated; funds to expand credit and lending into tier-2/3 Indian cities.
{{"buyer": "Tiger Global Management, Insight Partners, Blume Ventures", "seller": "Slice", "target_company": null, "deal_value": "$220 million", "sector": "Fintech", "sub_sector": "Lending/Wealthtech", "country": "India", "deal_type": "funding_round", "summary": "Slice, a Bengaluru-based fintech, raised $220 million in a closed Series B round led by Tiger Global, with Insight Partners and Blume Ventures participating. The capital will support expansion of its credit and lending products into tier-2 and tier-3 Indian cities."}}

3. PE/VC fund close, no investee named — "Bain Capital raises $10.5 billion for Asia Fund VI", exceeding its $7 billion target.
{{"buyer": "Bain Capital", "seller": null, "target_company": null, "deal_value": "$10.5 billion", "sector": "Others", "sub_sector": null, "country": null, "deal_type": "funding_round", "summary": "Bain Capital has closed its Asia Fund VI at $10.5 billion, exceeding its original $7 billion target. The fund will invest across technology, industrials, consumer, healthcare and financial services in Asia. No specific investee company has been named yet."}}

4. Stake sale / block deal — "Nexus Venture Partners offloads Rs 530 Cr stake in Delhivery via block deals"; the early backer sold 1.1 crore shares of the listed logistics firm on the NSE, with Morgan Stanley and Goldman Sachs among the buyers.
{{"buyer": "Morgan Stanley, Goldman Sachs", "seller": "Nexus Venture Partners", "target_company": "Delhivery", "deal_value": "Rs 530 crore", "sector": "Others", "sub_sector": "Logistics", "country": "India", "deal_type": "divestiture", "summary": "Nexus Venture Partners sold 1.1 crore shares of Delhivery for around Rs 530 crore via block deals on the NSE, with Morgan Stanley and Goldman Sachs among the buyers. The completed sale continues the early backer's steady exit from the listed logistics company."}}

5. Non-deal news — "Infosys reports 8% growth in Q3 revenue, beats analyst estimates".
{{"buyer": null, "seller": null, "target_company": null, "deal_value": null, "sector": null, "sub_sector": null, "country": null, "deal_type": null, "summary": null}}

Now extract from the article below.

Title: {title}
Content: {content}
"""


class DealData(BaseModel):
    buyer: Optional[str] = None
    seller: Optional[str] = None
    # The company the deal is about when it is neither buyer nor seller — a stake
    # sale names the investor and the purchaser, so without this the listed
    # company whose shares moved would never reach the graph.
    target_company: Optional[str] = None
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
        normalised = v.lower()
        if normalised == "funding":
            return "funding_round"
        allowed = {
            "acquisition", "merger", "joint_venture",
            "funding_round", "divestiture", "partnership", "other",
        }
        return normalised if normalised in allowed else "other"


class DealExtractor:
    def __init__(self, client: GeminiChatClient, model: str):
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
            start = time.monotonic()
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            elapsed = time.monotonic() - start
            logger.info(f"LLM request took {elapsed:.2f}s (model={self.model})")

            raw = json.loads(response.choices[0].message.content)
            # Weekly roundups ("Indian startups raised $252M this week") cover
            # dozens of deals, and the model answers with a LIST of them. The
            # graph stores exactly one deal per article — `d.article_id` is
            # uniquely constrained — so there is nowhere to put the rest, and
            # keeping an arbitrary one would attribute the whole article's
            # value to a single startup. Skip the article and say so loudly:
            # a WARNING makes these countable in the logs, which is what a
            # later decision about real multi-deal support will need.
            if isinstance(raw, list):
                logger.warning(
                    "Skipping multi-deal article — model returned %d deals but the "
                    "schema holds one per article: %r",
                    len(raw),
                    (title or "(no title)")[:100],
                )
                return None
            return DealData(**raw)
        except Exception as e:
            logger.error(f"Extraction LLM call failed: {e}")
            return None
        finally:
            time.sleep(LLM_REQUEST_DELAY_SECONDS)
