SET search_path TO app, public;

CREATE OR REPLACE FUNCTION app.set_user_locations(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_user  TEXT := btrim(COALESCE(p->>'username',''));
  v_uid   INT;
  v_home  TEXT := NULLIF(btrim(COALESCE(p->>'home_location','')),'');
  v_all   BOOLEAN := COALESCE((p->>'all_locations')::boolean, FALSE);
  v_codes JSONB := COALESCE(p->'locations','[]'::jsonb);
  v_home_id INT; c TEXT; v_id INT; v_n INT := 0;
BEGIN
  IF NOT app.is_admin() AND session_user NOT IN ('postgres','supabase_admin') THEN
    RAISE EXCEPTION 'Only an admin can change who sees which location.';
  END IF;
  SELECT user_id INTO v_uid FROM app_user WHERE lower(username)=lower(v_user);
  IF v_uid IS NULL THEN RAISE EXCEPTION 'User % not found.', v_user; END IF;

  IF v_home IS NOT NULL THEN
    SELECT location_id INTO v_home_id FROM location
     WHERE upper(code)=upper(v_home) OR upper(name)=upper(v_home);
    IF v_home_id IS NULL THEN RAISE EXCEPTION 'Location "%" not found.', v_home; END IF;
  END IF;

  UPDATE app_user SET home_location_id = CASE WHEN v_all THEN NULL ELSE v_home_id END
   WHERE user_id = v_uid;

  DELETE FROM user_location WHERE user_id = v_uid;
  IF NOT v_all THEN
    FOR c IN SELECT jsonb_array_elements_text(v_codes) LOOP
      SELECT location_id INTO v_id FROM location
       WHERE upper(code)=upper(btrim(c)) OR upper(name)=upper(btrim(c));
      IF v_id IS NULL THEN RAISE EXCEPTION 'Location "%" not found.', c; END IF;
      INSERT INTO user_location (user_id, location_id) VALUES (v_uid, v_id)
        ON CONFLICT DO NOTHING;
      v_n := v_n + 1;
    END LOOP;
  END IF;

  PERFORM app.log('UPDATE','app_user', v_user,
    CASE WHEN v_all THEN 'Given every location'
         ELSE 'Limited to '||COALESCE(v_home,'(no home)')||
              CASE WHEN v_n>0 THEN ' plus '||v_n||' more' ELSE '' END END);
  RETURN jsonb_build_object('ok',true,'username',v_user,
    'all_locations',v_all,'home',v_home,'extra',v_n);
END $fn$;
GRANT EXECUTE ON FUNCTION app.set_user_locations(JSONB) TO authenticated;

CREATE OR REPLACE FUNCTION app.trg_movement_location_right()
RETURNS trigger LANGUAGE plpgsql SET search_path = app, public AS $fn$
DECLARE v_from INT; v_ok BOOLEAN;
BEGIN
  IF auth.uid() IS NULL THEN RETURN NEW; END IF;
  IF app.is_admin() THEN RETURN NEW; END IF;
  SELECT location_id INTO v_from FROM jewel_code WHERE jewel_code_id = NEW.jewel_code_id;
  IF v_from IS NULL THEN RETURN NEW; END IF;
  SELECT v_from IN (SELECT app.visible_locations()) INTO v_ok;
  IF NOT v_ok THEN
    RAISE EXCEPTION 'That piece is at a location you do not hold. You can only move or sell stock from your own location.';
  END IF;
  RETURN NEW;
END $fn$;

DROP TRIGGER IF EXISTS movement_location_right ON app.stock_movement;
CREATE TRIGGER movement_location_right BEFORE INSERT ON app.stock_movement
  FOR EACH ROW EXECUTE FUNCTION app.trg_movement_location_right();

DROP VIEW IF EXISTS api.user_access;
CREATE VIEW api.user_access AS
SELECT u.username, u.full_name, u.email, r.code AS role_code, r.name AS role_name,
       u.is_active,
       COALESCE(hl.code,'ALL') AS home_location,
       (u.home_location_id IS NULL) AS all_locations,
       COALESCE((SELECT array_agg(l2.code ORDER BY l2.code)
                   FROM app.user_location ul JOIN app.location l2 USING (location_id)
                  WHERE ul.user_id = u.user_id), '{}') AS extra_locations,
       (SELECT array_agg(l3.code ORDER BY l3.code) FROM app.location l3
         WHERE u.home_location_id IS NULL OR l3.location_id = u.home_location_id
            OR l3.location_id IN (SELECT location_id FROM app.user_location
                                   WHERE user_id = u.user_id)) AS can_see
FROM app.app_user u
JOIN app.role r ON r.role_id = u.role_id
LEFT JOIN app.location hl ON hl.location_id = u.home_location_id
WHERE app.is_admin();
GRANT SELECT ON api.user_access TO authenticated;

CREATE OR REPLACE FUNCTION api.set_user_locations(p JSONB) RETURNS JSONB
LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public
AS $$ SELECT app.set_user_locations(p) $$;
GRANT EXECUTE ON FUNCTION api.set_user_locations(JSONB) TO authenticated;;
