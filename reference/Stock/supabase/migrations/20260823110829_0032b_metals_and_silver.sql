
-- ─────────────────────────────────────────────────────────────────────────
-- 0032  Metals become first-class, and silver stops being gold
--
-- app.metal_purity held karats and 925 in one list with a single factor
-- column, and every consumer multiplied that factor by ONE rate: the pure
-- gold rate. So 925 silver priced at 0.925 x gold. A purity now belongs to a
-- metal, and each metal carries its own rate.
--
-- Additive except for one deliberate correction: the 35 silver sale rates.
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS app.metal (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  pure_rate   NUMERIC(14,4) NOT NULL CHECK (pure_rate > 0),
  rate_as_on  TIMESTAMPTZ NOT NULL DEFAULT now(),
  unit        TEXT NOT NULL DEFAULT 'GM',
  note        TEXT,
  is_active   BOOLEAN NOT NULL DEFAULT true
);
COMMENT ON TABLE app.metal IS
  'One live rate per metal, typed in by an admin. No buffer and no GST field: '
  'the number here is the number pricing uses, so what you type is what you get.';

INSERT INTO app.metal (code, name, pure_rate, note) VALUES
  ('GOLD',  'Gold',    15481, 'Pure 24K per gram, incl. GST'),
  ('SILVER','Silver',    260, 'Pure 999 per gram, incl. GST')
ON CONFLICT (code) DO NOTHING;

ALTER TABLE app.metal_purity
  ADD COLUMN IF NOT EXISTS metal TEXT REFERENCES app.metal(code),
  ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;

UPDATE app.metal_purity SET metal = 'GOLD'   WHERE karat IN ('24K','22K','18K','14K');
UPDATE app.metal_purity SET metal = 'SILVER' WHERE karat = '925';

-- 925 was carrying gold's 0.925 sale factor. Silver sells at the 999 rate
-- (factor 1.0) and costs at its true 0.925 — a 7.5 point spread, deliberate.
UPDATE app.metal_purity
   SET sale_factor = 1.0000, true_fineness = 0.9250
 WHERE karat = '925';

INSERT INTO app.metal_purity (karat, sale_factor, true_fineness, metal)
SELECT '999', 1.0000, 1.0000, 'SILVER'
WHERE NOT EXISTS (SELECT 1 FROM app.metal_purity WHERE karat = '999');

UPDATE app.metal_purity SET sort_order = CASE karat
  WHEN '24K' THEN 1 WHEN '22K' THEN 2 WHEN '18K' THEN 3 WHEN '14K' THEN 4
  WHEN '999' THEN 1 WHEN '925' THEN 2 ELSE 9 END;

ALTER TABLE app.metal_purity ALTER COLUMN metal SET NOT NULL;

ALTER TABLE app.material
  ADD COLUMN IF NOT EXISTS metal TEXT REFERENCES app.metal(code);

UPDATE app.material SET metal = 'GOLD'
 WHERE mat_class = 'METAL' AND item_code <> 'S925';
UPDATE app.material SET metal = 'SILVER'
 WHERE item_code = 'S925';

ALTER TABLE app.material DROP CONSTRAINT IF EXISTS material_metal_required;
ALTER TABLE app.material
  ADD CONSTRAINT material_metal_required
  CHECK (mat_class <> 'METAL' OR metal IS NOT NULL) NOT VALID;
ALTER TABLE app.material VALIDATE CONSTRAINT material_metal_required;

CREATE OR REPLACE FUNCTION app.metal_rate(p_karat TEXT, p_side TEXT DEFAULT 'SALE')
RETURNS NUMERIC
LANGUAGE sql STABLE SET search_path = app, public AS $$
  SELECT round(m.pure_rate * CASE WHEN upper(p_side) = 'COST'
                                  THEN mp.true_fineness ELSE mp.sale_factor END)
    FROM app.metal_purity mp
    JOIN app.metal m ON m.code = mp.metal
   WHERE mp.karat = p_karat
$$;
COMMENT ON FUNCTION app.metal_rate(TEXT,TEXT) IS
  'Live per-gram rate for a purity. SALE uses the sale factor, COST the true '
  'fineness. Reads the rate of the metal that purity belongs to.';

-- ── the correction ────────────────────────────────────────────────────────
UPDATE app.jewel_material_line l
   SET sale_rate = app.metal_rate('925','SALE')
  FROM app.material m
 WHERE m.material_id = l.material_id
   AND m.item_code = 'S925';

INSERT INTO app.activity_log (action, table_name, record_pk, detail, user_id)
SELECT 'UPDATE', 'jewel_material_line', 'S925',
       'Silver sale rate corrected from 14320/g (pure gold x 0.925) to '
       || app.metal_rate('925','SALE')::text || '/g across ' || count(*)
       || ' lines on ' || count(DISTINCT l.jewel_code_id) || ' pieces', 1
  FROM app.jewel_material_line l JOIN app.material m USING (material_id)
 WHERE m.item_code = 'S925';
;
