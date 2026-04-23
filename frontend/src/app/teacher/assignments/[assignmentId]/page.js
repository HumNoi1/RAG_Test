'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/client'

const STATUS_COLOR = {
  uploaded: 'bg-gray-100 text-gray-600',
  text_ready: 'bg-blue-100 text-blue-700',
  grading: 'bg-yellow-100 text-yellow-700',
  pending_approval: 'bg-orange-100 text-orange-700',
  approved: 'bg-green-100 text-green-700',
  overridden: 'bg-purple-100 text-purple-700',
  failed: 'bg-red-100 text-red-700',
}

const STATUS_LABEL = {
  uploaded: 'อัปโหลดแล้ว',
  text_ready: 'แปลงข้อความแล้ว',
  grading: 'กำลังตรวจ...',
  pending_approval: 'รออนุมัติ',
  approved: 'อนุมัติแล้ว',
  overridden: 'Override แล้ว',
  failed: 'ล้มเหลว',
}

export default function AssignmentPage() {
  const params = useParams()
  const assignmentId = params.assignmentId
  const router = useRouter()

  const [assignment, setAssignment] = useState(null)
  const [submissions, setSubmissions] = useState([])
  const [students, setStudents] = useState([])
  const [loading, setLoading] = useState(true)

  // Upload submission form
  const [showSubmitForm, setShowSubmitForm] = useState(false)
  const [submitFile, setSubmitFile] = useState(null)
  const [submitStudentId, setSubmitStudentId] = useState('')
  const [submitLoading, setSubmitLoading] = useState(false)
  const [submitError, setSubmitError] = useState('')

  // Grading state
  const [gradingId, setGradingId] = useState(null)
  const [gradeError, setGradeError] = useState('')

  // Approve/Override state
  const [approvingId, setApprovingId] = useState(null)
  const [overrideScore, setOverrideScore] = useState('')
  const [overrideReason, setOverrideReason] = useState('')
  const [overrideNote, setOverrideNote] = useState('')
  const [approveLoading, setApproveLoading] = useState(false)
  const [approveError, setApproveError] = useState('')

  // Expanded proposal view
  const [expandedProposal, setExpandedProposal] = useState(null)

  useEffect(() => {
    loadAll()
  }, [assignmentId])

  async function loadAll() {
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return router.push('/login')

    const [assignRes, subsRes] = await Promise.all([
      supabase
        .from('assignments')
        .select('id, title, description, max_score, status, course_id, assignment_rubrics(id, criterion_name, description, max_score, sort_order)')
        .eq('id', assignmentId)
        .single(),
      supabase
        .from('submissions')
        .select(`
          id, status, original_filename, created_at,
          profiles ( id, full_name, email ),
          submission_grade_proposals (
            proposed_total_score,
            proposed_student_reason,
            proposed_internal_reason,
            rubric_breakdown,
            llm_model,
            teacher_override_note
          )
        `)
        .eq('assignment_id', assignmentId)
        .order('created_at', { ascending: false }),
    ])

    if (!assignRes.data) return router.push('/teacher')

    const a = assignRes.data
    a.assignment_rubrics = [...(a.assignment_rubrics ?? [])].sort((x, y) => x.sort_order - y.sort_order)
    setAssignment(a)
    setSubmissions(subsRes.data ?? [])

    // Load enrolled students for this course
    const { data: enrolled } = await supabase
      .from('course_students')
      .select('student_id, profiles(id, full_name, email)')
      .eq('course_id', a.course_id)

    setStudents(enrolled?.map(e => e.profiles).filter(Boolean) ?? [])
    setLoading(false)
  }

  // --- Upload student submission ---
  async function uploadSubmission(e) {
    e.preventDefault()
    if (!submitFile || !submitStudentId) return
    setSubmitLoading(true)
    setSubmitError('')

    const form = new FormData()
    form.append('file', submitFile)
    form.append('assignmentId', assignmentId)
    form.append('studentId', submitStudentId)

    const res = await fetch('/api/submit', { method: 'POST', body: form })
    const data = await res.json()

    if (!res.ok) {
      setSubmitError(data.error ?? 'เกิดข้อผิดพลาด')
    } else {
      setShowSubmitForm(false)
      setSubmitFile(null)
      setSubmitStudentId('')
      await loadAll()
    }
    setSubmitLoading(false)
  }

  // --- Grade submission ---
  async function gradeSubmission(submissionId) {
    setGradingId(submissionId)
    setGradeError('')

    const res = await fetch('/api/grade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ submissionId }),
    })
    const data = await res.json()

    if (!res.ok) {
      setGradeError(`[${submissionId.slice(0, 8)}] ${data.error ?? 'เกิดข้อผิดพลาด'}`)
    } else {
      await loadAll()
    }
    setGradingId(null)
  }

  // --- Approve / Override ---
  async function approveSubmission(submissionId) {
    setApproveLoading(true)
    setApproveError('')

    const body = { submissionId }
    if (overrideScore !== '') body.overrideScore = Number(overrideScore)
    if (overrideReason.trim()) body.overrideReason = overrideReason.trim()
    if (overrideNote.trim()) body.note = overrideNote.trim()

    const res = await fetch('/api/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()

    if (!res.ok) {
      setApproveError(data.error ?? 'เกิดข้อผิดพลาด')
    } else {
      setApprovingId(null)
      setOverrideScore('')
      setOverrideReason('')
      setOverrideNote('')
      await loadAll()
    }
    setApproveLoading(false)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-gray-400">
        กำลังโหลด...
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-start gap-3 mb-8">
        <Link
          href={`/teacher/courses/${assignment.course_id}`}
          className="text-gray-400 hover:text-gray-700 text-sm mt-1"
        >
          ← กลับ
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900">{assignment.title}</h1>
          {assignment.description && (
            <p className="text-sm text-gray-500 mt-1">{assignment.description}</p>
          )}
          <p className="text-sm text-gray-400 mt-1">คะแนนรวม {Number(assignment.max_score).toFixed(0)} คะแนน</p>
        </div>
      </div>

      {/* Rubric Summary */}
      <section className="mb-8">
        <h2 className="text-base font-semibold text-gray-800 mb-3">📋 เกณฑ์การตรวจ (Rubric)</h2>
        <div className="bg-white rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2 text-gray-600 font-medium">เกณฑ์</th>
                <th className="text-left px-4 py-2 text-gray-600 font-medium">คำอธิบาย</th>
                <th className="text-right px-4 py-2 text-gray-600 font-medium">คะแนน</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {assignment.assignment_rubrics.map(r => (
                <tr key={r.id}>
                  <td className="px-4 py-2 font-medium text-gray-900">{r.criterion_name}</td>
                  <td className="px-4 py-2 text-gray-500">{r.description || '—'}</td>
                  <td className="px-4 py-2 text-right text-gray-700">{Number(r.max_score).toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Submissions */}
      <section>
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold text-gray-900">
            📥 งานที่ส่ง ({submissions.length})
          </h2>
          <button
            onClick={() => { setShowSubmitForm(!showSubmitForm); setSubmitError('') }}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg"
          >
            + อัปโหลดงาน
          </button>
        </div>

        {/* Upload submission form */}
        {showSubmitForm && (
          <form onSubmit={uploadSubmission} className="bg-white rounded-xl border p-5 mb-4 space-y-3">
            <h3 className="font-medium text-gray-800">อัปโหลดงานนักเรียน</h3>

            <div>
              <label className="block text-xs text-gray-500 mb-1">เลือกนักเรียน</label>
              {students.length === 0 ? (
                <p className="text-sm text-red-500">
                  ยังไม่มีนักเรียนในวิชานี้ — กลับไปเพิ่มนักเรียนก่อน
                </p>
              ) : (
                <select
                  required
                  value={submitStudentId}
                  onChange={e => setSubmitStudentId(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">-- เลือกนักเรียน --</option>
                  {students.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.full_name || s.email} ({s.email})
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-1">ไฟล์งาน (.txt, .pdf, .docx)</label>
              <input
                type="file"
                required
                accept=".txt,.pdf,.docx"
                onChange={e => setSubmitFile(e.target.files[0])}
                className="w-full text-sm text-gray-600 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
              />
            </div>

            {submitError && <p className="text-red-500 text-sm">{submitError}</p>}

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={submitLoading || students.length === 0}
                className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-50"
              >
                {submitLoading ? 'กำลังอัปโหลด...' : 'อัปโหลด'}
              </button>
              <button
                type="button"
                onClick={() => setShowSubmitForm(false)}
                className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2"
              >
                ยกเลิก
              </button>
            </div>
          </form>
        )}

        {gradeError && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-4 text-sm text-red-600">
            {gradeError}
          </div>
        )}

        {submissions.length === 0 ? (
          <div className="bg-white rounded-xl border border-dashed border-gray-300 p-10 text-center">
            <p className="text-gray-400 text-sm">ยังไม่มีงานที่ส่ง</p>
          </div>
        ) : (
          <div className="space-y-4">
            {submissions.map(sub => {
              const proposal = sub.submission_grade_proposals
              const student = sub.profiles
              const isGrading = gradingId === sub.id
              const isApproving = approvingId === sub.id
              const canGrade = ['text_ready', 'failed'].includes(sub.status)
              const canApprove = sub.status === 'pending_approval'
              const isFinished = ['approved', 'overridden'].includes(sub.status)

              return (
                <div key={sub.id} className="bg-white rounded-xl border overflow-hidden">
                  {/* Submission header */}
                  <div className="flex justify-between items-start px-5 py-4">
                    <div>
                      <p className="font-medium text-gray-900">
                        {student?.full_name || student?.email || 'ไม่ระบุชื่อ'}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">{sub.original_filename}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${STATUS_COLOR[sub.status] ?? 'bg-gray-100 text-gray-600'}`}>
                        {STATUS_LABEL[sub.status] ?? sub.status}
                      </span>
                    </div>
                  </div>

                  {/* Proposal summary */}
                  {proposal && (
                    <div className="border-t border-gray-100 px-5 py-3 bg-gray-50">
                      <div className="flex justify-between items-center">
                        <div className="flex items-center gap-4">
                          <span className="text-2xl font-bold text-blue-600">
                            {Number(proposal.proposed_total_score).toFixed(1)}
                          </span>
                          <span className="text-sm text-gray-400">/ {Number(assignment.max_score).toFixed(0)}</span>
                          {proposal.llm_model && (
                            <span className="text-xs text-gray-400 bg-gray-200 px-2 py-0.5 rounded">
                              {proposal.llm_model.split('/').pop()}
                            </span>
                          )}
                        </div>
                        <button
                          onClick={() => setExpandedProposal(expandedProposal === sub.id ? null : sub.id)}
                          className="text-xs text-blue-600 hover:text-blue-800 underline"
                        >
                          {expandedProposal === sub.id ? 'ซ่อนรายละเอียด' : 'ดูรายละเอียด'}
                        </button>
                      </div>

                      <p className="text-sm text-gray-700 mt-2 leading-relaxed">
                        {proposal.proposed_student_reason}
                      </p>

                      {/* Expanded detail */}
                      {expandedProposal === sub.id && (
                        <div className="mt-4 space-y-3">
                          {/* Internal reason */}
                          <div>
                            <p className="text-xs font-semibold text-gray-500 uppercase mb-1">
                              Internal Reason (เห็นเฉพาะอาจารย์)
                            </p>
                            <p className="text-sm text-gray-600 bg-yellow-50 rounded-lg px-3 py-2 border border-yellow-100">
                              {proposal.proposed_internal_reason}
                            </p>
                          </div>

                          {/* Rubric breakdown */}
                          {Array.isArray(proposal.rubric_breakdown) && proposal.rubric_breakdown.length > 0 && (
                            <div>
                              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">
                                Rubric Breakdown
                              </p>
                              <div className="border rounded-lg overflow-hidden">
                                <table className="w-full text-sm">
                                  <thead className="bg-gray-100">
                                    <tr>
                                      <th className="text-left px-3 py-2 text-gray-600 font-medium">เกณฑ์</th>
                                      <th className="text-right px-3 py-2 text-gray-600 font-medium">คะแนน</th>
                                      <th className="text-left px-3 py-2 text-gray-600 font-medium">เหตุผล</th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-gray-100 bg-white">
                                    {proposal.rubric_breakdown.map((rb, i) => (
                                      <tr key={i}>
                                        <td className="px-3 py-2 font-medium text-gray-800">{rb.criterion_name}</td>
                                        <td className="px-3 py-2 text-right text-gray-700 whitespace-nowrap">
                                          {Number(rb.score).toFixed(1)} / {Number(rb.max_score).toFixed(0)}
                                        </td>
                                        <td className="px-3 py-2 text-gray-500 text-xs">{rb.reason}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          )}

                          {/* Override note if exists */}
                          {proposal.teacher_override_note && (
                            <div>
                              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">หมายเหตุจากอาจารย์</p>
                              <p className="text-sm text-gray-600 bg-purple-50 rounded-lg px-3 py-2 border border-purple-100">
                                {proposal.teacher_override_note}
                              </p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Actions */}
                  <div className="border-t border-gray-100 px-5 py-3 flex flex-wrap gap-2">
                    {/* Grade button */}
                    {canGrade && (
                      <button
                        onClick={() => gradeSubmission(sub.id)}
                        disabled={isGrading}
                        className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm px-4 py-1.5 rounded-lg disabled:opacity-50 transition-colors"
                      >
                        {isGrading ? '🤖 กำลังตรวจ...' : '🤖 ตรวจด้วย AI'}
                      </button>
                    )}

                    {/* Approve/Override button */}
                    {canApprove && !isApproving && (
                      <button
                        onClick={() => setApprovingId(sub.id)}
                        className="bg-green-600 hover:bg-green-700 text-white text-sm px-4 py-1.5 rounded-lg transition-colors"
                      >
                        ✅ อนุมัติ / Override
                      </button>
                    )}

                    {isFinished && (
                      <span className="text-xs text-gray-400 self-center">
                        {sub.status === 'approved' ? '✅ อนุมัติแล้ว' : '✏️ Override แล้ว'}
                      </span>
                    )}
                  </div>

                  {/* Approve / Override panel */}
                  {isApproving && (
                    <div className="border-t border-orange-100 bg-orange-50 px-5 py-4 space-y-3">
                      <p className="text-sm font-medium text-gray-800">
                        อนุมัติคะแนน หรือ Override (เว้นว่างเพื่ออนุมัติตามที่ AI เสนอ)
                      </p>

                      <div className="flex gap-3">
                        <div className="w-32">
                          <label className="block text-xs text-gray-500 mb-1">
                            คะแนน Override (ไม่บังคับ)
                          </label>
                          <input
                            type="number"
                            min="0"
                            max={Number(assignment.max_score)}
                            step="0.5"
                            placeholder={proposal ? String(Number(proposal.proposed_total_score).toFixed(1)) : ''}
                            value={overrideScore}
                            onChange={e => setOverrideScore(e.target.value)}
                            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                          />
                        </div>
                        <div className="flex-1">
                          <label className="block text-xs text-gray-500 mb-1">
                            เหตุผลสำหรับนักเรียน (Override — ไม่บังคับ)
                          </label>
                          <input
                            type="text"
                            placeholder="ปล่อยว่างเพื่อใช้ข้อความจาก AI"
                            value={overrideReason}
                            onChange={e => setOverrideReason(e.target.value)}
                            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                          />
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs text-gray-500 mb-1">
                          หมายเหตุภายใน (ไม่แสดงนักเรียน — ไม่บังคับ)
                        </label>
                        <input
                          type="text"
                          placeholder="เช่น ปรับคะแนนเพราะ..."
                          value={overrideNote}
                          onChange={e => setOverrideNote(e.target.value)}
                          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                        />
                      </div>

                      {approveError && (
                        <p className="text-red-500 text-sm">{approveError}</p>
                      )}

                      <div className="flex gap-2">
                        <button
                          onClick={() => approveSubmission(sub.id)}
                          disabled={approveLoading}
                          className="bg-green-600 hover:bg-green-700 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-50 transition-colors"
                        >
                          {approveLoading
                            ? 'กำลังบันทึก...'
                            : overrideScore !== ''
                            ? '✏️ Override และเผยแพร่'
                            : '✅ อนุมัติและเผยแพร่ผล'}
                        </button>
                        <button
                          onClick={() => {
                            setApprovingId(null)
                            setOverrideScore('')
                            setOverrideReason('')
                            setOverrideNote('')
                            setApproveError('')
                          }}
                          className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2"
                        >
                          ยกเลิก
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
