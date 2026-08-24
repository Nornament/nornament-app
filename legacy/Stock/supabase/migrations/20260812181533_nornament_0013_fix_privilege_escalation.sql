-- ============================================================
-- SECURITY FIX.
--
-- 0010 tested `current_user IN ('postgres', ...)` to let the SQL
-- editor run the initial import. Inside a SECURITY DEFINER
-- function current_user is the function OWNER, not the caller -
-- so it was 'postgres' for everybody, and the permission check
-- passed for every logged-in user. A Sales login could create
-- and edit stock over the REST API.
--
-- session_user is not rewritten by SECURITY DEFINER. It is
-- 'authenticator' for anything arriving through the API and
-- 'postgres' only in the SQL editor, which is the distinction
-- that was actually intended.
-- ============================================================
CREATE OR REPLACE FUNCTION app.is_privileged()
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT app.has_cap('editBom')
      OR session_user IN ('postgres','supabase_admin');
$$;

DROP FUNCTION IF EXISTS api.whoami_probe();;
