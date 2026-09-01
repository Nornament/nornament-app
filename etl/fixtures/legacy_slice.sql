-- A minimal but faithful slice of the Supabase schema, enough to rehearse the
-- ETL: the app tables load_legacy reads, plus the six public CRM tables.
CREATE SCHEMA app;
SET search_path TO app, public;

CREATE TABLE app.role (role_id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT, is_system BOOLEAN DEFAULT false);
INSERT INTO app.role (code, name, is_system) VALUES ('ADMIN','Admin',true),('SALES','Sales',false);

CREATE TABLE app.location (location_id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT, kind TEXT DEFAULT 'SHOWROOM', city TEXT, is_active BOOLEAN DEFAULT true);
INSERT INTO app.location (code,name,kind,city) VALUES ('HO','Head Office','GODOWN','Jaipur'),('MUM','Mumbai','SHOWROOM','Mumbai');

CREATE TABLE app.app_user (user_id SERIAL PRIMARY KEY, username TEXT UNIQUE, full_name TEXT, email TEXT, phone TEXT,
  password_hash TEXT, role_id INT REFERENCES app.role(role_id), home_location_id INT, is_active BOOLEAN DEFAULT true,
  auth_uid UUID, must_change_password BOOLEAN DEFAULT true, created_at TIMESTAMPTZ DEFAULT now());
-- The password_hash below is bcrypt's own published test vector, not anybody's
-- login: this fixture never authenticates, it only exercises the ETL's mapping.
INSERT INTO app.app_user (username, full_name, email, password_hash, role_id, auth_uid, must_change_password)
VALUES ('pradhyuman','Pradhyuman','pradhyuman@karigar.live','$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',1,'fda6fe50-cff2-4c32-8f99-da40d25f8cfc',false),
       ('showroom','Showroom','showroom@karigar.live','$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',2,'5cf533f2-54fb-4267-af32-ca91a14405de',false);

CREATE TABLE app.user_location (user_id INT, location_id INT, PRIMARY KEY (user_id, location_id));
INSERT INTO app.user_location VALUES (2,2);

CREATE TABLE app.category (category_id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT, parent_id INT, code_prefix TEXT, sort_order INT DEFAULT 0);
INSERT INTO app.category (code,name,code_prefix,sort_order) VALUES ('EARR','Earrings','ER',10);

CREATE TABLE app.collection (collection_id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT, story TEXT, is_bestseller BOOLEAN DEFAULT false, launched_on DATE);
CREATE TABLE app.vendor (vendor_id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT, contact TEXT, city TEXT, avg_tat_days NUMERIC(6,2), is_active BOOLEAN DEFAULT true);
INSERT INTO app.vendor (code,name,city,avg_tat_days) VALUES ('VEN01','Sharma Karigars','Jaipur',7.5);

CREATE TABLE app.metal (code TEXT PRIMARY KEY, name TEXT, pure_rate NUMERIC(14,4), rate_as_on TIMESTAMPTZ DEFAULT now(), unit TEXT DEFAULT 'GM', note TEXT, is_active BOOLEAN DEFAULT true);
INSERT INTO app.metal (code,name,pure_rate) VALUES ('GOLD','Gold',15481),('SILVER','Silver',260);

CREATE TABLE app.metal_purity (karat TEXT PRIMARY KEY, sale_factor NUMERIC(6,4), true_fineness NUMERIC(6,4), metal TEXT REFERENCES app.metal(code), sort_order INT DEFAULT 0);
INSERT INTO app.metal_purity VALUES ('18K',0.76,0.75,'GOLD',3),('925',1.0,0.925,'SILVER',2);

CREATE TABLE app.material_category (code TEXT PRIMARY KEY, name TEXT, sort_order INT DEFAULT 0, is_priceable BOOLEAN DEFAULT true, note TEXT);
INSERT INTO app.material_category VALUES ('METAL','Metal',1,true,null),('DIAMOND','Diamond',2,true,null),('LABOUR','Making',7,false,null);

