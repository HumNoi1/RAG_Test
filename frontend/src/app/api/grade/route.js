import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { gradeSubmission } from '@/lib/rag'

export async function POST(request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { submissionId } = await request.json()

  // Get submission + assignment + rubric
  const { data: submission, error: fetchError } = await supabase
    .from('submissions')
    .select(`
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
    `)
    .eq('id', submissionId)
    .single()

  if (fetchError || !submission) {
    return NextResponse.json({ error: 'Submission not found' }, { status: 404 })
  }

  if (!submission.extracted_text) {
    return NextResponse.json({ error: 'ยังไม่มี extracted text — กรุณาอัปโหลดไฟล์ก่อน' }, { status: 400 })
  }

  const assignment = submission.assignments
  const rubric = [...assignment.assignment_rubrics]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map(({ criterion_name, description, max_score }) => ({ criterion_name, description, max_score }))

  // Mark as grading
  await supabase
    .from('submissions')
    .update({ status: 'grading' })
    .eq('id', submissionId)

  try {
    const grade = await gradeSubmission({
      submissionText: submission.extracted_text,
      rubric,
      assignmentTitle: assignment.title,
      assignmentInstructions: assignment.description,
      metadataFilters: { course_id: assignment.course_id },
    })

    // Save proposal
    const { error: proposalError } = await supabase
      .from('submission_grade_proposals')
      .upsert({
        submission_id: submissionId,
        proposed_total_score: grade.proposed_total_score,
        proposed_student_reason: grade.student_reason,
        proposed_internal_reason: grade.internal_reason,
        rubric_breakdown: grade.rubric_breakdown,
        retrieval_evidence: grade.evidence,
        llm_model: grade.model_used ?? null,
      })

    if (proposalError) throw new Error(proposalError.message)

    await supabase
      .from('submissions')
      .update({ status: 'pending_approval' })
      .eq('id', submissionId)

    return NextResponse.json({ success: true, grade })
  } catch (err) {
    await supabase
      .from('submissions')
      .update({ status: 'failed', processing_error: err.message })
      .eq('id', submissionId)
    return NextResponse.json({ error: err.message }, { status: 500 })
  }
}
