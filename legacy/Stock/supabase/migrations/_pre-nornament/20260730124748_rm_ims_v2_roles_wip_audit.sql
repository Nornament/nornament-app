-- ===== 1. Profiles & roles =====
CREATE TABLE IF NOT EXISTS profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email text,
  display_name text,
  role text NOT NULL DEFAULT 'staff' CHECK (role IN ('admin','staff','viewer')),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz DEFAULT now()
);

-- role helper (security definer so RLS on profiles doesn't recurse)
CREATE OR REPLACE FUNCTION rm_role() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT coalesce((SELECT role FROM profiles WHERE id = auth.uid() AND active), 'viewer') $$;

-- auto-create profile on signup; first user ever becomes admin
CREATE OR REPLACE FUNCTION handle_new_user() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO profiles (id, email, role)
  VALUES (NEW.id, NEW.email,
    CASE WHEN NOT EXISTS (SELECT 1 FROM profiles) THEN 'admin' ELSE 'staff' END)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END; $$;
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- seed profiles for existing users as admin (they are the owners today)
INSERT INTO profiles (id, email, role)
SELECT id, email, 'admin' FROM auth.users
ON CONFLICT (id) DO NOTHING;

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "profiles_read" ON profiles;
DROP POLICY IF EXISTS "profiles_admin_write" ON profiles;
CREATE POLICY "profiles_read" ON profiles FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "profiles_admin_write" ON profiles FOR UPDATE USING (rm_role() = 'admin');

-- ===== 2. WIP =====
CREATE TABLE IF NOT EXISTS wip_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  wip_code text NOT NULL,
  name text,
  description text,
  stage text NOT NULL DEFAULT 'Design',
  party_id uuid REFERENCES rm_parties(id),   -- current holder
  order_ref text,                            -- link to CRM order/client
  photos jsonb NOT NULL DEFAULT '[]',
  data jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','cancelled')),
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS wip_jobs_code_unique ON wip_jobs (upper(wip_code));

CREATE TABLE IF NOT EXISTS wip_moves (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  wip_id uuid NOT NULL REFERENCES wip_jobs(id) ON DELETE CASCADE,
  from_stage text, to_stage text,
  party_id uuid REFERENCES rm_parties(id),
  remarks text,
  photos jsonb NOT NULL DEFAULT '[]',
  created_by text,
  created_at timestamptz DEFAULT now()
);

ALTER TABLE rm_txns ADD COLUMN IF NOT EXISTS wip_id uuid REFERENCES wip_jobs(id);
CREATE INDEX IF NOT EXISTS rm_txns_wip_idx ON rm_txns (wip_id);

-- default editable stages
INSERT INTO settings (key, value)
VALUES ('wip_stages', '["Design","Casting","Setting","Polish","QC","Done"]')
ON CONFLICT (key) DO NOTHING;

-- WIP material summary
CREATE OR REPLACE VIEW v_wip_materials AS
SELECT t.wip_id,
  coalesce(l.material, CASE WHEN t.txn_type='FINISHED_IN' THEN 'product' ELSE 'other' END) AS material,
  coalesce(l.uom,'g') AS uom,
  coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)::numeric(12,3) AS issued,
  coalesce(sum(CASE WHEN t.txn_type='FINISHED_IN' THEN t.qty END),0)::numeric(12,3) AS in_product,
  coalesce(sum(CASE WHEN t.txn_type='SCRAP_IN' THEN t.qty END),0)::numeric(12,3) AS scrap,
  coalesce(sum(CASE WHEN t.txn_type='LOSS_OUT' THEN -t.qty END),0)::numeric(12,3) AS loss,
  coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.pcs END),0) AS pcs_issued
FROM rm_txns t LEFT JOIN rm_lots l ON l.id = t.lot_id
WHERE t.wip_id IS NOT NULL
GROUP BY t.wip_id, 2, 3;
ALTER VIEW v_wip_materials SET (security_invoker = true);

-- ===== 3. Audit trail =====
CREATE TABLE IF NOT EXISTS rm_audit (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  table_name text NOT NULL,
  row_id uuid,
  action text NOT NULL,
  old_data jsonb,
  new_data jsonb,
  user_id uuid,
  user_email text,
  created_at timestamptz DEFAULT now()
);
ALTER TABLE rm_audit ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "audit_admin_read" ON rm_audit;
CREATE POLICY "audit_admin_read" ON rm_audit FOR SELECT USING (rm_role() = 'admin');

