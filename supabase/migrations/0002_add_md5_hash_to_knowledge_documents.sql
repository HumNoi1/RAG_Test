-- Add md5_hash to knowledge_documents for deduplication
alter table public.knowledge_documents
  add column if not exists md5_hash text;

create index if not exists idx_knowledge_documents_md5_course
  on public.knowledge_documents (md5_hash, course_id)
  where md5_hash is not null;
