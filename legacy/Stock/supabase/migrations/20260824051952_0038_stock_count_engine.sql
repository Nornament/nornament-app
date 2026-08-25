-- 0038  stock count: real, resumable, server-side
--------------------------------------------------------------------

ALTER TABLE app.stock_count
  ADD COLUMN IF NOT EXISTS result jsonb;

ALTER TABLE app.stock_count_scan
  ADD COLUMN IF NOT EXISTS verdict text;

-- one open count per location, ever
CREATE UNIQUE INDEX IF NOT EXISTS stock_count_one_open_per_location
  ON app.stock_count (location_id) WHERE status = 'OPEN';

CREATE INDEX IF NOT EXISTS stock_count_scan_count_seen
  ON app.stock_count_scan (count_id, scanned_at DESC);

--------------------------------------------------------------------
-- what a piece must be to count as "should be on this shelf"
--------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.countable_state(s app.stock_state)
RETURNS boolean LANGUAGE sql IMMUTABLE AS
$$ SELECT s IN ('IN_STOCK','RESERVED') $$;

--------------------------------------------------------------------
-- open (or resume) a count
--------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.open_count(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'app','public' AS $function$
DECLARE
  v_loc  INT;
  v_key  TEXT := btrim(COALESCE(p->>'location',''));
  v_id   INT;
  v_ref  TEXT;
  v_code TEXT;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to run a stock count.';
  END IF;

  SELECT location_id, code INTO v_loc, v_code FROM location
   WHERE (v_key ~ '^[0-9]+$' AND location_id = v_key::int)
      OR upper(code) = upper(v_key)
      OR upper(name) = upper(v_key);
  IF v_loc IS NULL THEN
    RAISE EXCEPTION 'Location "%" not found.', v_key;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM app.visible_locations() vl WHERE vl = v_loc) THEN
    RAISE EXCEPTION 'You cannot count %.', v_code;
  END IF;

  SELECT count_id INTO v_id FROM stock_count
   WHERE location_id = v_loc AND status = 'OPEN';

  IF v_id IS NULL THEN
    v_ref := 'SC-' || to_char(CURRENT_DATE,'YYMMDD') || '-' || v_code;
    IF EXISTS (SELECT 1 FROM stock_count WHERE count_ref = v_ref) THEN
      v_ref := v_ref || '-' || (SELECT count(*)+1 FROM stock_count
                                 WHERE count_ref LIKE v_ref || '%');
    END IF;
    INSERT INTO stock_count (count_ref, location_id, status, counted_by)
    VALUES (v_ref, v_loc, 'OPEN', app.current_user_id())
    RETURNING count_id INTO v_id;
    PERFORM app.log('INSERT','stock_count',v_ref,'Count opened at '||v_code);
  END IF;

  RETURN app.count_state(jsonb_build_object('count_id', v_id));
END $function$;

