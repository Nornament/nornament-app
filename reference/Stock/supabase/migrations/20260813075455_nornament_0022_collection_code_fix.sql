-- collection.code is NOT NULL; a new collection needs one generated from its name
CREATE OR REPLACE FUNCTION app.resolve_collection(p TEXT)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v INT; v_code TEXT;
BEGIN
  IF COALESCE(btrim(p),'') = '' THEN RETURN NULL; END IF;
  SELECT collection_id INTO v FROM collection WHERE upper(name) = upper(btrim(p));
  IF v IS NOT NULL THEN RETURN v; END IF;
  v_code := upper(left(regexp_replace(btrim(p),'[^A-Za-z0-9]','','g'), 12));
  IF v_code = '' THEN v_code := 'COL'; END IF;
  WHILE EXISTS (SELECT 1 FROM collection WHERE upper(code) = v_code) LOOP
    v_code := left(v_code, 10) || floor(random()*90+10)::text;
  END LOOP;
  INSERT INTO collection (code, name) VALUES (v_code, btrim(p)) RETURNING collection_id INTO v;
  RETURN v;
END $fn$;;
