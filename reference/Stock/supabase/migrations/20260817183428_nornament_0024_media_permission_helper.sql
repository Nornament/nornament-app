-- one place that answers "may this person touch media", used by all three
-- media functions, and usable from the SQL editor for a bulk registration
CREATE OR REPLACE FUNCTION app.can_upload_media()
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT app.has_cap('editBom')
      OR app.is_admin()
      OR EXISTS (SELECT 1 FROM app_user u JOIN role r USING (role_id)
                  WHERE u.auth_uid = auth.uid() AND u.is_active AND r.code = 'GRAPHIC')
      OR session_user IN ('postgres','supabase_admin');
$$;
GRANT EXECUTE ON FUNCTION app.can_upload_media() TO authenticated;

CREATE OR REPLACE FUNCTION app.reserve_media(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code  TEXT := upper(btrim(COALESCE(p->>'jewel_code','')));
  v_style TEXT := upper(btrim(COALESCE(p->>'style_code','')));
  v_kind  media_kind := COALESCE(NULLIF(upper(btrim(COALESCE(p->>'kind',''))),''),'PHOTO')::media_kind;
  v_jc INT; v_st INT; v_ref TEXT; v_ext TEXT; v_key TEXT; v_rank INT;
BEGIN
  IF NOT app.can_upload_media() THEN
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

CREATE OR REPLACE FUNCTION app.detach_media(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_ref TEXT := btrim(COALESCE(p->>'media_ref','')); v_key TEXT;
BEGIN
  IF NOT app.can_upload_media() THEN
    RAISE EXCEPTION 'You do not have permission to remove media.';
  END IF;
  SELECT storage_key INTO v_key FROM media_asset WHERE media_ref = v_ref;
  IF NOT EXISTS (SELECT 1 FROM media_asset WHERE media_ref=v_ref) THEN
    RAISE EXCEPTION 'Media reference % not found.', v_ref;
  END IF;
  UPDATE media_asset SET is_archived = TRUE WHERE media_ref = v_ref;
  PERFORM app.log('DELETE','media_asset', v_ref, 'Removed from the piece; object left in R2');
  RETURN jsonb_build_object('ok',true,'media_ref',v_ref,'storage_key',v_key);
END $fn$;;
