
-- 0031b was rolled back as a whole when the view rebuild inside it failed,
-- taking this with it. Re-applied on its own.

CREATE OR REPLACE FUNCTION app.reserve_media(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code  TEXT := NULLIF(upper(btrim(COALESCE(p->>'jewel_code',''))),'');
  v_style TEXT := NULLIF(upper(btrim(COALESCE(p->>'style_code',''))),'');
  v_kind  media_kind := COALESCE(NULLIF(upper(btrim(COALESCE(p->>'kind',''))),''),'PHOTO')::media_kind;
  v_of    TEXT := NULLIF(btrim(COALESCE(p->>'derivative_of','')),'');
  v_dkind TEXT := NULLIF(btrim(COALESCE(p->>'derivative_kind','')),'');
  v_ofid  INT;
  v_owner TEXT; v_jc INT; v_st INT; v_ref TEXT; v_ext TEXT; v_key TEXT; v_rank INT;
BEGIN
  IF NOT app.can_upload_media() THEN
    RAISE EXCEPTION 'You do not have permission to upload media.';
  END IF;
  IF v_code IS NOT NULL THEN
    SELECT jewel_code_id INTO v_jc FROM jewel_code WHERE upper(jewel_code) = v_code;
    IF v_jc IS NULL THEN RAISE EXCEPTION 'Jewel code % not found.', v_code; END IF;
  ELSIF v_style IS NOT NULL THEN
    SELECT style_id INTO v_st FROM style WHERE upper(style_code) = v_style;
    IF v_st IS NULL THEN RAISE EXCEPTION 'Design % not found.', v_style; END IF;
  ELSE
    RAISE EXCEPTION 'A photograph needs a jewel code; a CAD file needs a design.';
  END IF;
  v_owner := COALESCE(v_code, v_style);

  IF v_of IS NOT NULL THEN
    SELECT media_id INTO v_ofid FROM media_asset WHERE media_ref = v_of;
    IF v_ofid IS NULL THEN
      RAISE EXCEPTION 'Cannot attach a copy to "%" - no such file.', v_of;
    END IF;
  END IF;

  v_ext := lower(regexp_replace(COALESCE(p->>'file_name',''), '^.*\.', ''));
  IF v_ext = '' OR length(v_ext) > 8 OR v_ext !~ '^[a-z0-9]+$' THEN v_ext := 'bin'; END IF;

  -- A generated copy shares its original's rank. It is the same photograph,
  -- so it must not push the next real photo's number along.
  IF v_ofid IS NOT NULL THEN
    SELECT rank_order INTO v_rank FROM media_asset WHERE media_id = v_ofid;
  ELSE
    SELECT COALESCE(max(rank_order),0)+1 INTO v_rank FROM media_asset
     WHERE (v_jc IS NOT NULL AND jewel_code_id = v_jc)
        OR (v_st IS NOT NULL AND style_id = v_st);
  END IF;

  INSERT INTO media_asset (jewel_code_id, style_id, kind, view_angle, rank_order,
                           file_name, mime_type, bytes, caption, uploaded_by,
                           storage_provider, derivative_of, derivative_kind)
  VALUES (v_jc, v_st, v_kind, NULLIF(btrim(COALESCE(p->>'view_angle','')),''), v_rank,
          NULLIF(btrim(COALESCE(p->>'file_name','')),''),
          NULLIF(btrim(COALESCE(p->>'mime_type','')),''),
          NULLIF(p->>'bytes','')::bigint,
          NULLIF(btrim(COALESCE(p->>'caption','')),''),
          app.current_user_id(), 'R2', v_ofid, v_dkind)
  RETURNING media_ref INTO v_ref;

  v_key := v_owner || '/' || v_owner || '__' || v_kind::text || '__r' || v_rank
           || '__' || v_ref || CASE WHEN v_ofid IS NOT NULL THEN '__view' ELSE '' END
           || '.' || v_ext;
  UPDATE media_asset SET storage_key = v_key WHERE media_ref = v_ref;
  PERFORM app.log('INSERT','media_asset', v_ref,
                  CASE WHEN v_ofid IS NOT NULL
                       THEN 'Viewable copy of '||v_of
                       ELSE 'Reserved '||v_kind::text||' for '||v_owner END);
  RETURN jsonb_build_object('ok',true,'media_ref',v_ref,'storage_key',v_key,
                            'kind',v_kind::text,'rank',v_rank,'owner',v_owner,
                            'derivative_of', v_of);
END $fn$;

REVOKE ALL ON FUNCTION app.reserve_media(jsonb) FROM anon, authenticated;
;