--------------------------------------------------------------------
-- live state of a count
--------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.count_state(p jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'app','public' AS $function$
DECLARE
  v_id  INT := NULLIF(p->>'count_id','')::int;
  v_c   RECORD;
  v_out jsonb;
BEGIN
  IF v_id IS NULL THEN RAISE EXCEPTION 'count_id is required.'; END IF;
  SELECT sc.*, l.code AS loc_code, l.name AS loc_name,
         u.full_name AS by_name
    INTO v_c
    FROM stock_count sc
    JOIN location l USING (location_id)
    LEFT JOIN app_user u ON u.user_id = sc.counted_by
   WHERE sc.count_id = v_id;
  IF v_c IS NULL THEN RAISE EXCEPTION 'Count % not found.', v_id; END IF;
  IF NOT EXISTS (SELECT 1 FROM app.visible_locations() vl WHERE vl = v_c.location_id) THEN
    RAISE EXCEPTION 'You cannot see that count.';
  END IF;

  -- a closed count is frozen; never recompute it
  IF v_c.status <> 'OPEN' AND v_c.result IS NOT NULL THEN
    RETURN v_c.result;
  END IF;

  WITH expected AS (
    SELECT j.jewel_code_id, j.jewel_code
      FROM jewel_code j
     WHERE j.location_id = v_c.location_id
       AND app.countable_state(j.stock_state)
  ), scanned AS (
    SELECT s.jewel_code_id, s.scanned_at, j.jewel_code,
           j.stock_state, j.location_id AS home_id, hl.code AS home_code
      FROM stock_count_scan s
      JOIN jewel_code j USING (jewel_code_id)
      LEFT JOIN location hl ON hl.location_id = j.location_id
     WHERE s.count_id = v_id
  )
  SELECT jsonb_build_object(
    'count_id',   v_c.count_id,
    'count_ref',  v_c.count_ref,
    'status',     v_c.status,
    'location_id',v_c.location_id,
    'location',   v_c.loc_code,
    'location_name', v_c.loc_name,
    'started_at', v_c.started_at,
    'closed_at',  v_c.closed_at,
    'counted_by', v_c.by_name,
    'expected',   (SELECT count(*) FROM expected),
    'found',      (SELECT count(*) FROM scanned s WHERE EXISTS
                     (SELECT 1 FROM expected e WHERE e.jewel_code_id = s.jewel_code_id)),
    'unexpected', (SELECT count(*) FROM scanned s WHERE NOT EXISTS
                     (SELECT 1 FROM expected e WHERE e.jewel_code_id = s.jewel_code_id)),
    'missing',    (SELECT count(*) FROM expected e WHERE NOT EXISTS
                     (SELECT 1 FROM scanned s WHERE s.jewel_code_id = e.jewel_code_id)),
    'scanned',    (SELECT count(*) FROM scanned),
    'recent',     COALESCE((
        SELECT jsonb_agg(x ORDER BY x->>'at' DESC) FROM (
          SELECT jsonb_build_object(
                   'code', s.jewel_code,
                   'at',   s.scanned_at,
                   'verdict', CASE
                     WHEN EXISTS (SELECT 1 FROM expected e WHERE e.jewel_code_id = s.jewel_code_id)
                       THEN 'FOUND'
                     WHEN NOT app.countable_state(s.stock_state) THEN 'NOT_STOCK'
                     ELSE 'ELSEWHERE' END,
                   'note', CASE
                     WHEN EXISTS (SELECT 1 FROM expected e WHERE e.jewel_code_id = s.jewel_code_id)
                       THEN NULL
                     WHEN NOT app.countable_state(s.stock_state)
                       THEN 'books say ' || replace(s.stock_state::text,'_',' ')
                     ELSE 'books say ' || COALESCE(s.home_code,'no location') END
                 ) AS x
            FROM scanned s ORDER BY s.scanned_at DESC LIMIT 12) q), '[]'::jsonb),
    'missing_list', COALESCE((
        SELECT jsonb_agg(e.jewel_code ORDER BY e.jewel_code)
          FROM expected e WHERE NOT EXISTS
            (SELECT 1 FROM scanned s WHERE s.jewel_code_id = e.jewel_code_id)), '[]'::jsonb),
    'unexpected_list', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                 'code', s.jewel_code,
                 'verdict', CASE WHEN NOT app.countable_state(s.stock_state)
                                 THEN 'NOT_STOCK' ELSE 'ELSEWHERE' END,
                 'note', CASE WHEN NOT app.countable_state(s.stock_state)
                              THEN 'books say ' || replace(s.stock_state::text,'_',' ')
                              ELSE 'books say ' || COALESCE(s.home_code,'no location') END)
                 ORDER BY s.jewel_code)
          FROM scanned s WHERE NOT EXISTS
            (SELECT 1 FROM expected e WHERE e.jewel_code_id = s.jewel_code_id)), '[]'::jsonb)
  ) INTO v_out;

  RETURN v_out;
END $function$;