CREATE TABLE app.material (material_id SERIAL PRIMARY KEY, item_code TEXT UNIQUE, item_name TEXT, description TEXT, size TEXT,
  mat_class TEXT, category TEXT REFERENCES app.material_category(code), default_uom TEXT, purity_factor NUMERIC(6,4),
  metal TEXT REFERENCES app.metal(code), needs_review BOOLEAN DEFAULT false, is_active BOOLEAN DEFAULT true);
INSERT INTO app.material (item_code,item_name,mat_class,category,default_uom,metal) VALUES
  ('G','Gold','METAL','METAL','GM','GOLD'),('DRKL','Diamond RKL','DIAMOND','DIAMOND','CT',NULL),('MAKING','Making Charge','LABOUR','LABOUR','GM',NULL);

CREATE TABLE app.system_setting (key TEXT PRIMARY KEY, value TEXT, description TEXT);
INSERT INTO app.system_setting VALUES ('line_rounding_dp','0',null),('total_rounding_dp','0',null),('gross_wt_tolerance_gm','0.050',null);

CREATE TABLE app.style (style_id SERIAL PRIMARY KEY, style_code TEXT UNIQUE, name TEXT, category_id INT REFERENCES app.category(category_id),
  collection_id INT, state TEXT DEFAULT 'SKETCH', designer_user_id INT, story TEXT, website_description TEXT, designed_on DATE,
  parent_style_id INT, version_label TEXT, nos_min_qty INT DEFAULT 0, is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(), created_by INT);
INSERT INTO app.style (style_code,name,category_id) VALUES ('ER00738','Petal studs',1);

CREATE TABLE app.rate_chart (chart_id SERIAL PRIMARY KEY, code TEXT, name TEXT, version_no INT DEFAULT 1, is_default BOOLEAN DEFAULT false,
  is_locked BOOLEAN DEFAULT false, forked_from INT, note TEXT, created_by INT, created_at TIMESTAMPTZ DEFAULT now());
INSERT INTO app.rate_chart (code,name,is_default) VALUES ('DEFAULT','Default',true);

CREATE TABLE app.rate_chart_line (chart_id INT REFERENCES app.rate_chart(chart_id), material_id INT REFERENCES app.material(material_id),
  size_band TEXT DEFAULT '', cost_rate NUMERIC(14,4), sale_rate NUMERIC(14,4), rate_uom TEXT, PRIMARY KEY (chart_id, material_id, size_band));
INSERT INTO app.rate_chart_line VALUES (1,2,'',150000,180000,'CT');

CREATE TABLE app.scenario (scenario_id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT, method TEXT, chart_id INT, target_pct NUMERIC(8,3),
  spread_over TEXT[] DEFAULT ARRAY['DIAMOND'], spread_by TEXT DEFAULT 'COST', min_multiple NUMERIC(8,3) DEFAULT 1.0,
  max_multiple NUMERIC(8,3) DEFAULT 8.0, is_default BOOLEAN DEFAULT false, is_active BOOLEAN DEFAULT true, note TEXT);
INSERT INTO app.scenario (code,name,method,chart_id,is_default) VALUES ('RETAIL','Retail','CHART',1,true);

CREATE TABLE app.jewel_code (jewel_code_id SERIAL PRIMARY KEY, jewel_code TEXT UNIQUE, style_id INT REFERENCES app.style(style_id),
  sub_category TEXT, metal_purity TEXT, metal_colour TEXT, size_label TEXT, diamond_quality TEXT, measured_gross_wt_gm NUMERIC(10,3),
  length_mm NUMERIC(8,2), breadth_mm NUMERIC(8,2), height_mm NUMERIC(8,2), fg_date DATE, stock_type TEXT DEFAULT 'FINISH_GOODS',
  huid TEXT, hallmarked_on DATE, hallmark_centre TEXT, stock_state TEXT DEFAULT 'NOT_RECEIVED', location_id INT,
  received_on DATE, disposed_on DATE, current_bom_version INT DEFAULT 1, vendor_id INT, scenario_id INT, on_website BOOLEAN DEFAULT false,
  website_url TEXT, remarks TEXT, src_system TEXT, src_ref TEXT, src_cost_price NUMERIC, src_sale_price NUMERIC, src_tag_price NUMERIC,
  src_net_wt_gm NUMERIC, bom_is_summary BOOLEAN DEFAULT false, created_at TIMESTAMPTZ DEFAULT now(), created_by INT, updated_at TIMESTAMPTZ DEFAULT now());
