
-- ─────────────────────────────────────────────────────────────────────────
-- 0031  A display picture, and a place to keep web-viewable copies
--
-- Two problems from one root. An iPhone shoots HEIC and a studio shoots TIFF;
-- no desktop browser can decode either, so "view" silently became "download"
-- and the photo could never be a thumbnail. The app will now upload a JPEG
-- copy next to the original. That copy is not a second photograph and must
-- not appear in the file list as one, hence derivative_of.
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE app.media_asset
  ADD COLUMN IF NOT EXISTS derivative_of INT
    REFERENCES app.media_asset(media_id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS derivative_kind TEXT;

COMMENT ON COLUMN app.media_asset.derivative_of IS
  'This row is a generated copy of another asset (a JPEG made from a HEIC or '
  'TIFF), not a photograph in its own right. Cascades: deleting the original '
  'removes the copy, because a copy of nothing is litter.';

CREATE INDEX IF NOT EXISTS media_asset_derivative_idx
  ON app.media_asset(derivative_of) WHERE derivative_of IS NOT NULL;

-- One display picture per piece. A partial unique index says that in the
-- schema rather than trusting every future writer to remember it.
CREATE UNIQUE INDEX IF NOT EXISTS media_one_default_per_piece
  ON app.media_asset(jewel_code_id)
  WHERE is_catalogue_default AND jewel_code_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS media_one_default_per_style
  ON app.media_asset(style_id)
  WHERE is_catalogue_default AND style_id IS NOT NULL;

CREATE OR REPLACE FUNCTION app.set_display_photo(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_ref   TEXT := btrim(coalesce(p->>'media_ref',''));
  v_id    INT; v_jc INT; v_st INT; v_kind TEXT; v_mime TEXT; v_deriv INT;
BEGIN
  IF NOT (app.is_privileged() OR app.can_upload_media()) THEN
    RAISE EXCEPTION 'You do not have permission to change the display picture.';
  END IF;

  SELECT media_id, jewel_code_id, style_id, kind::text, mime_type, derivative_of
    INTO v_id, v_jc, v_st, v_kind, v_mime, v_deriv
    FROM app.media_asset WHERE media_ref = v_ref AND NOT is_archived;
  IF v_id IS NULL THEN RAISE EXCEPTION 'No file called "%".', v_ref; END IF;

  -- A CAD file or a job card scan is not a display picture. Say so rather
  -- than accepting it and rendering a broken image everywhere.
  IF v_kind NOT IN ('PHOTO','RENDER','GRAPH') THEN
    RAISE EXCEPTION 'A % is not something that can be a display picture. Use a photograph or a render.',
      lower(replace(v_kind,'_',' '));
  END IF;

  -- If the chosen file is one a browser cannot draw, prefer its JPEG copy.
  IF v_mime IN ('image/heic','image/heif','image/tiff','image/tif') THEN
    DECLARE v_alt INT;
    BEGIN
      SELECT media_id INTO v_alt FROM app.media_asset
       WHERE derivative_of = v_id AND NOT is_archived
       ORDER BY media_id LIMIT 1;
      IF v_alt IS NULL THEN
        RAISE EXCEPTION 'That file is a %, which browsers cannot display, and it has no JPEG copy yet. Re-upload it so a copy is made.',
          upper(split_part(v_mime,'/',2));
      END IF;
      v_id := v_alt;
    END;
  END IF;

  IF v_jc IS NOT NULL THEN
    UPDATE app.media_asset SET is_catalogue_default = false
      WHERE jewel_code_id = v_jc AND is_catalogue_default AND media_id <> v_id;
    UPDATE app.media_asset SET is_catalogue_default = true WHERE media_id = v_id;
  ELSIF v_st IS NOT NULL THEN
    UPDATE app.media_asset SET is_catalogue_default = false
      WHERE style_id = v_st AND is_catalogue_default AND media_id <> v_id;
    UPDATE app.media_asset SET is_catalogue_default = true WHERE media_id = v_id;
  ELSE
    RAISE EXCEPTION 'That file is not attached to a piece or a design.';
  END IF;

  PERFORM app.log('UPDATE','media_asset', v_ref, 'set as display picture');
  RETURN jsonb_build_object('ok', true, 'media_ref', v_ref,
    'used', (SELECT media_ref FROM app.media_asset WHERE media_id = v_id));
END $fn$;

CREATE OR REPLACE FUNCTION app.clear_display_photo(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_code TEXT := upper(btrim(coalesce(p->>'jewel_code','')));
        v_jc INT;
BEGIN
  IF NOT (app.is_privileged() OR app.can_upload_media()) THEN
    RAISE EXCEPTION 'You do not have permission to change the display picture.';
  END IF;
  SELECT jewel_code_id INTO v_jc FROM app.jewel_code WHERE upper(jewel_code) = v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'No piece called "%".', v_code; END IF;
  UPDATE app.media_asset SET is_catalogue_default = false
   WHERE jewel_code_id = v_jc AND is_catalogue_default;
  PERFORM app.log('UPDATE','media_asset', v_code, 'display picture cleared');
  RETURN jsonb_build_object('ok', true, 'jewel_code', v_code);
END $fn$;

CREATE OR REPLACE FUNCTION api.set_display_photo(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.set_display_photo(p) $$;
CREATE OR REPLACE FUNCTION api.clear_display_photo(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.clear_display_photo(p) $$;

GRANT EXECUTE ON FUNCTION api.set_display_photo(jsonb), api.clear_display_photo(jsonb)
  TO anon, authenticated;
REVOKE ALL ON FUNCTION app.set_display_photo(jsonb), app.clear_display_photo(jsonb)
  FROM anon, authenticated;
;