--------------------------------------------------------------------
-- scan one code into an open count
--------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.scan_piece(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'app','public' AS $function$
DECLARE
  v_id    INT  := NULLIF(p->>'count_id','')::int;
  v_raw   TEXT := btrim(COALESCE(p->>'code',''));
  v_code  TEXT;
  v_loc   INT;
  v_stat  TEXT;
  v_jc    INT;
  v_state stock_state;
  v_home  INT;
  v_homec TEXT;
  v_verd  TEXT;
  v_note  TEXT;
  v_new   BOOLEAN := TRUE;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to run a stock count.';
  END IF;
  IF v_id IS NULL THEN RAISE EXCEPTION 'count_id is required.'; END IF;

  SELECT location_id, status INTO v_loc, v_stat FROM stock_count WHERE count_id = v_id;
  IF v_loc IS NULL THEN RAISE EXCEPTION 'Count % not found.', v_id; END IF;
  IF v_stat <> 'OPEN' THEN RAISE EXCEPTION 'That count is already %.', lower(v_stat); END IF;

  -- barcode scanners append suffixes; take the part before a double underscore
  v_code := upper(split_part(v_raw,'__',1));
  v_code := regexp_replace(v_code,'\s+','','g');
  IF v_code = '' THEN RAISE EXCEPTION 'Nothing scanned.'; END IF;

  SELECT j.jewel_code_id, j.stock_state, j.location_id, l.code
    INTO v_jc, v_state, v_home, v_homec
    FROM jewel_code j LEFT JOIN location l ON l.location_id = j.location_id
   WHERE upper(j.jewel_code) = v_code;

  IF v_jc IS NULL THEN
    RETURN jsonb_build_object('verdict','UNKNOWN','code',v_code,
      'note','no such piece in the system',
      'state', app.count_state(jsonb_build_object('count_id',v_id)));
  END IF;

  IF EXISTS (SELECT 1 FROM stock_count_scan WHERE count_id=v_id AND jewel_code_id=v_jc) THEN
    v_new := FALSE;
  END IF;

  IF v_home IS NOT DISTINCT FROM v_loc AND app.countable_state(v_state) THEN
    v_verd := 'FOUND'; v_note := NULL;
  ELSIF NOT app.countable_state(v_state) THEN
    v_verd := 'NOT_STOCK'; v_note := 'books say ' || replace(v_state::text,'_',' ');
  ELSE
    v_verd := 'ELSEWHERE'; v_note := 'books say ' || COALESCE(v_homec,'no location');
  END IF;

  INSERT INTO stock_count_scan (count_id, jewel_code_id, scanned_by, verdict)
  VALUES (v_id, v_jc, app.current_user_id(), v_verd)
  ON CONFLICT (count_id, jewel_code_id) DO NOTHING;

  RETURN jsonb_build_object(
    'verdict', CASE WHEN v_new THEN v_verd ELSE 'ALREADY' END,
    'first_verdict', v_verd,
    'code', (SELECT jewel_code FROM jewel_code WHERE jewel_code_id=v_jc),
    'note', CASE WHEN v_new THEN v_note ELSE 'already scanned in this count' END,
    'state', app.count_state(jsonb_build_object('count_id',v_id)));
END $function$;

--------------------------------------------------------------------
-- undo a scan
--------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.unscan_piece(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'app','public' AS $function$
DECLARE
  v_id INT := NULLIF(p->>'count_id','')::int;
  v_code TEXT := upper(regexp_replace(btrim(COALESCE(p->>'code','')),'\s+','','g'));
  v_stat TEXT;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to run a stock count.';
  END IF;
  SELECT status INTO v_stat FROM stock_count WHERE count_id=v_id;
  IF v_stat IS NULL THEN RAISE EXCEPTION 'Count % not found.', v_id; END IF;
  IF v_stat <> 'OPEN' THEN RAISE EXCEPTION 'That count is already %.', lower(v_stat); END IF;

  DELETE FROM stock_count_scan s USING jewel_code j
   WHERE s.jewel_code_id = j.jewel_code_id
     AND s.count_id = v_id AND upper(j.jewel_code) = v_code;

  RETURN app.count_state(jsonb_build_object('count_id',v_id));
END $function$;

--------------------------------------------------------------------
-- close (or cancel) a count, freezing the result
--------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.close_count(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'app','public' AS $function$
DECLARE
  v_id   INT  := NULLIF(p->>'count_id','')::int;
  v_can  BOOLEAN := COALESCE((p->>'cancel')::boolean, FALSE);
  v_stat TEXT;
  v_ref  TEXT;
  v_res  jsonb;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to run a stock count.';
  END IF;
  SELECT status, count_ref INTO v_stat, v_ref FROM stock_count WHERE count_id=v_id;
  IF v_stat IS NULL THEN RAISE EXCEPTION 'Count % not found.', v_id; END IF;
  IF v_stat <> 'OPEN' THEN RAISE EXCEPTION 'That count is already %.', lower(v_stat); END IF;

  IF v_can THEN
    UPDATE stock_count SET status='CANCELLED', closed_at=now() WHERE count_id=v_id;
    PERFORM app.log('UPDATE','stock_count',v_ref,'Count cancelled');
    RETURN jsonb_build_object('cancelled', true, 'count_ref', v_ref);
  END IF;

  v_res := app.count_state(jsonb_build_object('count_id',v_id));
  v_res := v_res || jsonb_build_object('status','CLOSED','closed_at',now());

  UPDATE stock_count
     SET status='CLOSED', closed_at=now(), result=v_res,
         notes = COALESCE(NULLIF(btrim(p->>'notes'),''), notes)
   WHERE count_id=v_id;

  PERFORM app.log('UPDATE','stock_count',v_ref,
    format('Count closed: %s of %s found, %s missing, %s unexpected',
      v_res->>'found', v_res->>'expected', v_res->>'missing', v_res->>'unexpected'));

  RETURN v_res;
END $function$;

--------------------------------------------------------------------
-- list of counts visible to the caller
--------------------------------------------------------------------
DROP VIEW IF EXISTS api.stock_count;
CREATE VIEW api.stock_count
WITH (security_invoker = false) AS
SELECT sc.count_id, sc.count_ref, sc.location_id, l.code AS location,
       l.name AS location_name, sc.status, sc.started_at, sc.closed_at,
       u.full_name AS counted_by, sc.notes, sc.result,
       (SELECT count(*) FROM app.stock_count_scan s WHERE s.count_id = sc.count_id) AS scans
  FROM app.stock_count sc
  JOIN app.location l USING (location_id)
  LEFT JOIN app.app_user u ON u.user_id = sc.counted_by
 WHERE sc.location_id IN (SELECT app.visible_locations());

GRANT SELECT ON api.stock_count TO authenticated;

--------------------------------------------------------------------
-- api wrappers
--------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.open_count(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path TO 'app','public'
AS $$ SELECT app.open_count(p) $$;

CREATE OR REPLACE FUNCTION api.scan_piece(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path TO 'app','public'
AS $$ SELECT app.scan_piece(p) $$;

CREATE OR REPLACE FUNCTION api.unscan_piece(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path TO 'app','public'
AS $$ SELECT app.unscan_piece(p) $$;

CREATE OR REPLACE FUNCTION api.count_state(p jsonb) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'app','public'
AS $$ SELECT app.count_state(p) $$;

CREATE OR REPLACE FUNCTION api.close_count(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path TO 'app','public'
AS $$ SELECT app.close_count(p) $$;

REVOKE ALL ON FUNCTION api.open_count(jsonb), api.scan_piece(jsonb),
                       api.unscan_piece(jsonb), api.count_state(jsonb),
                       api.close_count(jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION api.open_count(jsonb), api.scan_piece(jsonb),
                          api.unscan_piece(jsonb), api.count_state(jsonb),
                          api.close_count(jsonb) TO authenticated;
;
