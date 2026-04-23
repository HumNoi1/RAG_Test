import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createServiceClient } from '@/lib/supabase/service'

const RAG_BASE = process.env.NEXT_PUBLIC_RAG_API_URL ?? 'http://localhost:8000'

export async function POST(request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  let form
  try {
    form = await request.formData()
  } catch {
    return NextResponse.json({ error: 'Invalid form data' }, { status: 400 })
  }

  const file = form.get('file')
  const assignmentId = form.get('assignmentId')
  const studentId = form.get('studentId')

  if (!file || !assignmentId || !studentId) {
    return NextResponse.json({ error: 'file, assignmentId, studentId are required' }, { status: 400 })
  }

  const timestamp = Date.now()
  const safeFilename = file.name.replace(/[^a-zA-Z0-9._-]/g, '_')
  const storagePath = `${assignmentId}/${timestamp}-${safeFilename}`

  // Insert submission record first (status: uploaded)
  const { data: submission, error: insertError } = await supabase
    .from('submissions')
    .insert({
      assignment_id: assignmentId,
      student_id: studentId,
      original_filename: file.name,
      storage_path: storagePath,
      mime_type: file.type || 'application/octet-stream',
      file_size_bytes: file.size,
      status: 'uploaded',
      uploaded_by: user.id,
    })
    .select()
    .single()

  if (insertError) {
    return NextResponse.json({ error: insertError.message }, { status: 500 })
  }

  // Upload file to Supabase Storage
  const fileBuffer = await file.arrayBuffer()
  const { error: storageError } = await supabase.storage
    .from('submission-files')
    .upload(storagePath, fileBuffer, { contentType: file.type || 'application/octet-stream' })

  if (storageError) {
    await supabase
      .from('submissions')
      .update({ status: 'failed', processing_error: storageError.message })
      .eq('id', submission.id)
    return NextResponse.json({ error: storageError.message }, { status: 500 })
  }

  // Extract text via Python backend
  try {
    const ragForm = new FormData()
    ragForm.append('file', new Blob([fileBuffer], { type: file.type }), file.name)

    const ragRes = await fetch(`${RAG_BASE}/documents/extract-text`, {
      method: 'POST',
      body: ragForm,
    })

    if (!ragRes.ok) {
      const errText = await ragRes.text()
      throw new Error(errText)
    }

    const { text } = await ragRes.json()

    // Update submission with extracted text
    const { data: updated } = await supabase
      .from('submissions')
      .update({ extracted_text: text, status: 'text_ready' })
      .eq('id', submission.id)
      .select()
      .single()

    return NextResponse.json({ success: true, submission: updated })
  } catch (err) {
    await supabase
      .from('submissions')
      .update({ status: 'failed', processing_error: err.message })
      .eq('id', submission.id)
    return NextResponse.json({ error: err.message }, { status: 500 })
  }
}
