-- 0038b  order the "recent" list by scan_id, not scanned_at.
-- Several scans inside one transaction share now(), so scanned_at is not a
-- reliable tiebreaker; scan_id always is.
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

  IF v_c.status <> 'OPEN' AND v_c.result IS NOT NULL THEN
    RETURN v_c.result;
  END IF;

  WITH expected AS (
    SELECT j.jewel_code_id, j.jewel_code
      FROM jewel_code j
     WHERE j.location_id = v_c.location_id
       AND app.countable_state(j.stock_state)
  ), scanned AS (
    SELECT s.scan_id, s.jewel_code_id, s.scanned_at, j.jewel_code,
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
        SELECT jsonb_agg(q.x ORDER BY q.scan_id DESC) FROM (
          SELECT s.scan_id, jsonb_build_object(
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
            FROM scanned s ORDER BY s.scan_id DESC LIMIT 12) q), '[]'::jsonb),
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
;
