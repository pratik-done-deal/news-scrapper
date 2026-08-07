import json
import logging
import time
from typing import Optional

from groq import Groq
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

GROQ_REQUEST_DELAY_SECONDS = 10

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

IMPORTANT RULES:
1. Extract ALL deals — including deals that are only announced, in talks, or pending regulatory approval. A deal does NOT need to be closed/completed to be extracted.
2. If a deal is announced but not yet closed, still populate all fields and clearly note the pending/announced status in the summary field.
3. If the article is NOT about a deal (e.g. product launch, earnings report, leadership change with no deal), return all fields as null.

Extract the following fields and return ONLY valid JSON:

- buyer: For acquisitions/mergers — the acquiring company. For funding rounds — the investor(s), comma-separated if multiple. Null if not applicable.
  Always use the company's clean trading name — omit legal suffixes like "Pvt. Ltd.", "Private Limited", "Ltd.", "Inc.", "Corp.", "LLP", etc. (e.g. write "Tata Sons" not "Tata Sons Pvt. Ltd.").
- seller: For acquisitions/mergers — the company being acquired. For funding rounds — the company receiving the investment. Null if not applicable.
  Same rule: omit legal suffixes from the company name.
- target_company: The company the deal is *about* — whose shares, stake or assets change hands — when that company is neither the buyer nor the seller. Null if the subject is already named as buyer or seller.
  This matters most for stake sales, block/bulk deals and secondary transactions: when investor X sells shares *of* listed company Y, the buyer is the purchaser, the seller is X, and target_company is "Y".
  Same rule: omit legal suffixes from the company name.
- deal_value: Monetary value as stated in the article, e.g. "$2.5 billion" (null if not mentioned)
- sector: Must be exactly one of: {sectors}
- sub_sector: Only required when sector is "D2C", "Fintech", or "Others".
  - If sector is "D2C", choose from: {d2c_sub}
  - If sector is "Fintech", choose from: {fintech_sub}
  - If sector is "Others", choose from: {others_sub}
  - For all other sectors, set to null
- country: Primary country where the deal is happening
- deal_type: Classify the deal type using one of — funding_round, acquisition, merger, joint_venture, divestiture, partnership, other
  - Use "funding_round" for any funding round (seed, Series A/B/C, etc.)
  - Use "acquisition" for any acquisition deal, whether closed or just announced/pending
  - Use "merger" for mergers, "joint_venture" for JVs, etc.
- summary: A 2–3 sentence summary for a business analyst. Include who is involved, what is happening, the deal value if known, whether the deal is closed or still pending/announced, and why it matters.

---

EXAMPLES:

### Example 1 — Closed Acquisition
Title: Tata Sons completes acquisition of Air India for ₹18,000 crore
Content: Tata Sons has successfully completed the acquisition of Air India from the Government of India for ₹18,000 crore. The deal, which was approved by the Competition Commission of India, marks the return of the airline to its original founders after 69 years of government ownership. Tata Sons plans to merge Air India with Vistara to create a full-service carrier.

Output:
{{
  "buyer": "Tata Sons",
  "seller": "Government of India (Air India)",
  "target_company": "Air India",
  "deal_value": "₹18,000 crore",
  "sector": "Others",
  "sub_sector": "Automobile",
  "country": "India",
  "deal_type": "acquisition",
  "summary": "Tata Sons has completed the acquisition of Air India from the Government of India for ₹18,000 crore, bringing the airline back to its original founders after 69 years. The deal was approved by CCI. Tata Sons intends to merge Air India with Vistara to build a competitive full-service carrier."
}}

### Example 2 — Announced / Pending Deal (not yet closed)
Title: Reliance Industries in talks to acquire Mandhana Retail Ventures for ₹900 crore
Content: Reliance Industries is reportedly in advanced discussions to acquire Mandhana Retail Ventures, the fashion retailer behind the Being Human brand. The deal, valued at approximately ₹900 crore, has not been finalised yet and is subject to due diligence and board approvals. Both parties have declined to comment officially.

