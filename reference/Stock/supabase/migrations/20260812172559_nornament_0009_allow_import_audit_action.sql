-- 'IMPORT' is a real thing that happens to stock, so the audit log must be
-- able to name it. Without this the whole batch dies on the audit row.
ALTER TABLE app.activity_log DROP CONSTRAINT IF EXISTS activity_log_action_check;
ALTER TABLE app.activity_log ADD CONSTRAINT activity_log_action_check
  CHECK (action = ANY (ARRAY['INSERT','UPDATE','DELETE','VIEW_COST','EXPORT',
                             'LOGIN','MELT','REPAIR','IMPORT','SALE','REVERSAL']));;
