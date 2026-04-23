import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

export async function POST(request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { submissionId, overrideScore, overrideReason, note } = await request.json()
  if (!submissionId) return NextResponse.json({ error: 'submissionId required' }, { status: 400 })

  // Get submission + proposal + assignment + course
  const { data: submission, error: fetchError } = await supabase
    .from('submissions')
    .select(`
      id,
      student_id,
      submission_grade_proposals (
        proposed_total_score,
        proposed_student_reason
      ),
      assignments (
        id,
        title,
        course_id,
        courses (
          code,
          name
        )
      )
    `)
    .eq('id', submissionId)
    .single()

  if (fetchError || !submission) {
    return NextResponse.json({ error: fetchError?.message ?? 'Submission not found' }, { status: 404 })
  }

  const proposal = submission.submission_grade_proposals
  if (!proposal) {
    return NextResponse.json({ error: 'No grade proposal found — grade first' }, { status: 400 })
  }

  const assignment = submission.assignments
  const course = assignment.courses

  const finalScore = overrideScore != null ? Number(overrideScore) : Number(proposal.proposed_total_score)
  const finalReason = overrideReason?.trim() || proposal.proposed_student_reason
  const status = overrideScore != null ? 'overridden' : 'approved'

  // Write final result (student-visible)
  const { error: finalError } = await supabase
    .from('submission_final_results')
    .upsert({
      submission_id: submissionId,
      student_id: submission.student_id,
      assignment_id: assignment.id,
      assignment_title: assignment.title,
      course_id: assignment.course_id,
      course_code: course.code,
      course_name: course.name,
      final_total_score: finalScore,
      final_reason: finalReason,
    })

  if (finalError) {
    return NextResponse.json({ error: finalError.message }, { status: 500 })
  }

  // Update submission status + approval info
  const { error: updateError } = await supabase
    .from('submissions')
    .update({
      status,
      approved_by: user.id,
      approved_at: new Date().toISOString(),
    })
    .eq('id', submissionId)

  if (updateError) {
    return NextResponse.json({ error: updateError.message }, { status: 500 })
  }

  // Save override note if provided
  if (note?.trim()) {
    await supabase
      .from('submission_grade_proposals')
      .update({ teacher_override_note: note.trim() })
      .eq('submission_id', submissionId)
  }

  return NextResponse.json({ success: true, status, final_score: finalScore })
}
