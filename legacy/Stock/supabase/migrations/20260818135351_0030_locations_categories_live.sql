
-- ─────────────────────────────────────────────────────────────────────────
-- 0030  Locations and categories, actually saved
--
-- The Settings screens for both were left over from the prototype: they
-- changed a JavaScript object and re-rendered, so adding a location looked
-- like it worked and disappeared on the next refresh. There was no write
-- path to the database at all. This adds one.
--
-- Deleting is deliberately not offered. A location that has ever held stock
-- is referenced by movements and by the pieces standing there; removing it
-- would orphan history. Retiring hides it from every picker instead, which
-- is what "remove" actually means here.
-- ─────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION app.upsert_location(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code TEXT := upper(btrim(coalesce(p->>'code','')));
  v_name TEXT := btrim(coalesce(p->>'name',''));
  v_kind TEXT := upper(btrim(coalesce(nullif(p->>'kind',''),'SHOWROOM')));
  v_city TEXT := nullif(btrim(coalesce(p->>'city','')),'');
  v_id   INT;
  v_new  BOOLEAN := false;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can add or change locations.';
  END IF;
  IF v_code !~ '^[A-Z0-9]{2,5}$' THEN
    RAISE EXCEPTION 'Location code must be 2 to 5 letters or digits — got "%".', v_code;
  END IF;
  IF length(v_name) < 2 THEN
    RAISE EXCEPTION 'Give the location a name.';
  END IF;
  IF v_kind NOT IN ('SHOWROOM','GODOWN','WORKSHOP','TRANSIT') THEN
    RAISE EXCEPTION 'Kind must be SHOWROOM, GODOWN, WORKSHOP or TRANSIT — got "%".', v_kind;
  END IF;

  SELECT location_id INTO v_id FROM app.location WHERE code = v_code;
  IF v_id IS NULL THEN
    v_new := true;
    INSERT INTO app.location (code, name, kind, city, is_active)
    VALUES (v_code, v_name, v_kind, v_city, true)
    RETURNING location_id INTO v_id;
  ELSE
    UPDATE app.location
       SET name = v_name, kind = v_kind, city = coalesce(v_city, city)
     WHERE location_id = v_id;
  END IF;

  PERFORM app.log(CASE WHEN v_new THEN 'INSERT' ELSE 'UPDATE' END,
                  'location', v_code, v_name || ' · ' || v_kind);
  RETURN jsonb_build_object('ok', true, 'code', v_code, 'name', v_name,
                            'kind', v_kind, 'created', v_new);
END $fn$;

CREATE OR REPLACE FUNCTION app.set_location_active(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code   TEXT := upper(btrim(coalesce(p->>'code','')));
  v_active BOOLEAN := coalesce((p->>'is_active')::boolean, true);
  v_id     INT;
  v_held   INT;
  v_left   INT;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can retire or restore a location.';
  END IF;
  SELECT location_id INTO v_id FROM app.location WHERE code = v_code;
  IF v_id IS NULL THEN RAISE EXCEPTION 'No location called "%".', v_code; END IF;

  IF NOT v_active THEN
    SELECT count(*) INTO v_held FROM app.jewel_code
     WHERE location_id = v_id AND stock_state = 'IN_STOCK';
    IF v_held > 0 THEN
      RAISE EXCEPTION 'Cannot retire % — % piece(s) are standing there. Move them first.',
        v_code, v_held;
    END IF;
    SELECT count(*) INTO v_left FROM app.location WHERE is_active AND location_id <> v_id;
    IF v_left = 0 THEN
      RAISE EXCEPTION 'This is the last active location. Stock has to be somewhere.';
    END IF;
  END IF;

  UPDATE app.location SET is_active = v_active WHERE location_id = v_id;
  PERFORM app.log('UPDATE', 'location', v_code,
                  CASE WHEN v_active THEN 'restored' ELSE 'retired' END);
  RETURN jsonb_build_object('ok', true, 'code', v_code, 'is_active', v_active);
END $fn$;

CREATE OR REPLACE FUNCTION app.upsert_category(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_name TEXT := btrim(coalesce(p->>'name',''));
  v_pre  TEXT := upper(btrim(coalesce(p->>'code_prefix','')));
  v_code TEXT := upper(btrim(coalesce(nullif(p->>'code',''), '')));
  v_id   INT;
  v_new  BOOLEAN := false;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can add or change categories.';
  END IF;
  IF length(v_name) < 3 THEN
    RAISE EXCEPTION 'Give the category a real name.';
  END IF;
  IF v_pre !~ '^[A-Z]{1,3}$' THEN
    RAISE EXCEPTION 'Code prefix must be 1 to 3 letters — got "%". It seeds new jewel codes.', v_pre;
  END IF;

  -- match on the existing row by code when editing, otherwise by name so the
  -- same category is not created twice under two spellings of one prefix
  IF v_code <> '' THEN
    SELECT category_id INTO v_id FROM app.category WHERE code = v_code;
  END IF;
  IF v_id IS NULL THEN
    SELECT category_id INTO v_id FROM app.category WHERE upper(name) = upper(v_name);
  END IF;

  IF v_id IS NULL THEN
    v_new := true;
    IF v_code = '' THEN
      v_code := upper(left(regexp_replace(v_name, '[^A-Za-z0-9]', '', 'g'), 12));
    END IF;
    IF EXISTS (SELECT 1 FROM app.category WHERE code = v_code) THEN
      v_code := v_code || (SELECT count(*)+1 FROM app.category)::text;
    END IF;
    INSERT INTO app.category (code, name, code_prefix, sort_order)
    VALUES (v_code, v_name, v_pre,
            (SELECT coalesce(max(sort_order),0)+1 FROM app.category))
    RETURNING category_id INTO v_id;
  ELSE
    UPDATE app.category SET name = v_name, code_prefix = v_pre WHERE category_id = v_id;
    SELECT code INTO v_code FROM app.category WHERE category_id = v_id;
  END IF;

  PERFORM app.log(CASE WHEN v_new THEN 'INSERT' ELSE 'UPDATE' END,
                  'category', v_code, v_name || ' · prefix ' || v_pre);
  RETURN jsonb_build_object('ok', true, 'code', v_code, 'name', v_name,
                            'code_prefix', v_pre, 'created', v_new);
END $fn$;

-- ── admin views, so the screens show what is really there ─────────────────
CREATE OR REPLACE VIEW api.locations
WITH (security_invoker = false) AS
SELECT l.code, l.name, l.kind, l.city, l.is_active,
       (SELECT count(*) FROM app.jewel_code j
         WHERE j.location_id = l.location_id AND j.stock_state = 'IN_STOCK') AS live_pieces,
       (SELECT count(*) FROM app.jewel_code j WHERE j.location_id = l.location_id) AS ever_held
  FROM app.location l
 WHERE app.is_admin()
 ORDER BY l.is_active DESC, l.location_id;

CREATE OR REPLACE VIEW api.categories
WITH (security_invoker = false) AS
SELECT c.code, c.name, c.code_prefix, c.sort_order,
       (SELECT count(*) FROM app.style s WHERE s.category_id = c.category_id) AS designs,
       (SELECT count(*) FROM app.jewel_code j
          JOIN app.style s2 ON s2.style_id = j.style_id
         WHERE s2.category_id = c.category_id) AS pieces
  FROM app.category c
 WHERE app.is_admin()
 ORDER BY c.sort_order, c.name;

CREATE OR REPLACE FUNCTION api.upsert_location(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.upsert_location(p) $$;
CREATE OR REPLACE FUNCTION api.set_location_active(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.set_location_active(p) $$;
CREATE OR REPLACE FUNCTION api.upsert_category(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.upsert_category(p) $$;

GRANT SELECT ON api.locations, api.categories TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.upsert_location(jsonb), api.set_location_active(jsonb),
                          api.upsert_category(jsonb) TO anon, authenticated;
REVOKE ALL ON FUNCTION app.upsert_location(jsonb), app.set_location_active(jsonb),
                       app.upsert_category(jsonb) FROM anon, authenticated;
;
