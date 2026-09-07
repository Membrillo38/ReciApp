-- Remove provider credential details from errors written by old deployments.
-- New pipeline failures are normalized before they reach extract_jobs.error.
update public.extract_jobs
   set error = 'Extraction failed in a previous deployment. Retry the import.'
 where status = 'failed'
   and (
     error ilike '%invalid_api_key%'
     or error ilike '%incorrect api key provided%'
   );