CREATE OR REPLACE FUNCTION rm_audit_fn() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO rm_audit (table_name, row_id, action, old_data, new_data, user_id, user_email)
  VALUES (TG_TABLE_NAME,
          coalesce((CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END)),
          TG_OP,
          CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END,
          CASE WHEN TG_OP IN ('UPDATE','INSERT') THEN to_jsonb(NEW) END,
          auth.uid(),
          (SELECT email FROM profiles WHERE id = auth.uid()));
  RETURN coalesce(NEW, OLD);
END; $$;
DROP TRIGGER IF EXISTS audit_rm_txns ON rm_txns;
CREATE TRIGGER audit_rm_txns AFTER UPDATE OR DELETE ON rm_txns FOR EACH ROW EXECUTE FUNCTION rm_audit_fn();
DROP TRIGGER IF EXISTS audit_rm_lots ON rm_lots;
CREATE TRIGGER audit_rm_lots AFTER UPDATE OR DELETE ON rm_lots FOR EACH ROW EXECUTE FUNCTION rm_audit_fn();
DROP TRIGGER IF EXISTS audit_wip_jobs ON wip_jobs;
CREATE TRIGGER audit_wip_jobs AFTER UPDATE OR DELETE ON wip_jobs FOR EACH ROW EXECUTE FUNCTION rm_audit_fn();

-- ===== 4. Balance guards on edit/delete too =====
CREATE OR REPLACE FUNCTION rm_check_balance() RETURNS trigger AS $$
DECLARE bal numeric;
BEGIN
  IF NEW.lot_id IS NOT NULL THEN
    SELECT coalesce(sum(qty),0) INTO bal FROM rm_txns
      WHERE lot_id = NEW.lot_id AND (TG_OP='INSERT' OR id <> OLD.id);
    IF bal + NEW.qty < -0.0005 THEN
      RAISE EXCEPTION 'Insufficient balance in lot: have %, this entry would make it negative', bal;
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS rm_txns_balance_check ON rm_txns;
CREATE TRIGGER rm_txns_balance_check BEFORE INSERT OR UPDATE ON rm_txns
  FOR EACH ROW EXECUTE FUNCTION rm_check_balance();

CREATE OR REPLACE FUNCTION rm_check_balance_del() RETURNS trigger AS $$
DECLARE bal numeric;
BEGIN
  IF OLD.lot_id IS NOT NULL THEN
    SELECT coalesce(sum(qty),0) INTO bal FROM rm_txns WHERE lot_id = OLD.lot_id AND id <> OLD.id;
    IF bal < -0.0005 THEN
      RAISE EXCEPTION 'Cannot delete: lot balance would go negative (%)', bal;
    END IF;
  END IF;
  RETURN OLD;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS rm_txns_balance_check_del ON rm_txns;
CREATE TRIGGER rm_txns_balance_check_del BEFORE DELETE ON rm_txns
  FOR EACH ROW EXECUTE FUNCTION rm_check_balance_del();

-- ===== 5. Role-based RLS on IMS tables =====
DROP POLICY IF EXISTS "auth_only" ON rm_parties;
DROP POLICY IF EXISTS "auth_only" ON rm_lots;
DROP POLICY IF EXISTS "auth_only" ON rm_txns;
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['rm_parties','rm_lots','rm_txns','wip_jobs','wip_moves'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS "sel" ON %I', t);
    EXECUTE format('DROP POLICY IF EXISTS "ins" ON %I', t);
    EXECUTE format('DROP POLICY IF EXISTS "upd" ON %I', t);
    EXECUTE format('DROP POLICY IF EXISTS "del" ON %I', t);
    EXECUTE format('CREATE POLICY "sel" ON %I FOR SELECT USING (auth.role() = ''authenticated'')', t);
    EXECUTE format('CREATE POLICY "ins" ON %I FOR INSERT WITH CHECK (rm_role() IN (''admin'',''staff''))', t);
    EXECUTE format('CREATE POLICY "upd" ON %I FOR UPDATE USING (rm_role() = ''admin'')', t);
    EXECUTE format('CREATE POLICY "del" ON %I FOR DELETE USING (rm_role() = ''admin'')', t);
  END LOOP;
END $$;;
