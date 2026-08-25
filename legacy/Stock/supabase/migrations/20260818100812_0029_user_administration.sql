
-- ─────────────────────────────────────────────────────────────────────────
-- 0029  User administration
--
-- A login and a user are two different things and always were. auth.users
-- holds the credential; app.app_user holds the role, the home location and
-- the location rights. Nothing linked them, so a login created in the
-- Supabase dashboard authenticated fine and then arrived as nobody.
--
-- This makes the pairing visible and repairable from the app.
-- Additive only: no existing table is altered.
-- ─────────────────────────────────────────────────────────────────────────

-- ── who the users actually are ────────────────────────────────────────────
CREATE OR REPLACE VIEW api.app_users
WITH (security_invoker = false) AS
SELECT u.user_id,
       u.username,
       u.full_name,
       u.email,
       r.code                AS role_code,
       r.name                AS role_name,
       COALESCE(hl.code,'')  AS home_location,
       u.home_location_id IS NULL          AS all_locations,
       COALESCE((SELECT array_agg(l2.code ORDER BY l2.code)
                   FROM app.user_location ul
                   JOIN app.location l2 USING (location_id)
                  WHERE ul.user_id = u.user_id), '{}'::text[]) AS extra_locations,
       u.is_active,
       u.auth_uid IS NOT NULL AS has_login,
       u.last_login_at,
       u.created_at
  FROM app.app_user u
  JOIN app.role r ON r.role_id = u.role_id
  LEFT JOIN app.location hl ON hl.location_id = u.home_location_id
 WHERE app.is_admin();

-- ── logins with nobody behind them ────────────────────────────────────────
-- The whole point of this view is that an orphan is loud rather than silent.
CREATE OR REPLACE VIEW api.pending_logins
WITH (security_invoker = false) AS
SELECT au.email,
       au.created_at,
       au.email_confirmed_at IS NOT NULL AS confirmed
  FROM auth.users au
 WHERE app.is_admin()
   AND NOT EXISTS (SELECT 1 FROM app.app_user a WHERE a.auth_uid = au.id)
   AND au.email IS NOT NULL;