INSERT INTO app.jewel_code (jewel_code, style_id, metal_purity, measured_gross_wt_gm, stock_state, location_id, received_on, vendor_id, src_cost_price)
VALUES ('ER00738',1,'18K',4.200,'IN_STOCK',2,'2026-08-01',1,180000),
       ('ER00739',1,'18K',3.900,'IN_STOCK',2,'2026-08-02',1,175000);

CREATE TABLE app.bom_version (jewel_code_id INT REFERENCES app.jewel_code(jewel_code_id), version_no INT, reason TEXT DEFAULT 'INITIAL',
  note TEXT, repair_job_id BIGINT, cost_rate_card_id INT, sale_rate_card_id INT, net_metal_wt_gm NUMERIC(10,3), bom_weight_gm NUMERIC(10,3),
  total_cost_price NUMERIC(14,2), total_sale_price NUMERIC(14,2), making_value NUMERIC(14,2), goods_value NUMERIC(14,2),
  is_current BOOLEAN DEFAULT true, created_at TIMESTAMPTZ DEFAULT now(), created_by INT, PRIMARY KEY (jewel_code_id, version_no));
INSERT INTO app.bom_version (jewel_code_id, version_no, net_metal_wt_gm, bom_weight_gm, total_cost_price, total_sale_price, making_value, goods_value)
VALUES (1,1,4.000,4.225,219994,255564,6000,249564),(2,1,3.700,3.900,205000,240000,5550,234450);

CREATE TABLE app.jewel_material_line (line_id BIGSERIAL PRIMARY KEY, jewel_code_id INT, version_no INT, line_no INT,
  material_id INT REFERENCES app.material(material_id), size_band TEXT DEFAULT '', pcs INT, qty_value NUMERIC(12,4), qty_uom TEXT,
  basis TEXT DEFAULT 'BY_QTY', cost_rate NUMERIC(14,4), cost_amount NUMERIC(14,2), sale_rate NUMERIC(14,4), sale_amount NUMERIC(14,2),
  off_chart BOOLEAN DEFAULT false, remarks TEXT);
INSERT INTO app.jewel_material_line (jewel_code_id, version_no, line_no, material_id, qty_value, qty_uom, basis, cost_rate, cost_amount, sale_rate, sale_amount) VALUES
 (1,1,1,1,4.0000,'GM','BY_QTY',11611,46444,11766,47064),
 (1,1,2,2,1.1250,'CT','BY_QTY',150000,168750,180000,202500),
 (1,1,3,3,4.0000,'GM','BY_NET_METAL_WT',1200,4800,1500,6000),
 (2,1,1,1,3.7000,'GM','BY_QTY',11611,42961,11766,43534),
 (2,1,2,2,1.0000,'CT','BY_QTY',150000,150000,180000,180000),
 (2,1,3,3,3.7000,'GM','BY_NET_METAL_WT',1200,4440,1500,5550);

CREATE TABLE app.stock_movement (movement_id BIGSERIAL PRIMARY KEY, jewel_code_id INT, move_type TEXT, from_location_id INT,
  to_location_id INT, resulting_state TEXT, moved_at TIMESTAMPTZ DEFAULT now(), reference_no TEXT, party_name TEXT, reason TEXT,
  user_id INT, created_at TIMESTAMPTZ DEFAULT now());
INSERT INTO app.stock_movement (jewel_code_id, move_type, to_location_id, resulting_state, moved_at, user_id)
VALUES (1,'RECEIPT',2,'IN_STOCK','2026-08-01 10:00+05:30',1),(2,'RECEIPT',2,'IN_STOCK','2026-08-02 10:00+05:30',1);

