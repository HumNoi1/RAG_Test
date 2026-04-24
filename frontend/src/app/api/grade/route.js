import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";

const RAG_API = process.env.RAG_API_URL ?? "http://localhost:8000";

export async function POST(request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user)
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { submissionId } = await request.json();

  // 1. Fetch submission + assignment + rubric in one join
  const { data: submission, error: fetchError } = await supabase
    .from("submissions")
    .select(
      `
      id,
      extracted_text,
      student_id,
      assignments (
        id,
        title,
        description,
        course_id,
        assignment_rubrics ( criterion_name, description, max_score, sort_order )
      )
    `,
    )
    .eq("id", submissionId)
    .single();

  if (fetchError || !submission) {
    return NextResponse.json(
      { error: "Submission not found" },
      { status: 404 },
    );
  }

  if (!submission.extracted_text) {
    return NextResponse.json(
      { error: "ยังไม่มี extracted text — กรุณาอัปโหลดไฟล์ก่อน" },
      { status: 400 },
    );
  }

  const assignment = submission.assignments;
  const courseId = assignment.course_id;

  const rubric = [...assignment.assignment_rubrics]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map(({ criterion_name, description, max_score }) => ({
      criterion_name,
      description,
      max_score,
    }));

  // 2. Fetch qdrant_collection from knowledge_documents for this course
  const { data: knowledgeDocs } = await supabase
    .from("knowledge_documents")
    .select("qdrant_collection")
    .eq("course_id", courseId)
    .eq("ingest_status", "ready")
    .limit(1);

  const collectionName =
    knowledgeDocs?.[0]?.qdrant_collection ?? "rag_demo_bge_m3";

  // Mark as grading
  await supabase
    .from("submissions")
    .update({ status: "grading" })
    .eq("id", submissionId);

  const serviceClient = createServiceClient();

  try {
    // 3. Call Python grading endpoint with course-scoped collection + filter
    const ragRes = await fetch(`${RAG_API}/grading/grade-submission`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        submission_text: submission.extracted_text,
        rubric,
        assignment_title: assignment.title ?? "",
        assignment_instructions: assignment.description ?? "",
        collection_name: collectionName,
        metadata_filters: { course_id: courseId },
      }),
      signal: AbortSignal.timeout(120_000),
    });

    if (!ragRes.ok) {
      const detail = await ragRes.text();
      throw new Error(`RAG backend ${ragRes.status}: ${detail}`);
    }

    const grade = await ragRes.json();

    // 4. Upsert grade proposal using service client (bypasses RLS)
    const { error: proposalError } = await serviceClient
      .from("submission_grade_proposals")
      .upsert({
        submission_id: submissionId,
        proposed_total_score: grade.proposed_total_score,
        proposed_student_reason: grade.student_reason,
        proposed_internal_reason: grade.internal_reason,
        rubric_breakdown: grade.rubric_breakdown,
        retrieval_evidence: grade.evidence,
        llm_model: grade.model_used ?? null,
      });

    if (proposalError) throw new Error(proposalError.message);

    // 5. Update submission status using service client
    await serviceClient
      .from("submissions")
      .update({ status: "pending_approval" })
      .eq("id", submissionId);

    return NextResponse.json({ success: true, grade });
  } catch (err) {
    await serviceClient
      .from("submissions")
      .update({ status: "failed", processing_error: err.message })
      .eq("id", submissionId);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
