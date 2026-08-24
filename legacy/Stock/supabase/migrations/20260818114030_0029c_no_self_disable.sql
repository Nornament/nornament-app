
-- 0029c  An admin who disables their own account loses admin in the same
-- statement, so they cannot undo it — is_admin() checks is_active. With two
-- admins that is a phone call; with one it is a locked door. Refuse it.

CREATE OR REPLACE FUNCTION app.set_user_active(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_username TEXT := lower(btrim(p->>'username'));
  v_active   BOOLEAN := coalesce((p->>'is_active')::boolean, true);
  v_id       INT;
  v_role     TEXT;
  v_admins   INT;
  v_me       INT := app.current_user_id();
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

  IF NOT v_active AND v_id = v_me THEN
    RAISE EXCEPTION 'You cannot switch off your own account — you would lose the access needed to switch it back on. Ask the other admin.';
  END IF;

  IF NOT v_active AND v_role = 'ADMIN' THEN
    SELECT count(*) INTO v_admins
      FROM app.app_user u JOIN app.role r ON r.role_id = u.role_id
     WHERE r.code = 'ADMIN' AND u.is_active AND u.user_id <> v_id;
    IF v_admins = 0 THEN
      RAISE EXCEPTION 'This is the last active admin. Make someone else an admin first.';
    END IF;
  END IF;

  UPDATE app.app_user SET is_active = v_active WHERE user_id = v_id;
  PERFORM app.log('UPDATE', 'app_user', v_username,
                  CASE WHEN v_active THEN 'enabled' ELSE 'disabled' END);
  RETURN jsonb_build_object('ok', true, 'username', v_username, 'is_active', v_active);
END $fn$;

REVOKE ALL ON FUNCTION app.set_user_active(jsonb) FROM anon, authenticated;

-- Same reasoning for the role: demoting yourself out of ADMIN is a one-way
-- door taken by accident from a dropdown.
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
  v_old_role TEXT;
  v_new      BOOLEAN := false;
  v_me       INT := app.current_user_id();
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

  IF NOT v_all AND v_home IS NOT NULL THEN
    SELECT location_id INTO v_home_id FROM app.location WHERE code = upper(v_home);
    IF v_home_id IS NULL THEN
      RAISE EXCEPTION 'Location "%" is not one of %', v_home,
        (SELECT string_agg(code, ', ' ORDER BY code) FROM app.location WHERE is_active);
    END IF;
  END IF;

  IF v_email IS NOT NULL THEN
    SELECT id INTO v_auth FROM auth.users WHERE lower(email) = v_email LIMIT 1;
  END IF;

  SELECT u.user_id, r.code INTO v_id, v_old_role
    FROM app.app_user u JOIN app.role r ON r.role_id = u.role_id
   WHERE u.username = v_username;

  IF v_id IS NOT NULL AND v_id = v_me AND v_old_role = 'ADMIN' AND v_role <> 'ADMIN' THEN
    RAISE EXCEPTION 'You cannot take Admin away from yourself — you would lose the access needed to put it back. Ask the other admin.';
  END IF;

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

  PERFORM app.log(CASE WHEN v_new THEN 'INSERT' ELSE 'UPDATE' END,
                  'app_user', v_username, v_full || ' · ' || v_role);

  RETURN jsonb_build_object(
    'ok', true, 'user_id', v_id, 'username', v_username, 'created', v_new,
    'linked_login', v_auth IS NOT NULL,
    'note', CASE WHEN v_auth IS NULL
                 THEN 'Saved, but there is no login for ' || coalesce(v_email,'(no email)') ||
                      ' yet — this person cannot sign in until one is created.'
                 ELSE 'Saved and linked to their login.' END);
END $fn$;

REVOKE ALL ON FUNCTION app.upsert_app_user(jsonb) FROM anon, authenticated;
;
