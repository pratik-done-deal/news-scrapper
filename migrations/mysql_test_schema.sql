-- Test schema for the company MySQL database.
--
-- Reproduces only the surface that src/db/mysql_queries.py reads — `company`
-- (sellers), `buyer`, and `leads`. The production tables carry many more
-- columns; these are the ones the queries touch, plus the audit timestamps a
-- CRM table normally has.
--
-- Destructive: drops and recreates the three tables. Load it into a scratch
-- database (e.g. `company_db_test`), never the production DB:
--
--     python scripts/seed_test_company_db.py
--
-- The seed data below is deliberately messy. It includes rows every active
-- filter is supposed to exclude — blank names, junk/archived/delist/Inactive
-- sellers, non-lead `primary_id_type` values, dropped/converted leads, and a
-- NULL-status lead (excluded because `status NOT IN (...)` is NULL for NULL).

SET NAMES utf8mb4;

DROP TABLE IF EXISTS company;
DROP TABLE IF EXISTS buyer;
DROP TABLE IF EXISTS leads;

-- ---------------------------------------------------------------------------
-- company: sell-side mandates. `name` is the registered entity, `brand_name`
-- the name news coverage actually uses. `status` is nullable, and a NULL status
-- counts as active.
-- ---------------------------------------------------------------------------
CREATE TABLE company (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name        VARCHAR(255) DEFAULT NULL,
    brand_name  VARCHAR(255) DEFAULT NULL,
    website     VARCHAR(255) DEFAULT NULL,
    status      VARCHAR(32)  DEFAULT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_company_name (name),
    KEY idx_company_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- buyer: buy-side entities. No status column — the only filter is a non-blank
-- company_name.
-- ---------------------------------------------------------------------------
CREATE TABLE buyer (
    id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_name VARCHAR(255) DEFAULT NULL,
    website      VARCHAR(255) DEFAULT NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_buyer_company_name (company_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- leads: pre-qualification pipeline for both sides. Only `seller_lead` and
-- `buyer_lead` rows are in scope, and only while they are neither DROPPED nor
-- CONVERTED.
-- ---------------------------------------------------------------------------
CREATE TABLE leads (
    id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name            VARCHAR(255) DEFAULT NULL,
    website         VARCHAR(255) DEFAULT NULL,
    primary_id_type VARCHAR(32)  DEFAULT NULL,
    status          VARCHAR(32)  DEFAULT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_leads_name (name),
    KEY idx_leads_primary_id_type (primary_id_type),
    KEY idx_leads_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- Seed: sellers (35 active, 8 excluded)
-- Registered entity names paired with the brand the press uses.
-- ---------------------------------------------------------------------------
INSERT INTO company (name, brand_name, website, status) VALUES
    ('Bundl Technologies Private Limited',        'Swiggy',          'swiggy.com',              'active'),
    ('ANI Technologies Private Limited',          'Ola',             'olacabs.com',             'active'),
    ('Kiranakart Technologies Private Limited',   'Zepto',           'zeptonow.com',            'active'),
    ('One97 Communications Limited',              'Paytm',           'paytm.com',               'active'),
    ('FSN E-Commerce Ventures Limited',           'Nykaa',           'nykaa.com',               'active'),
    ('Lenskart Solutions Private Limited',        'Lenskart',        'lenskart.com',            'active'),
    ('Imagine Marketing Limited',                 'boAt',            'boat-lifestyle.com',      'active'),
    ('Honasa Consumer Limited',                   'Mamaearth',       'mamaearth.in',            'active'),
    ('Vellvette Lifestyle Private Limited',       'SUGAR Cosmetics', 'sugarcosmetics.com',      'active'),
    ('Dreamplug Technologies Private Limited',    'CRED',            'cred.club',               'active'),
    ('Razorpay Software Private Limited',         'Razorpay',        'razorpay.com',            NULL),
    ('Billionbrains Garage Ventures Private Limited', 'Groww',       'groww.in',                NULL),
    ('Zerodha Broking Limited',                   'Zerodha',         'zerodha.com',             'active'),
    ('PB Fintech Limited',                        'Policybazaar',    'policybazaar.com',        'active'),
    ('Pine Labs Private Limited',                 'Pine Labs',       'pinelabs.com',            'active'),
    ('Zetwerk Manufacturing Businesses Private Limited', 'Zetwerk',  'zetwerk.com',             'active'),
    ('Roppen Transportation Services Private Limited',   'Rapido',   'rapido.bike',             'active'),
    ('Urbanclap Technologies India Private Limited',     'Urban Company', 'urbancompany.com',   'active'),
    ('Delightful Gourmet Private Limited',        'Licious',         'licious.in',              'active'),
    ('Binsar Farms Private Limited',              'Country Delight', 'countrydelight.in',       'active'),
    ('Wakefit Innovations Limited',               'Wakefit',         'wakefit.co',              'active'),
    ('Ather Energy Limited',                      'Ather',           'atherenergy.com',         'active'),
    ('Ola Electric Mobility Limited',             'Ola Electric',    'olaelectric.com',         'active'),
    ('Mohalla Tech Private Limited',              'ShareChat',       'sharechat.com',           'active'),
    ('Sorting Hat Technologies Private Limited',  'Unacademy',       'unacademy.com',           'active'),
    ('Physics Wallah Limited',                    'PhysicsWallah',   'pw.live',                 'active'),
    ('Hector Beverages Private Limited',          'Paper Boat',      'paperboatdrinks.com',     'active'),
    ('Drums Food International Private Limited',  'Epigamia',        'epigamia.com',            'active'),
    ('Bombay Shaving Company Private Limited',    'Bombay Shaving Company', 'bombayshavingcompany.com', 'active'),
    ('Wingreens Farms Private Limited',           'Wingreens Farms', 'wingreensfarms.com',      'active'),
    ('Blue Tokai Coffee Roasters Private Limited','Blue Tokai',      'bluetokaicoffee.com',     NULL),
    ('Sunshine Teahouse Private Limited',         'Chaayos',         'chaayos.com',             'active'),
    ('Radhamani Textiles Private Limited',        'Rare Rabbit',     'rarerabbit.in',           'active');

-- ---------------------------------------------------------------------------
-- Sellers with explicit ids, mirroring real Done Deal seller references so the
-- entity news flow can be exercised end to end: the UI's "S5123" card resolves
-- through `GET /api/news/entities/S5123/news` to this row, and from its name to
-- the deals in Neo4j. Ids are set explicitly (not AUTO_INCREMENT) because the
-- reference is the fixture — S5123 must be Delhivery on every reseed.
--
-- These are the companies scraped in the news run, so each one has coverage in
-- the graph to resolve against. A NULL brand_name is deliberate on several:
-- it exercises the legal-suffix fallback, which is what turns the registered
-- "Oracle Corporation" into the "Oracle" the press actually writes.
-- ---------------------------------------------------------------------------
-- 5122-5125 are the real Done Deal seller ids. The rest are placeholders for
-- companies from the same scrape run whose ids are not yet known — correct
-- them here and reseed if they differ.
INSERT INTO company (id, name, brand_name, website, status) VALUES
    (5122, 'Zoho Corporation Private Limited',     'Zoho',        'zoho.com',        'active'),
    (5123, 'Delhivery Limited',                    'Delhivery',   'delhivery.com',   'active'),
    (5124, 'Fashnear Technologies Private Limited','Meesho',      'meesho.com',      'active'),
    (5125, 'API Holdings Limited',                 'PharmEasy',   'pharmeasy.in',    'active'),
    (5126, 'Curaa Home Private Limited',           'Curaa Home',  NULL,              'active'),
    (5127, 'Parviom Technologies Private Limited', NULL,          NULL,              'active'),
    (5128, 'Onesta Foods Private Limited',         'Onesta',      NULL,              'active'),
    (5129, 'Plugstack Technologies Private Limited','Plugstack',  NULL,              'active'),
    (6270, 'Rapidbox Commerce Private Limited',    'Rapidbox',    NULL,              'active'),
    (5131, 'Oracle Corporation',                   NULL,          'oracle.com',      'active');

-- Sellers the active filter must exclude.
INSERT INTO company (name, brand_name, website, status) VALUES
    ('Think and Learn Private Limited',           'BYJU''S',         'byjus.com',               'Inactive'),
    ('Dunzo Digital Private Limited',             'Dunzo',           'dunzo.com',               'Inactive'),
    ('Stayzilla Hospitality Private Limited',     'Stayzilla',       NULL,                      'archived'),
    ('Koinex Solutions Private Limited',          'Koinex',          NULL,                      'delist'),
    ('Test Entry Do Not Use',                     NULL,              NULL,                      'junk'),
    ('Duplicate Import 4471',                     NULL,              NULL,                      'junk'),
    ('   ',                                       'Blank Name Co',   'blank.example',           'active'),
    (NULL,                                        NULL,              NULL,                      'active');

-- ---------------------------------------------------------------------------
-- Seed: buyers (28 active, 2 excluded)
-- Strategics, listed conglomerates, and PE/VC funds that acquire.
-- ---------------------------------------------------------------------------
INSERT INTO buyer (company_name, website) VALUES
    ('Reliance Retail Ventures Limited',          'relianceretail.com'),
    ('Tata Digital Private Limited',              'tatadigital.com'),
    ('Flipkart Internet Private Limited',         'flipkart.com'),
    ('Amazon Seller Services Private Limited',    'amazon.in'),
    ('PhonePe Private Limited',                   'phonepe.com'),
    ('Info Edge (India) Limited',                 'infoedge.in'),
    ('Zomato Limited',                            'zomato.com'),
    ('Hindustan Unilever Limited',                'hul.co.in'),
    ('ITC Limited',                               'itcportal.com'),
    ('Marico Limited',                            'marico.com'),
    ('Dabur India Limited',                       'dabur.com'),
    ('Emami Limited',                             'emamiltd.in'),
    ('Godrej Consumer Products Limited',          'godrejcp.com'),
    ('Tata Consumer Products Limited',            'tataconsumer.com'),
    ('Aditya Birla Fashion and Retail Limited',   'abfrl.com'),
    ('Titan Company Limited',                     'titancompany.in'),
    ('Adani Enterprises Limited',                 'adanienterprises.com'),
    ('Larsen & Toubro Limited',                   'larsentoubro.com'),
    ('Wipro Limited',                             'wipro.com'),
    ('Infosys Limited',                           'infosys.com'),
    ('HCL Technologies Limited',                  'hcltech.com'),
    ('Tech Mahindra Limited',                     'techmahindra.com'),
    ('ChrysCapital Advisors LLP',                 'chryscapital.com'),
    ('Everstone Capital Advisors Private Limited','everstonegroup.com'),
    ('Multiples Alternate Asset Management Private Limited', 'multiplesequity.com'),
    ('Warburg Pincus India Private Limited',      'warburgpincus.com'),
    ('Peak XV Partners',                          'peakxv.com'),
    ('Blackstone Advisors India Private Limited', 'blackstone.com');

-- Buyers the non-blank name filter must exclude.
INSERT INTO buyer (company_name, website) VALUES
    ('',                                          'blank-buyer.example'),
    (NULL,                                        NULL);

-- ---------------------------------------------------------------------------
-- Seed: leads (26 in scope, 9 excluded)
-- Consumer brands and mid-market acquirers in early pipeline stages.
-- ---------------------------------------------------------------------------
INSERT INTO leads (name, website, primary_id_type, status) VALUES
    ('The Whole Truth Foods',                     'thewholetruthfoods.com',  'seller_lead', 'NEW'),
    ('Slurrp Farm',                               'slurrpfarm.com',          'seller_lead', 'NEW'),
    ('Yoga Bar',                                  'yogabars.in',             'seller_lead', 'CONTACTED'),
    ('Rage Coffee',                               'ragecoffee.com',          'seller_lead', 'CONTACTED'),
    ('Sleepy Owl Coffee',                         'sleepyowl.co',            'seller_lead', 'QUALIFIED'),
    ('Third Wave Coffee Roasters',                'thirdwavecoffeeroasters.com', 'seller_lead', 'QUALIFIED'),
    ('Bewakoof Brands Private Limited',           'bewakoof.com',            'seller_lead', 'NEW'),
    ('Snitch Apparels Private Limited',           'snitch.co.in',            'seller_lead', 'IN_DISCUSSION'),
    ('Plum Goodness',                             'plumgoodness.com',        'seller_lead', 'CONTACTED'),
    ('The Man Company',                           'themancompany.com',       'seller_lead', 'NEW'),
    ('Beardo',                                    'beardo.in',               'seller_lead', 'QUALIFIED'),
    ('Wow Skin Science',                          'buywow.in',               'seller_lead', 'NEW'),
    ('Nua Wellness Private Limited',              'nuawoman.com',            'seller_lead', 'CONTACTED'),
    ('Chumbak Design Private Limited',            'chumbak.com',             'seller_lead', 'NEW'),
    ('Milk Mantra Dairy Private Limited',         'milkmantra.com',          'seller_lead', 'IN_DISCUSSION'),
    ('Bombay Sweet Shop',                         'bombaysweetshop.com',     'seller_lead', 'NEW'),
    ('Farmley',                                   'farmley.com',             'seller_lead', 'QUALIFIED'),
    ('Nestle India Limited',                      'nestle.in',               'buyer_lead',  'NEW'),
    ('Britannia Industries Limited',              'britannia.co.in',         'buyer_lead',  'CONTACTED'),
    ('Zydus Wellness Limited',                    'zyduswellness.com',       'buyer_lead',  'NEW'),
    ('Bikaji Foods International Limited',        'bikaji.com',              'buyer_lead',  'QUALIFIED'),
    ('Haldiram Snacks Private Limited',           'haldirams.com',           'buyer_lead',  'IN_DISCUSSION'),
    ('Varun Beverages Limited',                   'varunpepsi.com',          'buyer_lead',  'NEW'),
    ('Jubilant FoodWorks Limited',                'jubilantfoodworks.com',   'buyer_lead',  'CONTACTED'),
    ('Mankind Pharma Limited',                    'mankindpharma.com',       'buyer_lead',  'NEW'),
    ('Piramal Enterprises Limited',               'piramal.com',             'buyer_lead',  'QUALIFIED');

-- Leads the filters must exclude: wrong id type, terminal status, NULL status
-- (NOT IN yields NULL), and blank names.
INSERT INTO leads (name, website, primary_id_type, status) VALUES
    ('Sula Vineyards Limited',                    'sulawines.com',           'seller_lead', 'DROPPED'),
    ('Manyavar (Vedant Fashions Limited)',        'manyavar.com',            'seller_lead', 'CONVERTED'),
    ('Go Colors (Go Fashion India Limited)',      'gocolors.com',            'buyer_lead',  'DROPPED'),
    ('Campus Activewear Limited',                 'campusactivewear.com',    'buyer_lead',  'CONVERTED'),
    ('Kotak Mahindra Bank Limited',               'kotak.com',               'investor_lead', 'NEW'),
    ('Deloitte India',                            'deloitte.com',            'advisor_lead',  'NEW'),
    ('ICICI Securities Limited',                  'icicisecurities.com',     'partner_lead',  'CONTACTED'),
    ('Unnamed Referral 2291',                     NULL,                      'seller_lead', NULL),
    ('   ',                                       NULL,                      'buyer_lead',  'NEW');

-- ---------------------------------------------------------------------------
-- Ageing: the watchlist searches only companies added since a cutoff, so most
-- of the seed is backdated and a named handful counts as "newly added".
--
-- Recent and active:  3 sellers, 2 buyers, 2 leads = 7 entities in a 24h window.
-- Recent but excluded: Dunzo (Inactive) and Go Colors (DROPPED) — they prove the
-- created_since filter composes with the active filters instead of overriding them.
-- ---------------------------------------------------------------------------
UPDATE company SET created_at = NOW() - INTERVAL 30 DAY;
UPDATE buyer   SET created_at = NOW() - INTERVAL 30 DAY;
UPDATE leads   SET created_at = NOW() - INTERVAL 30 DAY;

UPDATE company SET created_at = NOW() - INTERVAL 2 HOUR
    WHERE brand_name IN ('Swiggy', 'Zepto', 'Rare Rabbit', 'Dunzo');

UPDATE buyer SET created_at = NOW() - INTERVAL 2 HOUR
    WHERE company_name IN ('Reliance Retail Ventures Limited', 'Peak XV Partners');

UPDATE leads SET created_at = NOW() - INTERVAL 2 HOUR
    WHERE name IN ('Farmley', 'Mankind Pharma Limited', 'Go Colors (Go Fashion India Limited)');