-- ── create or update one user ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION app.upsert_app_user(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public, auth AS $fn$
DECLARE
  v_username TEXT := lower(btrim(p->>'username'));
  v_email    TEXT := lower(nullif(btrim(p->>'email'),''));
  v_full     TEXT := btrim(coalesce(p->>'full_name',''));
  v_role     TEXT := upper(btrim(coalesce(p->>'role_code','')));
  v_home     TEXT := nullif(btrim(coalesce(p->>'home_location','')),'');
  v_all      BOOLEAN := coalesce((p->>'all_locations')::boolean, false);
  v_role_id  INT;
  v_home_id  INT;
  v_auth     UUID;
  v_id       INT;
  v_new      BOOLEAN := false;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can add or change users.';
  END IF;

  IF v_username IS NULL OR length(v_username) < 3 THEN
    RAISE EXCEPTION 'Username must be at least 3 characters.';
  END IF;
  IF v_username !~ '^[a-z0-9._-]+$' THEN
    RAISE EXCEPTION 'Username may use letters, digits, dot, dash and underscore only — no spaces.';
  END IF;
  IF length(v_full) < 3 THEN
    RAISE EXCEPTION 'Enter the person''s full name.';
  END IF;

  SELECT role_id INTO v_role_id FROM app.role WHERE code = v_role;
  IF v_role_id IS NULL THEN
    RAISE EXCEPTION 'Role "%" is not one of %', v_role,
      (SELECT string_agg(code, ', ' ORDER BY role_id) FROM app.role);
  END IF;

  -- A blank home location means every location. Admins always see everything,
  -- so the two are the same thing for them, but we store it explicitly.
  IF NOT v_all AND v_home IS NOT NULL THEN
    SELECT location_id INTO v_home_id FROM app.location WHERE code = upper(v_home);
    IF v_home_id IS NULL THEN
      RAISE EXCEPTION 'Location "%" is not one of %', v_home,
        (SELECT string_agg(code, ', ' ORDER BY code) FROM app.location WHERE is_active);
    END IF;
  END IF;

  -- Link the credential. Matching on email is the only handle we have, and it
  -- is the same string the person types to sign in.
  IF v_email IS NOT NULL THEN
    SELECT id INTO v_auth FROM auth.users WHERE lower(email) = v_email LIMIT 1;
  END IF;

  SELECT user_id INTO v_id FROM app.app_user WHERE username = v_username;

  IF v_id IS NULL THEN
    v_new := true;
    INSERT INTO app.app_user (username, full_name, email, role_id,
                              home_location_id, is_active, auth_uid,
                              must_change_password)
    VALUES (v_username, v_full, v_email, v_role_id, v_home_id, true, v_auth, false)
    RETURNING user_id INTO v_id;
  ELSE
    UPDATE app.app_user
       SET full_name        = v_full,
           email            = coalesce(v_email, email),
           role_id          = v_role_id,
           home_location_id = v_home_id,
           auth_uid         = coalesce(v_auth, auth_uid)
     WHERE user_id = v_id;
  END IF;

  PERFORM app.log_activity('USER_' || CASE WHEN v_new THEN 'ADDED' ELSE 'UPDATED' END,
                           v_username, v_full || ' · ' || v_role);

  RETURN jsonb_build_object(
    'ok', true, 'user_id', v_id, 'username', v_username, 'created', v_new,
    'linked_login', v_auth IS NOT NULL,
    'note', CASE WHEN v_auth IS NULL
                 THEN 'Saved, but there is no login for ' || coalesce(v_email,'(no email)') ||
                      ' yet — this person cannot sign in until one is created.'
                 ELSE 'Saved and linked to their login.' END);
END $fn$;

-- ── switch someone off without deleting their history ─────────────────────
CREATE OR REPLACE FUNCTION app.set_user_active(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_username TEXT := lower(btrim(p->>'username'));
  v_active   BOOLEAN := coalesce((p->>'is_active')::boolean, true);
  v_id       INT;
  v_role     TEXT;
  v_admins   INT;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can enable or disable a user.';
  END IF;

  SELECT u.user_id, r.code INTO v_id, v_role
    FROM app.app_user u JOIN app.role r ON r.role_id = u.role_id
   WHERE u.username = v_username;
  IF v_id IS NULL THEN
    RAISE EXCEPTION 'No user called "%".', v_username;
  END IF;

  -- Locking yourself out of your own stock system is not a recoverable
  -- mistake from inside the app, so it is refused rather than confirmed.
  IF NOT v_active AND v_role = 'ADMIN' THEN
    SELECT count(*) INTO v_admins
      FROM app.app_user u JOIN app.role r ON r.role_id = u.role_id
     WHERE r.code = 'ADMIN' AND u.is_active AND u.user_id <> v_id;
    IF v_admins = 0 THEN
      RAISE EXCEPTION 'This is the last active admin. Make someone else an admin first.';
    END IF;
  END IF;

  UPDATE app.app_user SET is_active = v_active WHERE user_id = v_id;
  PERFORM app.log_activity(CASE WHEN v_active THEN 'USER_ENABLED' ELSE 'USER_DISABLED' END,
                           v_username, null);
  RETURN jsonb_build_object('ok', true, 'username', v_username, 'is_active', v_active);
END $fn$;

-- ── api wrappers ──────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION api.upsert_app_user(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.upsert_app_user(p) $$;

CREATE OR REPLACE FUNCTION api.set_user_active(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.set_user_active(p) $$;

GRANT SELECT ON api.app_users, api.pending_logins TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.upsert_app_user(jsonb) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.set_user_active(jsonb) TO anon, authenticated;
REVOKE ALL ON FUNCTION app.upsert_app_user(jsonb) FROM anon, authenticated;
REVOKE ALL ON FUNCTION app.set_user_active(jsonb)  FROM anon, authenticated;
;