Output:
{{
  "buyer": "Reliance Industries",
  "seller": "Mandhana Retail Ventures",
  "target_company": null,
  "deal_value": "₹900 crore",
  "sector": "D2C",
  "sub_sector": "Apparel",
  "country": "India",
  "deal_type": "acquisition",
  "summary": "Reliance Industries is in advanced talks to acquire Mandhana Retail Ventures (Being Human brand) for approximately ₹900 crore, though the deal is not yet closed and remains subject to due diligence and board approvals. This move would strengthen Reliance's position in the fashion retail segment if completed."
}}

### Example 3 — Funding Round
Title: Fintech startup Slice raises $220 million in Series B led by Tiger Global
Content: Bengaluru-based fintech startup Slice has raised $220 million in a Series B funding round led by Tiger Global Management, with participation from Insight Partners and Blume Ventures. The funds will be used to expand its credit card and lending products to tier-2 and tier-3 cities across India.

Output:
{{
  "buyer": "Tiger Global Management, Insight Partners, Blume Ventures",
  "seller": "Slice",
  "target_company": null,
  "deal_value": "$220 million",
  "sector": "Fintech",
  "sub_sector": "Lending/Wealthtech",
  "country": "India",
  "deal_type": "funding_round",
  "summary": "Slice, a Bengaluru-based fintech, raised $220 million in a Series B round led by Tiger Global, with Insight Partners and Blume Ventures participating. The capital will support expansion of its credit and lending products into tier-2 and tier-3 Indian cities."
}}

### Example 4 — PE/VC Fund Close (fund raise by a fund manager, no specific investee company)
Title: Bain Capital raises $10.5 billion for Asia Fund VI
Content: Bain Capital partners, employees, and related entities committed the balance of capital and collectively are the single largest investor in the fund — which exceeded its original target of $7 billion.

Output:
{{
  "buyer": "Bain Capital",
  "seller": null,
  "target_company": null,
  "deal_value": "$10.5 billion",
  "sector": "Others",
  "sub_sector": null,
  "country": null,
  "deal_type": "funding_round",
  "summary": "Bain Capital has closed its Asia Fund VI at $10.5 billion, exceeding its original $7 billion target. The fund will invest across Technology, Industrials, Consumer, Healthcare, and Business and Financial Services in Asia. No specific investee company has been named yet."
}}

### Example 5 — Stake Sale / Block Deal (the listed company is neither buyer nor seller)
Title: Nexus Venture Partners offloads Rs 530 Cr stake in Delhivery via block deals
Content: Nexus Venture Partners sold 1.1 crore shares of logistics firm Delhivery for approximately Rs 530 crore through block deals on the NSE. Morgan Stanley and Goldman Sachs were among the buyers. Nexus, an early backer of the company, has been steadily paring its holding since Delhivery's listing.

Output:
{{
  "buyer": "Morgan Stanley, Goldman Sachs",
  "seller": "Nexus Venture Partners",
  "target_company": "Delhivery",
  "deal_value": "Rs 530 crore",
  "sector": "Others",
  "sub_sector": "Logistics",
  "country": "India",
  "deal_type": "divestiture",
  "summary": "Nexus Venture Partners sold 1.1 crore shares of Delhivery for around Rs 530 crore via block deals on the NSE, with Morgan Stanley and Goldman Sachs among the buyers. The completed sale continues the early backer's steady exit from the listed logistics company."
}}

### Example 6 — Non-Deal News (return all nulls)
Title: Infosys reports 8% growth in Q3 revenue, beats analyst estimates
Content: Infosys reported an 8% year-on-year increase in revenue for the third quarter, beating consensus analyst estimates. The company's CEO attributed the growth to strong deal wins in the North American market. Infosys also raised its full-year revenue guidance to 8–10%.

Output:
{{
  "buyer": null,
  "seller": null,
  "target_company": null,
  "deal_value": null,
  "sector": null,
  "sub_sector": null,
  "country": null,
  "deal_type": null,
  "summary": null
}}

---

Now extract from the article below:

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
            start = time.monotonic()
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            elapsed = time.monotonic() - start
            logger.info(f"Groq request took {elapsed:.2f}s (model={self.model})")

            raw = json.loads(response.choices[0].message.content)
            return DealData(**raw)
        except Exception as e:
            logger.error(f"Extraction LLM call failed: {e}")
            return None
        finally:
            time.sleep(GROQ_REQUEST_DELAY_SECONDS)
