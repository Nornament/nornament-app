CREATE SCHEMA IF NOT EXISTS app;
SET search_path TO app, public;
CREATE TYPE uom AS ENUM ('CT','GM','RATTI','PCS');
CREATE TYPE material_class AS ENUM (
  'METAL','DIAMOND','POLKI','COLOUR_STONE','PEARL','FINDING','LABOUR','OTHER');
CREATE TYPE charge_basis AS ENUM (
  'BY_QTY','BY_NET_METAL_WT','BY_GROSS_WT','BY_PIECE','FLAT');
CREATE TYPE design_state AS ENUM (
  'SKETCH','DESIGN_INSPIRATION','RENDERING','CAD',
  'IN_STOCK_DESIGN','OUT_OF_STOCK_DESIGN','DISCONTINUED');
CREATE TYPE media_kind AS ENUM (
  'PHOTO','VIDEO','CAD','PENCIL_DRAWING','RENDER','CERTIFICATE_SCAN','JOB_CARD_SCAN');
CREATE TYPE stock_state AS ENUM (
  'NOT_RECEIVED','IN_STOCK','RESERVED','ON_APPROVAL','IN_TRANSIT',
  'IN_REPAIR','SOLD','MELTED','LOST');
CREATE TYPE movement_type AS ENUM (
  'RECEIPT','TRANSFER_OUT','TRANSFER_IN','RESERVE','UNRESERVE',
  'APPROVAL_OUT','APPROVAL_RETURN','REPAIR_OUT','REPAIR_IN',
  'SALE','SALE_RETURN','MELT','LOST','COUNT_ADJUSTMENT');
CREATE TYPE bom_change_reason AS ENUM ('INITIAL','REPAIR','CORRECTION','RECOST');
CREATE TABLE uom_conversion (
  unit uom PRIMARY KEY, grams_per_unit NUMERIC(12,6) NOT NULL);
INSERT INTO uom_conversion VALUES ('GM',1.0),('CT',0.2),('RATTI',0.1215),('PCS',0.0);
CREATE TABLE metal_purity (
  karat TEXT PRIMARY KEY,
  sale_factor   NUMERIC(6,4) NOT NULL CHECK (sale_factor > 0 AND sale_factor <= 1),
  true_fineness NUMERIC(6,4) NOT NULL CHECK (true_fineness > 0 AND true_fineness <= 1),
  CHECK (sale_factor >= true_fineness));
INSERT INTO metal_purity VALUES
  ('24K',1.0000,1.0000),('22K',0.9250,0.9167),('18K',0.7600,0.7500),('14K',0.5900,0.5833);
CREATE TABLE system_setting (key TEXT PRIMARY KEY, value TEXT NOT NULL, description TEXT);
INSERT INTO system_setting VALUES
 ('line_rounding_dp','0','Decimals each material line rounds to before summing. 0 = whole rupees, matches the legacy Excel job card.'),
 ('total_rounding_dp','0','Decimals the jewel code total rounds to.'),
 ('gross_wt_tolerance_gm','0.050','Allowed gap between the BOM-derived weight and the measured gross weight before the reconciliation report flags it.'),
 ('pure_gold_rate','14744','Live 24K rate per gram. Every karat sale rate derives from this. Cost rates never do.'),
 ('pure_gold_rate_as_on','2026-08-12 10:00:00','When the pure rate above was last set. Every quote must carry this.');
CREATE OR REPLACE FUNCTION setting_int(k TEXT, d INT) RETURNS INT
LANGUAGE sql STABLE AS $$ SELECT COALESCE((SELECT value::INT FROM system_setting WHERE key=k), d); $$;
CREATE OR REPLACE FUNCTION setting_num(k TEXT, d NUMERIC) RETURNS NUMERIC
LANGUAGE sql STABLE AS $$ SELECT COALESCE((SELECT value::NUMERIC FROM system_setting WHERE key=k), d); $$;
CREATE TABLE location (
  location_id SERIAL PRIMARY KEY,
  code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'SHOWROOM'
       CHECK (kind IN ('SHOWROOM','GODOWN','WORKSHOP','VENDOR','TRANSIT')),
  city TEXT, is_active BOOLEAN NOT NULL DEFAULT TRUE);
