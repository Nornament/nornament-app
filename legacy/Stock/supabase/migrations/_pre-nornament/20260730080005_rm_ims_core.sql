-- Raw Material IMS: parties, lots, transactions (gold pilot; generic for stones/diamonds/jewellery)

CREATE TABLE IF NOT EXISTS rm_parties (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  party_type text NOT NULL DEFAULT 'karigar' CHECK (party_type IN ('karigar','vendor','refiner','client','other')),
  phone text,
  notes text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rm_lots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lot_code text NOT NULL,
  material text NOT NULL CHECK (material IN ('gold','diamond','stone','jewellery')),
  form text,                       -- fine/wire/sheet/chorsa/grain/findings/scrap/dust ...
  purity_label text,               -- '995','24K','22K','18K','14K'
  fineness numeric(6,4) CHECK (fineness > 0 AND fineness <= 1),
  uom text NOT NULL DEFAULT 'g' CHECK (uom IN ('g','ct','pc')),
  description text,
  box_no text,
  location text,
  photos jsonb NOT NULL DEFAULT '[]',
  data jsonb NOT NULL DEFAULT '{}',   -- stone attrs later: shape,colour,quality,size...
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS rm_lots_code_unique ON rm_lots (upper(lot_code));

CREATE TABLE IF NOT EXISTS rm_txns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lot_id uuid REFERENCES rm_lots(id),
  txn_date date NOT NULL DEFAULT current_date,
  txn_type text NOT NULL CHECK (txn_type IN (
    'PURCHASE_IN','OPENING_IN','ISSUE_OUT','FINISHED_IN','SCRAP_IN',
    'MELT_OUT','MELT_IN','CLIENT_RETURN_IN','SALE_OUT','ADJUST'
  )),
  qty numeric(12,3) NOT NULL,          -- signed: + into lot, - out of lot
  pcs integer,
  fineness numeric(6,4),               -- override / for lot-less FINISHED_IN rows
  party_id uuid REFERENCES rm_parties(id),
  job_ref text,
  issue_txn_id uuid REFERENCES rm_txns(id),
  melt_group uuid,
  rate numeric(12,2),
  remarks text,
  photos jsonb NOT NULL DEFAULT '[]',
  created_by text,
  created_at timestamptz DEFAULT now(),
  -- FINISHED_IN reduces karigar outstanding without touching an RM lot
  CONSTRAINT lot_required CHECK (lot_id IS NOT NULL OR txn_type = 'FINISHED_IN'),
  CONSTRAINT sign_matches_type CHECK (
    (txn_type IN ('PURCHASE_IN','OPENING_IN','SCRAP_IN','MELT_IN','CLIENT_RETURN_IN','FINISHED_IN') AND qty >= 0)
    OR (txn_type IN ('ISSUE_OUT','MELT_OUT','SALE_OUT') AND qty <= 0)
    OR txn_type = 'ADJUST'
  )
);
CREATE INDEX IF NOT EXISTS rm_txns_lot_idx ON rm_txns (lot_id);
CREATE INDEX IF NOT EXISTS rm_txns_party_idx ON rm_txns (party_id);
CREATE INDEX IF NOT EXISTS rm_txns_job_idx ON rm_txns (job_ref);

-- Block negative lot balances at DB level
CREATE OR REPLACE FUNCTION rm_check_balance() RETURNS trigger AS $$
DECLARE bal numeric;
BEGIN
  IF NEW.lot_id IS NOT NULL AND NEW.qty < 0 THEN
    SELECT coalesce(sum(qty),0) INTO bal FROM rm_txns WHERE lot_id = NEW.lot_id;
    IF bal + NEW.qty < -0.0005 THEN
      RAISE EXCEPTION 'Insufficient balance in lot: have %, tried to remove %', bal, -NEW.qty;
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS rm_txns_balance_check ON rm_txns;
CREATE TRIGGER rm_txns_balance_check BEFORE INSERT ON rm_txns
  FOR EACH ROW EXECUTE FUNCTION rm_check_balance();