CREATE TABLE app.sale (sale_id BIGSERIAL PRIMARY KEY, jewel_code_id INT UNIQUE, bom_version_at_sale INT, sold_on DATE, location_id INT,
  customer_name TEXT, customer_phone TEXT, salesperson_id INT, sold_price NUMERIC(14,2), discount_amt NUMERIC(14,2) DEFAULT 0,
  cost_at_sale NUMERIC(14,2), margin_amt NUMERIC(14,2) GENERATED ALWAYS AS (sold_price - discount_amt - cost_at_sale) STORED,
  created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE app.melt_record (melt_id BIGSERIAL PRIMARY KEY, jewel_code_id INT UNIQUE, bom_version_at_melt INT, melted_on DATE,
  location_id INT, reason TEXT, cost_written_off NUMERIC(14,2), authorised_by INT, created_at TIMESTAMPTZ DEFAULT now());

CREATE TABLE app.repair_job (repair_job_id BIGSERIAL PRIMARY KEY, job_no TEXT UNIQUE, jewel_code_id INT, from_bom_version INT,
  to_bom_version INT, opened_on DATE, closed_on DATE, vendor_id INT, return_location_id INT, fault_description TEXT, work_done TEXT,
  labour_cost NUMERIC(14,2) DEFAULT 0, status TEXT DEFAULT 'OPEN', opened_by INT, closed_by INT,
  tat_days INT GENERATED ALWAYS AS (closed_on - opened_on) STORED);

CREATE TABLE app.repair_material_change (change_id BIGSERIAL PRIMARY KEY, repair_job_id BIGINT, action TEXT, material_id INT,
  size_band TEXT DEFAULT '', pcs INT, qty_value NUMERIC(12,4), qty_uom TEXT, cost_rate NUMERIC(14,4), sale_rate NUMERIC(14,4),
  returned_to_stock BOOLEAN DEFAULT true, remarks TEXT);

CREATE TABLE app.stock_count (count_id SERIAL PRIMARY KEY, count_ref TEXT UNIQUE, location_id INT, started_at TIMESTAMPTZ DEFAULT now(),
  closed_at TIMESTAMPTZ, status TEXT DEFAULT 'OPEN', counted_by INT, approved_by INT, notes TEXT, result JSONB);
INSERT INTO app.stock_count (count_ref, location_id, status, closed_at, counted_by, result)
VALUES ('SC-260801-MUM',2,'CLOSED','2026-08-01 18:00+05:30',1,'{"expected":2,"found":2,"missing":0,"unexpected":0}');

CREATE TABLE app.stock_count_scan (scan_id BIGSERIAL PRIMARY KEY, count_id INT, jewel_code_id INT, scanned_at TIMESTAMPTZ DEFAULT now(),
  scanned_by INT, verdict TEXT);
INSERT INTO app.stock_count_scan (count_id, jewel_code_id, scanned_by, verdict) VALUES (1,1,1,'FOUND'),(1,2,1,'FOUND');

CREATE TABLE app.media_asset (media_id BIGSERIAL PRIMARY KEY, media_ref TEXT UNIQUE, style_id INT, jewel_code_id INT, kind TEXT DEFAULT 'PHOTO',
  storage_provider TEXT DEFAULT 'R2', storage_key TEXT, storage_url TEXT, thumb_url TEXT, file_name TEXT, mime_type TEXT, sha256 TEXT,
  bytes BIGINT, caption TEXT, view_angle TEXT, rank_order INT DEFAULT 100, is_catalogue_default BOOLEAN DEFAULT false,
  is_archived BOOLEAN DEFAULT false, width_px INT, height_px INT, file_size_kb INT, derivative_of INT, derivative_kind TEXT,
  uploaded_by INT, uploaded_at TIMESTAMPTZ DEFAULT now());
INSERT INTO app.media_asset (media_ref, jewel_code_id, storage_key, file_name, mime_type, bytes)
VALUES ('M000001',1,'stock/piece/1/abc.jpg','front.jpg','image/jpeg',120000);

-- ── the CRM, as six JSONB tables ────────────────────────────────────────
CREATE TABLE public.customers (id TEXT PRIMARY KEY, customer_code TEXT UNIQUE, data JSONB DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE public.orders (id TEXT PRIMARY KEY, order_code TEXT UNIQUE, customer_id TEXT, data JSONB DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE public.repairs (id TEXT PRIMARY KEY, repair_code TEXT UNIQUE, customer_id TEXT, data JSONB DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE public.enquiries (id TEXT PRIMARY KEY, enquiry_code TEXT UNIQUE, customer_id TEXT, data JSONB DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE public.client_materials (id TEXT PRIMARY KEY, cm_code TEXT UNIQUE, customer_id TEXT, data JSONB DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE public.settings (key TEXT PRIMARY KEY, value JSONB DEFAULT '{}');

INSERT INTO public.customers (id, customer_code, data) VALUES
('c_anita','NC0001', '{"name":"Anita Shah","phone":{"mobile":"9820000000","preferred":"mobile"},"email":"anita@example.com","birthDate":"1985-03-04","referenceFrom":{"type":"Existing Customer","referrerCode":"NC0002"},"fonData":{"isFoN":true,"level":1,"parentId":null},"outreach":{"done":true,"lastDate":"2026-07-01","notes":"Called"},"metalPreference":["Gold"],"occasions":[{"type":"Wedding","date":"2026-12-01"}],"relatedPeople":[{"name":"Rahul","relation":"Husband"}],"gifting":[{"date":"2026-05-01","occasion":"Anniversary","description":"Silver frame","amount":4500}],"purchases":[{"id":"p1","date":"2026-08-04","amount":125000,"category":"cat1","invoiceNo":"INV-9"},{"id":"p2","date":"2026-08-20","amount":40000,"category":"cat3"}],"customerType":"VIP","temperature":"Hot","somethingNew":"keep me"}'),
('c_bhavna','NC0002','{"name":"Bhavna Rao","phone":{"mobile":"9810000000"},"fonData":{"isFoN":true,"level":2,"parentId":"c_anita"},"purchases":[{"id":"p3","date":"2026-08-10","amount":200000,"category":"cat1"}]}'),
-- The shapes the real Supabase data has and a hand-written fixture never does:
-- a date the invoice OCR wrote (04/08/2026), a category the CSV bulk upload
-- stored as its label, a purchase with no date at all, and a purchase carrying
-- the sourceOrderId the legacy app stamped on it when an order was delivered.
('c_dirty','NC0003','{"name":"Kavita Nair","phone":{"mobile":"9800000000"},"purchases":[{"id":"p4","date":"04/08/2026","amount":"1,25,000","category":"Cat 1 \u2013 Diamond/Polki","invoiceNo":"INV-11"},{"id":"p5","date":"","amount":15000},{"id":"p6","date":"2026-08-15","amount":450000,"sourceOrderId":"o_1","remarks":"Auto from NO0001"}]}');

INSERT INTO public.orders (id, order_code, customer_id, data) VALUES
('o_1','NO0001','c_anita','{"orderDate":"2026-08-05","itemDescription":"Polki choker","totalAmount":"450000","advancePaid":100000,"status":"Designing","statusLog":[{"date":"2026-08-05","status":"Order Confirmed","by":"Priya"}],"unknownThing":42}'),
('o_2','NO0002','c_ghost','{"orderDate":"2026-08-06","itemDescription":"Orphan order","status":"Designing"}'),
-- a stage that is the right one but not the right string
('o_3','NO0003','c_dirty','{"orderDate":"2026-08-07","itemDescription":"Jadau set","status":"  order   confirmed "}');

INSERT INTO public.enquiries (id, enquiry_code, customer_id, data) VALUES
('e_1','NE0001','c_anita','{"enquiryDate":"2026-08-01","itemOfInterest":"Diamond studs","estimatedBudget":"200000","status":"Quote Sent","followUpDate":"2026-08-30","temperature":"Hot"}');
INSERT INTO public.repairs (id, repair_code, customer_id, data) VALUES
('r_1','NR0001','c_anita','{"receivedDate":"2026-08-03","itemDescription":"Gold chain","issue":"Clasp broken","estimatedCost":1500,"status":"In Workshop"}');
INSERT INTO public.client_materials (id, cm_code, customer_id, data) VALUES
('cm_1','NCM001','c_anita','{"receivedDate":"2026-08-02","jewelleryDescription":"Old bangles","metalType":"Gold 22k","weightGrams":"38.5","status":"Design Pending"}');
INSERT INTO public.settings VALUES ('salespersons','["Ananya","Priya"]');
