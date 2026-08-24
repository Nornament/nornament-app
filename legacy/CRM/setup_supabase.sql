-- Run this in: supabase.com → your project → SQL Editor → New query → Run

-- 1. Tables (safe to re-run)
CREATE TABLE IF NOT EXISTS customers (
  id           TEXT PRIMARY KEY,
  customer_code TEXT UNIQUE NOT NULL,
  data         JSONB NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
  id           TEXT PRIMARY KEY,
  order_code   TEXT UNIQUE NOT NULL,
  customer_id  TEXT,
  data         JSONB NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS repairs (
  id           TEXT PRIMARY KEY,
  repair_code  TEXT UNIQUE NOT NULL,
  customer_id  TEXT,
  data         JSONB NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value JSONB NOT NULL DEFAULT '{}'
);

-- 2. Row Level Security
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders    ENABLE ROW LEVEL SECURITY;
ALTER TABLE repairs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings  ENABLE ROW LEVEL SECURITY;

-- 3. Drop existing policies if present, then recreate
DROP POLICY IF EXISTS "auth_only" ON customers;
DROP POLICY IF EXISTS "auth_only" ON orders;
DROP POLICY IF EXISTS "auth_only" ON repairs;
DROP POLICY IF EXISTS "auth_only" ON settings;

CREATE POLICY "auth_only" ON customers FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_only" ON orders    FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_only" ON repairs   FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_only" ON settings  FOR ALL USING (auth.role() = 'authenticated');

-- 4. New tables for v2: enquiries and client_materials
CREATE TABLE IF NOT EXISTS enquiries (
  id            TEXT PRIMARY KEY,
  enquiry_code  TEXT UNIQUE NOT NULL,
  customer_id   TEXT,
  data          JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS client_materials (
  id          TEXT PRIMARY KEY,
  cm_code     TEXT UNIQUE NOT NULL,
  customer_id TEXT,
  data        JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE enquiries       ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_materials ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "auth_only" ON enquiries;
DROP POLICY IF EXISTS "auth_only" ON client_materials;

CREATE POLICY "auth_only" ON enquiries        FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_only" ON client_materials FOR ALL USING (auth.role() = 'authenticated');