-- Lot balances incl. fine weight
CREATE OR REPLACE VIEW v_rm_lot_balance AS
SELECT l.id, l.lot_code, l.material, l.form, l.purity_label, l.fineness, l.uom,
       l.description, l.box_no, l.location, l.photos, l.status,
       coalesce(sum(t.qty),0)::numeric(12,3) AS balance,
       coalesce(sum(t.pcs),0) AS balance_pcs,
       (coalesce(sum(t.qty),0) * coalesce(l.fineness,1))::numeric(12,3) AS fine_balance,
       max(t.created_at) AS last_txn_at,
       count(t.id) AS txn_count
FROM rm_lots l LEFT JOIN rm_txns t ON t.lot_id = l.id
GROUP BY l.id;

-- Karigar outstanding: issued minus (finished + scrap returned), gross and fine
CREATE OR REPLACE VIEW v_rm_party_outstanding AS
SELECT p.id, p.name, p.party_type,
  coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)::numeric(12,3) AS issued_g,
  coalesce(sum(CASE WHEN t.txn_type IN ('FINISHED_IN','SCRAP_IN') THEN t.qty END),0)::numeric(12,3) AS returned_g,
  (coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)
   - coalesce(sum(CASE WHEN t.txn_type IN ('FINISHED_IN','SCRAP_IN') THEN t.qty END),0))::numeric(12,3) AS outstanding_g,
  (coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty * coalesce(t.fineness, l.fineness, 1) END),0)
   - coalesce(sum(CASE WHEN t.txn_type IN ('FINISHED_IN','SCRAP_IN') THEN t.qty * coalesce(t.fineness, l.fineness, 1) END),0))::numeric(12,3) AS outstanding_fine
FROM rm_parties p
LEFT JOIN rm_txns t ON t.party_id = p.id
LEFT JOIN rm_lots l ON l.id = t.lot_id
GROUP BY p.id;

-- Wastage per job: issued - finished - scrap
CREATE OR REPLACE VIEW v_rm_job_wastage AS
SELECT t.job_ref, t.party_id, p.name AS party_name,
  coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)::numeric(12,3) AS issued_g,
  coalesce(sum(CASE WHEN t.txn_type='FINISHED_IN' THEN t.qty END),0)::numeric(12,3) AS finished_g,
  coalesce(sum(CASE WHEN t.txn_type='SCRAP_IN' THEN t.qty END),0)::numeric(12,3) AS scrap_g,
  (coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)
   - coalesce(sum(CASE WHEN t.txn_type='FINISHED_IN' THEN t.qty END),0)
   - coalesce(sum(CASE WHEN t.txn_type='SCRAP_IN' THEN t.qty END),0))::numeric(12,3) AS wastage_g
FROM rm_txns t LEFT JOIN rm_parties p ON p.id = t.party_id
WHERE t.job_ref IS NOT NULL
GROUP BY t.job_ref, t.party_id, p.name;

-- RLS consistent with existing CRM tables
ALTER TABLE rm_parties ENABLE ROW LEVEL SECURITY;
ALTER TABLE rm_lots    ENABLE ROW LEVEL SECURITY;
ALTER TABLE rm_txns    ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth_only" ON rm_parties;
DROP POLICY IF EXISTS "auth_only" ON rm_lots;
DROP POLICY IF EXISTS "auth_only" ON rm_txns;
CREATE POLICY "auth_only" ON rm_parties FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_only" ON rm_lots    FOR ALL USING (auth.role() = 'authenticated');
CREATE POLICY "auth_only" ON rm_txns    FOR ALL USING (auth.role() = 'authenticated');

-- Photo storage bucket
INSERT INTO storage.buckets (id, name, public)
VALUES ('rm-photos','rm-photos', true)
ON CONFLICT (id) DO NOTHING;
DROP POLICY IF EXISTS "rm_photos_auth_write" ON storage.objects;
CREATE POLICY "rm_photos_auth_write" ON storage.objects
  FOR INSERT TO authenticated WITH CHECK (bucket_id = 'rm-photos');
DROP POLICY IF EXISTS "rm_photos_read" ON storage.objects;
CREATE POLICY "rm_photos_read" ON storage.objects
  FOR SELECT USING (bucket_id = 'rm-photos');;
