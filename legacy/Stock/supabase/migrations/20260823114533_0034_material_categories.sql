
-- ─────────────────────────────────────────────────────────────────────────
-- 0034  Materials get the six categories, a description and a size
--
-- mat_class was an enum of eight engineering-ish names. The six categories
-- here are the ones the business actually uses, and they are a table rather
-- than an enum so you can add one without a migration. mat_class stays
-- exactly as it is — the costing engine keys off METAL and LABOUR and must
-- not be disturbed by a renaming exercise.
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS app.material_category (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  sort_order  INT  NOT NULL DEFAULT 0,
  is_priceable BOOLEAN NOT NULL DEFAULT true,   -- false for labour
  note        TEXT
);

INSERT INTO app.material_category (code, name, sort_order, is_priceable, note) VALUES
  ('METAL',   'Metal',            1, true,  'Priced from its metal''s live rate, never marked up'),
  ('DIAMOND', 'Diamond',          2, true,  'Cut and polished'),
  ('POLKI',   'Diamond Polki',    3, true,  'Uncut, foil-backed'),
  ('SETTING', 'Setting Stones',   4, true,  'Coloured stones and pearls that are set'),
  ('PURAI',   'Purai Stones',     5, true,  'Kept separate from setting stones on purpose'),
  ('OTHER',   'Other Materials',  6, true,  'Findings, and anything not yet classified'),
  ('LABOUR',  'Making',           7, false, 'Not a material — the charge for making the piece')
ON CONFLICT (code) DO NOTHING;

ALTER TABLE app.material
  ADD COLUMN IF NOT EXISTS category    TEXT REFERENCES app.material_category(code),
  ADD COLUMN IF NOT EXISTS description TEXT,
  ADD COLUMN IF NOT EXISTS size        TEXT,
  ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT false;

-- Map from the old class. PEARL joins setting stones because that is what a
-- pearl is here; FINDING and OTHER become Other Materials.
UPDATE app.material SET category = CASE mat_class
    WHEN 'METAL'        THEN 'METAL'
    WHEN 'DIAMOND'      THEN 'DIAMOND'
    WHEN 'POLKI'        THEN 'POLKI'
    WHEN 'COLOUR_STONE' THEN 'SETTING'
    WHEN 'PEARL'        THEN 'SETTING'
    WHEN 'LABOUR'       THEN 'LABOUR'
    ELSE 'OTHER' END
 WHERE category IS NULL;

ALTER TABLE app.material ALTER COLUMN category SET NOT NULL;
CREATE INDEX IF NOT EXISTS material_category_idx ON app.material(category);

-- ── an unknown code arriving from an import ──────────────────────────────
-- app.resolve_material creates materials it has not seen. Those must land
-- somewhere obvious and be flagged, not quietly become a stone.
CREATE OR REPLACE FUNCTION app.trg_material_defaults() RETURNS trigger
LANGUAGE plpgsql SET search_path = app, public AS $fn$
BEGIN
  IF NEW.category IS NULL THEN
    NEW.category := CASE NEW.mat_class
      WHEN 'METAL' THEN 'METAL' WHEN 'DIAMOND' THEN 'DIAMOND'
      WHEN 'POLKI' THEN 'POLKI' WHEN 'COLOUR_STONE' THEN 'SETTING'
      WHEN 'PEARL' THEN 'SETTING' WHEN 'LABOUR' THEN 'LABOUR'
      ELSE 'OTHER' END;
    -- anything that fell through to Other has not really been classified
    IF NEW.category = 'OTHER' THEN NEW.needs_review := true; END IF;
  END IF;
  RETURN NEW;
END $fn$;

DROP TRIGGER IF EXISTS material_defaults ON app.material;
CREATE TRIGGER material_defaults BEFORE INSERT ON app.material
  FOR EACH ROW EXECUTE FUNCTION app.trg_material_defaults();

-- CCS arrived from Gati with no real classification
UPDATE app.material SET needs_review = true
 WHERE category = 'OTHER' AND mat_class NOT IN ('LABOUR');

-- ── read ─────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW api.material_category
WITH (security_invoker = false) AS
SELECT code, name, sort_order, is_priceable, note FROM app.material_category
ORDER BY sort_order;

CREATE OR REPLACE VIEW api.material
WITH (security_invoker = false) AS
SELECT m.item_code AS code, m.item_name AS name, m.description, m.size,
       m.category, mc.name AS category_name, mc.sort_order AS category_order,
       m.mat_class::text AS mat_class, m.default_uom::text AS uom, m.metal,
       m.is_active, m.needs_review,
       (SELECT count(*) FROM app.jewel_material_line l
         WHERE l.material_id = m.material_id)                    AS used_on_lines,
       (SELECT count(DISTINCT l.jewel_code_id) FROM app.jewel_material_line l
         WHERE l.material_id = m.material_id)                    AS used_on_pieces
  FROM app.material m
  JOIN app.material_category mc ON mc.code = m.category
 WHERE app.has_cap('materials');

