
-- CREATE OR REPLACE cannot insert columns in the middle of a view, so the
-- view is dropped and rebuilt. Nothing depends on it but the front end.
DROP VIEW IF EXISTS api.media;

CREATE VIEW api.media
WITH (security_invoker = false) AS
SELECT m.media_ref,
       jc.jewel_code,
       s.style_code,
       m.kind::text AS kind,
       m.view_angle,
       m.rank_order,
       m.file_name,
       m.mime_type,
       m.bytes,
       m.sha256,
       m.caption,
       m.storage_provider,
       m.storage_key,
       m.width_px,
       m.height_px,
       m.is_catalogue_default,
       u.username AS uploaded_by,
       m.uploaded_at,
       -- the browser-viewable copy of this file, when the original is a
       -- format no browser can decode
       (SELECT d.media_ref  FROM app.media_asset d
         WHERE d.derivative_of = m.media_id AND NOT d.is_archived
         ORDER BY d.media_id LIMIT 1) AS view_ref,
       (SELECT d.storage_key FROM app.media_asset d
         WHERE d.derivative_of = m.media_id AND NOT d.is_archived
         ORDER BY d.media_id LIMIT 1) AS view_key,
       o.media_ref AS derivative_of,
       m.derivative_kind
  FROM app.media_asset m
  LEFT JOIN app.jewel_code  jc ON jc.jewel_code_id = m.jewel_code_id
  LEFT JOIN app.style       s  ON s.style_id       = m.style_id
  LEFT JOIN app.media_asset o  ON o.media_id       = m.derivative_of
  LEFT JOIN app.app_user    u  ON u.user_id        = m.uploaded_by
 WHERE NOT m.is_archived
   AND (jc.jewel_code_id IS NULL OR jc.location_id IS NULL
        OR jc.location_id IN (SELECT app.visible_locations()));

GRANT SELECT ON api.media TO anon, authenticated;
;
