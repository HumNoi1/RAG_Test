# Supabase Notes

This folder contains the lean `Supabase` schema for the grading workflow discussed in `AGENTS.md`.

## What This Schema Assumes
- Teachers upload both course materials and student submissions.
- Students do not upload files in v1.
- One submission per student per assignment.
- LLM grades are proposals only; student-visible results come from `submission_final_results` after teacher approval.
- Students should read from `public.student_results`, not from internal proposal tables.
- New signups default to `student`; promote teacher accounts explicitly with SQL or an admin workflow.

## Storage Layout
- Bucket `knowledge-files`: path should start with `<course_id>/...`
- Bucket `submission-files`: path should start with `<assignment_id>/...`

The storage RLS policies expect those first path segments so they can authorize access with `storage.foldername(name))[1]`.

## Suggested Flow
1. Next.js authenticates users with Supabase Auth.
2. Teacher uploads file to Supabase Storage.
3. Next.js inserts/updates `knowledge_documents` or `submissions`.
4. Next.js or a worker extracts text, then calls this Python backend.
5. Python ingests course materials into Qdrant with metadata like `course_id`, `assignment_id`, and `source_kind`.
6. Python grades submissions and returns a proposal payload.
7. Next.js stores the proposal in `submission_grade_proposals` and sets submission status to `pending_approval`.
8. Teacher approves or overrides.
9. Next.js writes the student-visible record to `submission_final_results` with denormalized course/assignment fields and updates submission status to `approved` or `overridden`.

## Backend Metadata Contract
When ingesting course materials into Qdrant, use payload metadata that matches this schema, especially:
- `course_id`
- `assignment_id`
- `source_kind`
- `document_id`

When grading, pass matching `metadata_filters` to keep retrieval scoped to the right course or assignment.
