ALTER TABLE company_deals DROP CONSTRAINT IF EXISTS company_deals_role_check;
ALTER TABLE company_deals ADD CONSTRAINT company_deals_role_check
    CHECK (role IN ('buyer', 'seller', 'investor', 'company'));
