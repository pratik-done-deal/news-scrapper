-- companies: one row per unique company name (exact string match)
CREATE TABLE IF NOT EXISTS companies (
    id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE
);

-- company_deals: links a company to a deal with its role
CREATE TABLE IF NOT EXISTS company_deals (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id),
    deal_id    UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('buyer', 'seller')),
    UNIQUE (company_id, deal_id, role)
);

CREATE INDEX IF NOT EXISTS idx_company_deals_company_id ON company_deals(company_id);
CREATE INDEX IF NOT EXISTS idx_company_deals_deal_id    ON company_deals(deal_id);

-- Backfill companies from existing buyer / seller values
INSERT INTO companies (name)
SELECT DISTINCT TRIM(buyer_name)
FROM deals
CROSS JOIN LATERAL unnest(string_to_array(buyer, ',')) AS buyer_name
WHERE buyer IS NOT NULL AND TRIM(buyer_name) != ''
ON CONFLICT (name) DO NOTHING;

INSERT INTO companies (name)
SELECT DISTINCT TRIM(seller_name)
FROM deals
CROSS JOIN LATERAL unnest(string_to_array(seller, ',')) AS seller_name
WHERE seller IS NOT NULL AND TRIM(seller_name) != ''
ON CONFLICT (name) DO NOTHING;

-- Backfill company_deals from existing buyer / seller values
INSERT INTO company_deals (company_id, deal_id, role)
SELECT c.id, d.id, 'buyer'
FROM deals d
CROSS JOIN LATERAL unnest(string_to_array(d.buyer, ',')) AS buyer_name
JOIN companies c ON c.name = TRIM(buyer_name)
WHERE d.buyer IS NOT NULL AND TRIM(buyer_name) != ''
ON CONFLICT (company_id, deal_id, role) DO NOTHING;

INSERT INTO company_deals (company_id, deal_id, role)
SELECT c.id, d.id, 'seller'
FROM deals d
CROSS JOIN LATERAL unnest(string_to_array(d.seller, ',')) AS seller_name
JOIN companies c ON c.name = TRIM(seller_name)
WHERE d.seller IS NOT NULL AND TRIM(seller_name) != ''
ON CONFLICT (company_id, deal_id, role) DO NOTHING;