CREATE TABLE role (
  role_id SERIAL PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT,
  can_view_cost_price       BOOLEAN NOT NULL DEFAULT FALSE,
  can_view_sale_price       BOOLEAN NOT NULL DEFAULT FALSE,
  can_view_material_breakup BOOLEAN NOT NULL DEFAULT FALSE,
  can_view_vendor           BOOLEAN NOT NULL DEFAULT FALSE,
  can_view_margin           BOOLEAN NOT NULL DEFAULT FALSE,
  can_melt                  BOOLEAN NOT NULL DEFAULT FALSE,
  can_edit_bom              BOOLEAN NOT NULL DEFAULT FALSE,
  can_adjust_stock          BOOLEAN NOT NULL DEFAULT FALSE,
  is_system                 BOOLEAN NOT NULL DEFAULT FALSE);
CREATE TABLE app_user (
  user_id SERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
  email TEXT UNIQUE, phone TEXT, password_hash TEXT,
  role_id INT NOT NULL REFERENCES role(role_id),
  home_location_id INT REFERENCES location(location_id),
  is_active BOOLEAN NOT NULL DEFAULT TRUE, last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE user_location (
  user_id INT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
  location_id INT NOT NULL REFERENCES location(location_id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, location_id));
CREATE TABLE module (module_code TEXT PRIMARY KEY, name TEXT NOT NULL, sort_order INT NOT NULL DEFAULT 0);
CREATE TABLE role_module_permission (
  role_id INT NOT NULL REFERENCES role(role_id) ON DELETE CASCADE,
  module_code TEXT NOT NULL REFERENCES module(module_code) ON DELETE CASCADE,
  can_view BOOLEAN NOT NULL DEFAULT FALSE, can_create BOOLEAN NOT NULL DEFAULT FALSE,
  can_edit BOOLEAN NOT NULL DEFAULT FALSE, can_delete BOOLEAN NOT NULL DEFAULT FALSE,
  can_export BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (role_id, module_code));
CREATE TABLE category (
  category_id SERIAL PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  parent_id INT REFERENCES category(category_id), code_prefix TEXT, sort_order INT NOT NULL DEFAULT 0);
CREATE TABLE tag (
  tag_id SERIAL PRIMARY KEY, name TEXT NOT NULL, tag_group TEXT NOT NULL,
  UNIQUE (tag_group, name));
CREATE TABLE collection (
  collection_id SERIAL PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  story TEXT, is_bestseller BOOLEAN NOT NULL DEFAULT FALSE, launched_on DATE);
CREATE TABLE vendor (
  vendor_id SERIAL PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  contact TEXT, city TEXT, avg_tat_days NUMERIC(6,2), is_active BOOLEAN NOT NULL DEFAULT TRUE);
CREATE TABLE style (
  style_id SERIAL PRIMARY KEY, style_code TEXT NOT NULL UNIQUE, name TEXT,
  category_id INT NOT NULL REFERENCES category(category_id),
  collection_id INT REFERENCES collection(collection_id),
  state design_state NOT NULL DEFAULT 'SKETCH',
  designer_user_id INT REFERENCES app_user(user_id),
  story TEXT, website_description TEXT, designed_on DATE,
  parent_style_id INT REFERENCES style(style_id), version_label TEXT,
  nos_min_qty INT NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by INT REFERENCES app_user(user_id));
CREATE TABLE style_tag (
  style_id INT NOT NULL REFERENCES style(style_id) ON DELETE CASCADE,
  tag_id INT NOT NULL REFERENCES tag(tag_id) ON DELETE CASCADE,
  PRIMARY KEY (style_id, tag_id));
CREATE TABLE jewel_code (
  jewel_code_id SERIAL PRIMARY KEY,
  jewel_code TEXT NOT NULL UNIQUE,
  style_id INT NOT NULL REFERENCES style(style_id),
  metal_purity TEXT, metal_colour TEXT, size_label TEXT, diamond_quality TEXT,
  measured_gross_wt_gm NUMERIC(10,3),
  length_mm NUMERIC(8,2), breadth_mm NUMERIC(8,2), height_mm NUMERIC(8,2),
  fg_date DATE, stock_type TEXT DEFAULT 'FINISH_GOODS',
  huid TEXT UNIQUE,
  hallmarked_on DATE, hallmark_centre TEXT,
  stock_state stock_state NOT NULL DEFAULT 'NOT_RECEIVED',
  location_id INT REFERENCES location(location_id),
  received_on DATE, disposed_on DATE,
  current_bom_version INT NOT NULL DEFAULT 1,
  vendor_id INT REFERENCES vendor(vendor_id),
  on_website BOOLEAN NOT NULL DEFAULT FALSE, website_url TEXT, remarks TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by INT REFERENCES app_user(user_id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT live_piece_has_location CHECK (
    (stock_state IN ('SOLD','MELTED','LOST','NOT_RECEIVED')) OR (location_id IS NOT NULL)),
  CONSTRAINT dead_piece_has_date CHECK (
    (stock_state NOT IN ('SOLD','MELTED','LOST')) OR (disposed_on IS NOT NULL)));
CREATE INDEX idx_jewel_style ON jewel_code(style_id);
CREATE INDEX idx_jewel_state ON jewel_code(stock_state, location_id);
CREATE TABLE jewel_code_certificate (
  certificate_id SERIAL PRIMARY KEY,
  jewel_code_id INT NOT NULL REFERENCES jewel_code(jewel_code_id) ON DELETE CASCADE,
  company TEXT NOT NULL, cert_number TEXT NOT NULL, issued_on DATE,
  UNIQUE (company, cert_number));
CREATE TABLE material (
  material_id SERIAL PRIMARY KEY, item_code TEXT NOT NULL UNIQUE, item_name TEXT NOT NULL,
  mat_class material_class NOT NULL, default_uom uom NOT NULL,
  purity_factor NUMERIC(6,4), is_active BOOLEAN NOT NULL DEFAULT TRUE);
CREATE TABLE rate_card (
  rate_card_id SERIAL PRIMARY KEY, code TEXT NOT NULL UNIQUE,
  card_type TEXT NOT NULL CHECK (card_type IN ('COST','SALE')),
  effective_from DATE NOT NULL, effective_to DATE, notes TEXT,
  created_by INT REFERENCES app_user(user_id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (effective_to IS NULL OR effective_to >= effective_from));
CREATE TABLE rate_card_line (
  rate_card_id INT NOT NULL REFERENCES rate_card(rate_card_id) ON DELETE CASCADE,
  material_id INT NOT NULL REFERENCES material(material_id),
  size_band TEXT NOT NULL DEFAULT '',
  rate NUMERIC(14,4) NOT NULL, rate_uom uom NOT NULL,
  PRIMARY KEY (rate_card_id, material_id, size_band));
CREATE TABLE bom_version (
  jewel_code_id INT NOT NULL REFERENCES jewel_code(jewel_code_id) ON DELETE CASCADE,
  version_no INT NOT NULL,
  reason bom_change_reason NOT NULL DEFAULT 'INITIAL',
  note TEXT,
  repair_job_id BIGINT,
  cost_rate_card_id INT REFERENCES rate_card(rate_card_id),
  sale_rate_card_id INT REFERENCES rate_card(rate_card_id),
  net_metal_wt_gm  NUMERIC(10,3),
  bom_weight_gm    NUMERIC(10,3),
  total_cost_price NUMERIC(14,2),
  total_sale_price NUMERIC(14,2),
  making_value     NUMERIC(14,2),
  goods_value      NUMERIC(14,2),
  is_current BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by INT REFERENCES app_user(user_id),
  PRIMARY KEY (jewel_code_id, version_no));
CREATE UNIQUE INDEX uq_current_bom ON bom_version(jewel_code_id) WHERE is_current;
CREATE TABLE jewel_material_line (
  line_id BIGSERIAL PRIMARY KEY,
  jewel_code_id INT NOT NULL,
  version_no INT NOT NULL,
  line_no INT NOT NULL,
  material_id INT NOT NULL REFERENCES material(material_id),
  size_band TEXT NOT NULL DEFAULT '',
  pcs INT,
  qty_value NUMERIC(12,4), qty_uom uom NOT NULL,
  basis charge_basis NOT NULL DEFAULT 'BY_QTY',
  cost_rate NUMERIC(14,4), cost_amount NUMERIC(14,2),
  sale_rate NUMERIC(14,4), sale_amount NUMERIC(14,2),
  remarks TEXT,
  FOREIGN KEY (jewel_code_id, version_no) REFERENCES bom_version(jewel_code_id, version_no) ON DELETE CASCADE,
  UNIQUE (jewel_code_id, version_no, line_no));
CREATE INDEX idx_jml ON jewel_material_line(jewel_code_id, version_no);;
