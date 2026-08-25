-- ============================================================
-- 0023  Media, stored in Cloudflare R2.
--
-- The file itself never comes near this database. What is kept
-- here is the record of it: which piece (or which design) it
-- belongs to, what kind of file it is, its size and checksum,
-- and the storage key.
--
-- A photograph belongs to the PIECE — two pieces of one design
-- have different stones. A CAD or 3DM file belongs to the
-- DESIGN, because it is what the design is made from. Both are
-- allowed; exactly one must be given.
--
-- media_ref is issued from a sequence and baked into the file
-- name, so a file someone renames still finds its way home.
-- ============================================================
SET search_path TO app, public;

ALTER TABLE media_asset
  ADD COLUMN IF NOT EXISTS storage_provider TEXT NOT NULL DEFAULT 'R2',
  ADD COLUMN IF NOT EXISTS mime_type TEXT,
  ADD COLUMN IF NOT EXISTS caption TEXT,
  ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_media_ref ON media_asset(media_ref);
CREATE INDEX IF NOT EXISTS idx_media_jewel ON media_asset(jewel_code_id) WHERE jewel_code_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_media_style ON media_asset(style_id) WHERE style_id IS NOT NULL;

-- Reserve the reference and the storage key BEFORE the upload, so the key the
-- browser uploads to is the key we have recorded. No guessing afterwards.
CREATE OR REPLACE FUNCTION app.reserve_media(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code  TEXT := upper(btrim(COALESCE(p->>'jewel_code','')));
  v_style TEXT := upper(btrim(COALESCE(p->>'style_code','')));
  v_kind  media_kind := COALESCE(NULLIF(upper(btrim(COALESCE(p->>'kind',''))),''),'PHOTO')::media_kind;
  v_jc INT; v_st INT; v_ref TEXT; v_ext TEXT; v_key TEXT; v_rank INT;
BEGIN
  IF NOT (app.has_cap('editBom') OR app.is_admin()
          OR EXISTS (SELECT 1 FROM app_user u JOIN role r USING (role_id)
                      WHERE u.auth_uid = auth.uid() AND u.is_active AND r.code = 'GRAPHIC')) THEN
    RAISE EXCEPTION 'You do not have permission to upload media.';
  END IF;

  IF v_code <> '' THEN
    SELECT jewel_code_id INTO v_jc FROM jewel_code WHERE upper(jewel_code) = v_code;
    IF v_jc IS NULL THEN RAISE EXCEPTION 'Jewel code % not found.', v_code; END IF;
  ELSIF v_style <> '' THEN
    SELECT style_id INTO v_st FROM style WHERE upper(style_code) = v_style;
    IF v_st IS NULL THEN RAISE EXCEPTION 'Design % not found.', v_style; END IF;
  ELSE
    RAISE EXCEPTION 'A photograph needs a jewel code; a CAD file needs a design.';
  END IF;

  v_ext := lower(regexp_replace(COALESCE(p->>'file_name',''), '^.*\.', ''));
  IF v_ext = '' OR length(v_ext) > 8 THEN v_ext := 'bin'; END IF;

  SELECT COALESCE(max(rank_order),0)+1 INTO v_rank FROM media_asset
   WHERE (v_jc IS NOT NULL AND jewel_code_id = v_jc)
      OR (v_st IS NOT NULL AND style_id = v_st);

  INSERT INTO media_asset (jewel_code_id, style_id, kind, view_angle, rank_order,
                           file_name, mime_type, bytes, caption, uploaded_by, storage_provider)
  VALUES (v_jc, v_st, v_kind, NULLIF(btrim(COALESCE(p->>'view_angle','')),''), v_rank,
          NULLIF(btrim(COALESCE(p->>'file_name','')),''),
          NULLIF(btrim(COALESCE(p->>'mime_type','')),''),
          NULLIF(p->>'bytes','')::bigint,
          NULLIF(btrim(COALESCE(p->>'caption','')),''),
          app.current_user_id(), 'R2')
  RETURNING media_ref INTO v_ref;

  v_key := COALESCE(v_code, v_style) || '/' ||
           COALESCE(v_code, v_style) || '__' || v_kind::text || '__r' || v_rank ||
           '__' || v_ref || '.' || v_ext;
  UPDATE media_asset SET storage_key = v_key WHERE media_ref = v_ref;

  PERFORM app.log('INSERT','media_asset', v_ref,
                  'Reserved '||v_kind::text||' for '||COALESCE(v_code,v_style));
  RETURN jsonb_build_object('ok',true,'media_ref',v_ref,'storage_key',v_key,
                            'kind',v_kind::text,'rank',v_rank);
END $fn$;

-- Called after the browser has finished putting the file into R2.
CREATE OR REPLACE FUNCTION app.confirm_media(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_ref TEXT := btrim(COALESCE(p->>'media_ref',''));
BEGIN
  UPDATE media_asset
     SET bytes  = COALESCE(NULLIF(p->>'bytes','')::bigint, bytes),
         sha256 = COALESCE(NULLIF(btrim(COALESCE(p->>'sha256','')),''), sha256),
         width_px  = COALESCE(NULLIF(p->>'width','')::int, width_px),
         height_px = COALESCE(NULLIF(p->>'height','')::int, height_px),
         file_size_kb = COALESCE((NULLIF(p->>'bytes','')::bigint/1024)::int, file_size_kb)
   WHERE media_ref = v_ref;
  IF NOT FOUND THEN RAISE EXCEPTION 'Media reference % not found.', v_ref; END IF;
  RETURN jsonb_build_object('ok',true,'media_ref',v_ref);
END $fn$;

-- Removing a file is a record change; the object in R2 is swept separately.
CREATE OR REPLACE FUNCTION app.detach_media(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_ref TEXT := btrim(COALESCE(p->>'media_ref','')); v_key TEXT;
BEGIN
  IF NOT (app.has_cap('editBom') OR app.is_admin()
          OR EXISTS (SELECT 1 FROM app_user u JOIN role r USING (role_id)
                      WHERE u.auth_uid = auth.uid() AND u.is_active AND r.code='GRAPHIC')) THEN
    RAISE EXCEPTION 'You do not have permission to remove media.';
  END IF;
  SELECT storage_key INTO v_key FROM media_asset WHERE media_ref = v_ref;
  IF v_key IS NULL AND NOT EXISTS (SELECT 1 FROM media_asset WHERE media_ref=v_ref) THEN
    RAISE EXCEPTION 'Media reference % not found.', v_ref;
  END IF;
  UPDATE media_asset SET is_archived = TRUE WHERE media_ref = v_ref;
  PERFORM app.log('DELETE','media_asset', v_ref, 'Removed from the piece; object left in R2');
  RETURN jsonb_build_object('ok',true,'media_ref',v_ref,'storage_key',v_key);
END $fn$;

GRANT EXECUTE ON FUNCTION app.reserve_media(JSONB), app.confirm_media(JSONB),
  app.detach_media(JSONB) TO authenticated;

DROP VIEW IF EXISTS api.media;
CREATE VIEW api.media AS
SELECT m.media_ref, jc.jewel_code, s.style_code, m.kind::text AS kind, m.view_angle,
       m.rank_order, m.file_name, m.mime_type, m.bytes, m.sha256, m.caption,
       m.storage_provider, m.storage_key, m.width_px, m.height_px,
       m.is_catalogue_default, u.username AS uploaded_by, m.uploaded_at
FROM app.media_asset m
LEFT JOIN app.jewel_code jc ON jc.jewel_code_id = m.jewel_code_id
LEFT JOIN app.style s       ON s.style_id = m.style_id
LEFT JOIN app.app_user u    ON u.user_id = m.uploaded_by
WHERE NOT m.is_archived
  AND (jc.jewel_code_id IS NULL
       OR jc.location_id IS NULL
       OR jc.location_id IN (SELECT app.visible_locations()));
GRANT SELECT ON api.media TO authenticated;

CREATE OR REPLACE FUNCTION api.reserve_media(p JSONB) RETURNS JSONB
LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public AS $$ SELECT app.reserve_media(p) $$;
CREATE OR REPLACE FUNCTION api.confirm_media(p JSONB) RETURNS JSONB
LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public AS $$ SELECT app.confirm_media(p) $$;
CREATE OR REPLACE FUNCTION api.detach_media(p JSONB) RETURNS JSONB
LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public AS $$ SELECT app.detach_media(p) $$;
GRANT EXECUTE ON FUNCTION api.reserve_media(JSONB), api.confirm_media(JSONB),
  api.detach_media(JSONB) TO authenticated;;
