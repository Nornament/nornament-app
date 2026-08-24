
-- Fix auth_rls_initplan: wrap auth.role() in (select ...) so it's evaluated once per query, not per row
-- This is the main cause of excessive Disk IO reads on the free tier

DO $$
DECLARE
  t text;
  tables text[] := ARRAY['customers','orders','repairs','settings','rm_parties','rm_lots','rm_txns'];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    -- Drop and recreate each auth_only policy with the optimized form
    EXECUTE format('DROP POLICY IF EXISTS auth_only ON public.%I', t);
    EXECUTE format(
      'CREATE POLICY auth_only ON public.%I FOR ALL USING ((select auth.role()) = ''authenticated'')',
      t
    );
  END LOOP;
END $$;

-- Add missing index on rm_txns.issue_txn_id (flagged as unindexed FK)
CREATE INDEX IF NOT EXISTS idx_rm_txns_issue_txn_id ON public.rm_txns(issue_txn_id);
;