GRANT SELECT ON api.material, api.material_category TO anon, authenticated;

-- ── write ────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION app.upsert_material(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code  TEXT := upper(btrim(coalesce(p->>'code','')));
  v_new   TEXT := upper(btrim(coalesce(p->>'new_code','')));
  v_name  TEXT := btrim(coalesce(p->>'name',''));
  v_desc  TEXT := nullif(btrim(coalesce(p->>'description','')),'');
  v_size  TEXT := nullif(btrim(coalesce(p->>'size','')),'');
  v_cat   TEXT := upper(btrim(coalesce(p->>'category','')));
  v_uom   TEXT := upper(btrim(coalesce(p->>'uom','')));
  v_metal TEXT := nullif(upper(btrim(coalesce(p->>'metal',''))),'');
  v_id INT; v_class app.material_class; v_created BOOLEAN := false;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to change the material master.';
  END IF;
  IF v_code = '' THEN RAISE EXCEPTION 'A material needs a code.'; END IF;
  IF NOT EXISTS (SELECT 1 FROM app.material_category WHERE code = v_cat) THEN
    RAISE EXCEPTION 'Category "%" is not one of %', v_cat,
      (SELECT string_agg(name,', ' ORDER BY sort_order) FROM app.material_category);
  END IF;

  -- the class the costing engine keys off follows the category
  v_class := CASE v_cat
    WHEN 'METAL' THEN 'METAL' WHEN 'DIAMOND' THEN 'DIAMOND'
    WHEN 'POLKI' THEN 'POLKI' WHEN 'SETTING' THEN 'COLOUR_STONE'
    WHEN 'PURAI' THEN 'COLOUR_STONE' WHEN 'LABOUR' THEN 'LABOUR'
    ELSE 'OTHER' END::app.material_class;

  IF v_cat = 'METAL' AND v_metal IS NULL THEN
    RAISE EXCEPTION 'A Metal material must say which metal it is — a rate cannot be found otherwise.';
  END IF;

  SELECT material_id INTO v_id FROM app.material WHERE item_code = v_code;

  IF v_id IS NULL THEN
    v_created := true;
    IF length(v_name) < 2 THEN RAISE EXCEPTION 'Give the material a name.'; END IF;
    INSERT INTO app.material (item_code, item_name, description, size, mat_class,
                              category, default_uom, metal, is_active, needs_review)
    VALUES (v_code, v_name, v_desc, v_size, v_class, v_cat,
            COALESCE(nullif(v_uom,''),'CT')::app.uom_code, v_metal, true, false)
    RETURNING material_id INTO v_id;
  ELSE
    -- renaming the code moves every bill of materials that points at it, so
    -- only an admin may, and only to a code nobody else holds
    IF v_new <> '' AND v_new <> v_code THEN
      IF NOT app.is_admin() THEN
        RAISE EXCEPTION 'Only an admin can change a material code.';
      END IF;
      IF EXISTS (SELECT 1 FROM app.material WHERE item_code = v_new) THEN
        RAISE EXCEPTION 'Code "%" is already used by another material.', v_new;
      END IF;
      UPDATE app.material SET item_code = v_new WHERE material_id = v_id;
      PERFORM app.log('UPDATE','material', v_code, 'code renamed to '||v_new);
      v_code := v_new;
    END IF;
    UPDATE app.material
       SET item_name = COALESCE(nullif(v_name,''), item_name),
           description = COALESCE(v_desc, description),
           size = COALESCE(v_size, size),
           category = v_cat, mat_class = v_class,
           default_uom = COALESCE(nullif(v_uom,'')::app.uom_code, default_uom),
           metal = CASE WHEN v_cat='METAL' THEN v_metal ELSE NULL END,
           needs_review = false
     WHERE material_id = v_id;
  END IF;

  PERFORM app.log(CASE WHEN v_created THEN 'INSERT' ELSE 'UPDATE' END,
                  'material', v_code, v_name || ' · ' || v_cat);
  RETURN jsonb_build_object('ok', true, 'code', v_code, 'created', v_created,
                            'category', v_cat);
END $fn$;

CREATE OR REPLACE FUNCTION api.upsert_material(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.upsert_material(p) $$;
GRANT EXECUTE ON FUNCTION api.upsert_material(jsonb) TO anon, authenticated;
REVOKE ALL ON FUNCTION app.upsert_material(jsonb) FROM anon, authenticated;
;
