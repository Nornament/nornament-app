-- Private buckets. Nothing is public-read: a photograph of a piece worth
-- lakhs should not be fetchable by anyone who guesses a URL.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
  ('originals','originals', FALSE, 524288000, NULL),
  ('derived','derived',     FALSE,  10485760, ARRAY['image/webp','image/jpeg','image/png']),
  ('brand','brand',         FALSE,   2097152, ARRAY['image/png','image/svg+xml','image/webp','image/jpeg'])
ON CONFLICT (id) DO NOTHING;

CREATE POLICY "nornament originals read"
  ON storage.objects FOR SELECT TO authenticated
  USING (bucket_id = 'originals' AND app.has_cap('materials'));
CREATE POLICY "nornament derived read"
  ON storage.objects FOR SELECT TO authenticated
  USING (bucket_id = 'derived');
CREATE POLICY "nornament media upload"
  ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (bucket_id IN ('originals','derived')
    AND EXISTS (SELECT 1 FROM app.app_user u JOIN app.role r USING (role_id)
                WHERE u.auth_uid = auth.uid() AND u.is_active
                  AND (r.is_system OR r.code = 'GRAPHIC')));
CREATE POLICY "nornament brand admin"
  ON storage.objects FOR ALL TO authenticated
  USING (bucket_id='brand' AND app.is_admin())
  WITH CHECK (bucket_id='brand' AND app.is_admin());

-- media_ref: the join key that survives renaming and expiring URLs.
-- Issued from ONE sequence, because a hash-derived id collides and a
-- collision attaches one piece's photographs to another.
CREATE SEQUENCE IF NOT EXISTS app.media_ref_seq;
ALTER TABLE app.media_asset
  ADD COLUMN IF NOT EXISTS media_ref TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS file_name TEXT,
  ADD COLUMN IF NOT EXISTS sha256 TEXT,
  ADD COLUMN IF NOT EXISTS bytes BIGINT,
  ADD COLUMN IF NOT EXISTS storage_key TEXT;
ALTER TABLE app.media_asset ALTER COLUMN storage_url DROP NOT NULL;
ALTER TABLE app.media_asset
  ALTER COLUMN media_ref SET DEFAULT 'M'||lpad(nextval('app.media_ref_seq')::text,6,'0');

CREATE OR REPLACE VIEW api.media AS
SELECT m.media_ref, jc.jewel_code, m.kind, m.view_angle, m.rank_order,
       m.file_name, m.sha256, m.bytes, m.storage_key, m.thumb_url,
       u.username AS uploaded_by, m.uploaded_at
FROM app.media_asset m
LEFT JOIN app.jewel_code jc ON jc.jewel_code_id = m.jewel_code_id
LEFT JOIN app.app_user u    ON u.user_id = m.uploaded_by
WHERE jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations());
GRANT SELECT ON api.media TO authenticated;;
