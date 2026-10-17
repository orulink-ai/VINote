-- API-only tables: verified account scope is enforced by VINote's API.
-- Apply AFTER the cloud API's init_db creates its tables.
-- No browser/mobile direct table grants or public attachment bucket.
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'workspace_notes', 'workspace_versions', 'workspace_operations',
    'workspace_evidence', 'workspace_version_evidence', 'workspace_generations',
    'workspace_generation_claims', 'workspace_attachments'
  ] LOOP
    IF to_regclass('public.' || table_name) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
      EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', table_name);
    END IF;
  END LOOP;
END $$;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('vinote-content', 'vinote-content', false, 5242880,
        ARRAY['image/png', 'image/jpeg', 'image/webp'])
ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = 5242880,
  allowed_mime_types = ARRAY['image/png', 'image/jpeg', 'image/webp'];
-- Do not add anonymous/authenticated storage policies. Server service credentials
-- upload/read; clients receive account-checked short-lived signed URLs only.
