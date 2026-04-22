create extension if not exists pgcrypto;

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text unique,
  full_name text not null default '',
  role text not null check (role in ('teacher', 'student')),
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create table public.courses (
  id uuid primary key default gen_random_uuid(),
  code text not null,
  name text not null,
  term text,
  teacher_id uuid not null references public.profiles (id) on delete restrict,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create table public.course_students (
  course_id uuid not null references public.courses (id) on delete cascade,
  student_id uuid not null references public.profiles (id) on delete cascade,
  created_at timestamp with time zone not null default now(),
  primary key (course_id, student_id)
);

create table public.assignments (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses (id) on delete cascade,
  title text not null,
  description text not null default '',
  max_score numeric(10, 2) not null check (max_score > 0),
  status text not null default 'draft' check (status in ('draft', 'published', 'closed')),
  due_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create table public.assignment_rubrics (
  id uuid primary key default gen_random_uuid(),
  assignment_id uuid not null references public.assignments (id) on delete cascade,
  criterion_name text not null,
  description text not null default '',
  max_score numeric(10, 2) not null check (max_score > 0),
  sort_order integer not null default 0,
  created_at timestamp with time zone not null default now(),
  unique (assignment_id, sort_order)
);

create table public.knowledge_documents (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses (id) on delete cascade,
  assignment_id uuid references public.assignments (id) on delete cascade,
  source_kind text not null default 'course_material' check (source_kind = 'course_material'),
  title text not null,
  original_filename text not null,
  storage_path text not null unique,
  mime_type text,
  file_size_bytes bigint,
  extracted_text text,
  qdrant_collection text not null default 'rag_demo_bge_m3',
  ingest_status text not null default 'pending' check (ingest_status in ('pending', 'processing', 'ready', 'failed')),
  chunks_stored integer not null default 0 check (chunks_stored >= 0),
  ingest_error text,
  uploaded_by uuid not null references public.profiles (id) on delete restrict,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create table public.submissions (
  id uuid primary key default gen_random_uuid(),
  assignment_id uuid not null references public.assignments (id) on delete cascade,
  student_id uuid not null references public.profiles (id) on delete cascade,
  original_filename text not null,
  storage_path text not null unique,
  mime_type text,
  file_size_bytes bigint,
  extracted_text text,
  status text not null default 'uploaded' check (status in ('uploaded', 'text_ready', 'grading', 'pending_approval', 'approved', 'overridden', 'failed')),
  processing_error text,
  approved_by uuid references public.profiles (id) on delete restrict,
  approved_at timestamp with time zone,
  uploaded_by uuid not null references public.profiles (id) on delete restrict,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  unique (assignment_id, student_id),
  constraint submissions_approval_requires_actor
    check (
      status not in ('approved', 'overridden')
      or (approved_by is not null and approved_at is not null)
    )
);

create table public.submission_grade_proposals (
  submission_id uuid primary key references public.submissions (id) on delete cascade,
  proposed_total_score numeric(10, 2) not null check (proposed_total_score >= 0),
  proposed_student_reason text not null,
  proposed_internal_reason text not null,
  rubric_breakdown jsonb not null default '[]'::jsonb,
  retrieval_evidence jsonb not null default '[]'::jsonb,
  llm_model text,
  embedding_model text,
  prompt_version text,
  confidence numeric(5, 4) check (confidence is null or (confidence >= 0 and confidence <= 1)),
  teacher_override_note text,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint submission_grade_proposals_rubric_breakdown_is_array
    check (jsonb_typeof(rubric_breakdown) = 'array'),
  constraint submission_grade_proposals_retrieval_evidence_is_array
    check (jsonb_typeof(retrieval_evidence) = 'array')
);

create table public.submission_final_results (
  submission_id uuid primary key references public.submissions (id) on delete cascade,
  student_id uuid not null references public.profiles (id) on delete cascade,
  assignment_id uuid not null references public.assignments (id) on delete cascade,
  assignment_title text not null,
  course_id uuid not null references public.courses (id) on delete cascade,
  course_code text not null,
  course_name text not null,
  final_total_score numeric(10, 2) not null check (final_total_score >= 0),
  final_reason text not null,
  published_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create index idx_course_students_student_id
  on public.course_students (student_id);

create index idx_assignments_course_id
  on public.assignments (course_id);

create index idx_assignment_rubrics_assignment_id_sort_order
  on public.assignment_rubrics (assignment_id, sort_order);

create index idx_knowledge_documents_course_id
  on public.knowledge_documents (course_id);

create index idx_knowledge_documents_assignment_id
  on public.knowledge_documents (assignment_id);

create index idx_knowledge_documents_ingest_status
  on public.knowledge_documents (ingest_status);

create index idx_submissions_student_id
  on public.submissions (student_id);

create index idx_submissions_status
  on public.submissions (status);

create or replace function public.try_uuid(value text)
returns uuid
language plpgsql
immutable
set search_path = ''
as $$
begin
  return value::uuid;
exception
  when others then
    return null;
end;
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name, role)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', ''),
    'student'
  );

  return new;
end;
$$;

create or replace function public.current_role()
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select p.role
  from public.profiles p
  where p.id = auth.uid()
$$;

create or replace function public.is_teacher()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(public.current_role() = 'teacher', false)
$$;

create or replace function public.owns_course(target_course_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.courses c
    where c.id = target_course_id
      and c.teacher_id = auth.uid()
  )
$$;

create or replace function public.enrolled_in_course(target_course_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.course_students cs
    where cs.course_id = target_course_id
      and cs.student_id = auth.uid()
  )
$$;

create or replace function public.owns_assignment(target_assignment_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.assignments a
    join public.courses c on c.id = a.course_id
    where a.id = target_assignment_id
      and c.teacher_id = auth.uid()
  )
$$;

create or replace function public.owns_submission(target_submission_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.submissions s
    join public.assignments a on a.id = s.assignment_id
    join public.courses c on c.id = a.course_id
    where s.id = target_submission_id
      and c.teacher_id = auth.uid()
  )
$$;

create or replace function public.is_submission_owner(target_submission_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.submissions s
    where s.id = target_submission_id
      and s.student_id = auth.uid()
  )
$$;

create or replace function public.can_read_profile(target_profile_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select (
    auth.uid() = target_profile_id
    or exists (
      select 1
      from public.course_students cs
      join public.courses c on c.id = cs.course_id
      where c.teacher_id = auth.uid()
        and cs.student_id = target_profile_id
    )
    or exists (
      select 1
      from public.course_students cs
      join public.courses c on c.id = cs.course_id
      where cs.student_id = auth.uid()
        and c.teacher_id = target_profile_id
    )
  )
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
  before update on public.profiles
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_courses_updated_at on public.courses;
create trigger set_courses_updated_at
  before update on public.courses
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_assignments_updated_at on public.assignments;
create trigger set_assignments_updated_at
  before update on public.assignments
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_knowledge_documents_updated_at on public.knowledge_documents;
create trigger set_knowledge_documents_updated_at
  before update on public.knowledge_documents
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_submissions_updated_at on public.submissions;
create trigger set_submissions_updated_at
  before update on public.submissions
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_submission_grade_proposals_updated_at on public.submission_grade_proposals;
create trigger set_submission_grade_proposals_updated_at
  before update on public.submission_grade_proposals
  for each row execute procedure public.set_updated_at();

drop trigger if exists set_submission_final_results_updated_at on public.submission_final_results;
create trigger set_submission_final_results_updated_at
  before update on public.submission_final_results
  for each row execute procedure public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.courses enable row level security;
alter table public.course_students enable row level security;
alter table public.assignments enable row level security;
alter table public.assignment_rubrics enable row level security;
alter table public.knowledge_documents enable row level security;
alter table public.submissions enable row level security;
alter table public.submission_grade_proposals enable row level security;
alter table public.submission_final_results enable row level security;

create policy "profiles_select_related"
  on public.profiles for select
  to authenticated
  using (public.can_read_profile(id));

create policy "profiles_insert_own"
  on public.profiles for insert
  to authenticated
  with check (auth.uid() = id);

create policy "profiles_update_own"
  on public.profiles for update
  to authenticated
  using (auth.uid() = id)
  with check (auth.uid() = id);

create policy "courses_teacher_manage"
  on public.courses for all
  to authenticated
  using (public.is_teacher() and public.owns_course(id))
  with check (public.is_teacher() and teacher_id = auth.uid());

create policy "courses_student_select"
  on public.courses for select
  to authenticated
  using (public.enrolled_in_course(id));

create policy "course_students_teacher_manage"
  on public.course_students for all
  to authenticated
  using (public.is_teacher() and public.owns_course(course_id))
  with check (public.is_teacher() and public.owns_course(course_id));

create policy "course_students_student_select_own"
  on public.course_students for select
  to authenticated
  using (student_id = auth.uid());

create policy "assignments_teacher_manage"
  on public.assignments for all
  to authenticated
  using (public.is_teacher() and public.owns_course(course_id))
  with check (public.is_teacher() and public.owns_course(course_id));

create policy "assignments_student_select"
  on public.assignments for select
  to authenticated
  using (public.enrolled_in_course(course_id));

create policy "assignment_rubrics_teacher_manage"
  on public.assignment_rubrics for all
  to authenticated
  using (public.is_teacher() and public.owns_assignment(assignment_id))
  with check (public.is_teacher() and public.owns_assignment(assignment_id));

create policy "knowledge_documents_teacher_manage"
  on public.knowledge_documents for all
  to authenticated
  using (public.is_teacher() and public.owns_course(course_id))
  with check (public.is_teacher() and public.owns_course(course_id));

create policy "submissions_teacher_manage"
  on public.submissions for all
  to authenticated
  using (public.is_teacher() and public.owns_assignment(assignment_id))
  with check (public.is_teacher() and public.owns_assignment(assignment_id));

create policy "submission_grade_proposals_teacher_manage"
  on public.submission_grade_proposals for all
  to authenticated
  using (public.is_teacher() and public.owns_submission(submission_id))
  with check (public.is_teacher() and public.owns_submission(submission_id));

create policy "submission_final_results_teacher_manage"
  on public.submission_final_results for all
  to authenticated
  using (public.is_teacher() and public.owns_submission(submission_id))
  with check (public.is_teacher() and public.owns_submission(submission_id));

create policy "submission_final_results_student_select_own"
  on public.submission_final_results for select
  to authenticated
  using (student_id = auth.uid());

insert into storage.buckets (id, name, public)
values
  ('knowledge-files', 'knowledge-files', false),
  ('submission-files', 'submission-files', false)
on conflict (id) do nothing;

create policy "knowledge_files_select_teachers"
  on storage.objects for select
  to authenticated
  using (
    bucket_id = 'knowledge-files'
    and public.is_teacher()
    and public.owns_course(public.try_uuid((storage.foldername(name))[1]))
  );

create policy "knowledge_files_insert_teachers"
  on storage.objects for insert
  to authenticated
  with check (
    bucket_id = 'knowledge-files'
    and public.is_teacher()
    and public.owns_course(public.try_uuid((storage.foldername(name))[1]))
  );

create policy "knowledge_files_update_teachers"
  on storage.objects for update
  to authenticated
  using (
    bucket_id = 'knowledge-files'
    and public.is_teacher()
    and public.owns_course(public.try_uuid((storage.foldername(name))[1]))
  )
  with check (
    bucket_id = 'knowledge-files'
    and public.is_teacher()
    and public.owns_course(public.try_uuid((storage.foldername(name))[1]))
  );

create policy "knowledge_files_delete_teachers"
  on storage.objects for delete
  to authenticated
  using (
    bucket_id = 'knowledge-files'
    and public.is_teacher()
    and public.owns_course(public.try_uuid((storage.foldername(name))[1]))
  );

create policy "submission_files_select_teachers"
  on storage.objects for select
  to authenticated
  using (
    bucket_id = 'submission-files'
    and public.is_teacher()
    and public.owns_assignment(public.try_uuid((storage.foldername(name))[1]))
  );

create policy "submission_files_insert_teachers"
  on storage.objects for insert
  to authenticated
  with check (
    bucket_id = 'submission-files'
    and public.is_teacher()
    and public.owns_assignment(public.try_uuid((storage.foldername(name))[1]))
  );

create policy "submission_files_update_teachers"
  on storage.objects for update
  to authenticated
  using (
    bucket_id = 'submission-files'
    and public.is_teacher()
    and public.owns_assignment(public.try_uuid((storage.foldername(name))[1]))
  )
  with check (
    bucket_id = 'submission-files'
    and public.is_teacher()
    and public.owns_assignment(public.try_uuid((storage.foldername(name))[1]))
  );

create policy "submission_files_delete_teachers"
  on storage.objects for delete
  to authenticated
  using (
    bucket_id = 'submission-files'
    and public.is_teacher()
    and public.owns_assignment(public.try_uuid((storage.foldername(name))[1]))
  );

create or replace view public.student_results
with (security_invoker = true)
as
select
  sfr.submission_id,
  sfr.assignment_id,
  sfr.assignment_title,
  sfr.course_id,
  sfr.course_code,
  sfr.course_name,
  sfr.final_total_score,
  sfr.final_reason,
  sfr.published_at
from public.submission_final_results sfr
where sfr.student_id = auth.uid();

grant select on public.student_results to authenticated;
