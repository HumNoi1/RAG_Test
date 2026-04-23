import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

const RAG_API = process.env.NEXT_PUBLIC_RAG_API_URL ?? 'http://localhost:8000'

export async function POST(request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const form = await request.formData()
  const file = form.get('file')
  const courseId = form.get('courseId')
  const documentTitle = form.get('documentTitle') || file.name
  const assignmentId = form.get('assignmentId') || null

  if (!file || !courseId) {
    return NextResponse.json({ error: 'file และ courseId จำเป็นต้องมี' }, { status: 400 })
  }

  const storagePath = `${courseId}/${Date.now()}-${file.name}`
  const fileBuffer = await file.arrayBuffer()

  // 1. Insert knowledge_documents row (status: pending)
  const { data: doc, error: insertError } = await supabase
    .from('knowledge_documents')
    .insert({
      course_id: courseId,
      assignment_id: assignmentId,
      title: documentTitle,
      original_filename: file.name,
      storage_path: storagePath,
      mime_type: file.type || 'application/octet-stream',
      file_size_bytes: fileBuffer.byteLength,
      qdrant_collection: process.env.QDRANT_COLLECTION ?? 'rag_demo_bge_m3',
      ingest_status: 'pending',
      uploaded_by: user.id,
    })
    .select()
    .single()

  if (insertError) {
    return NextResponse.json({ error: insertError.message }, { status: 500 })
  }

  // 2. Upload to Supabase Storage
  const { error: storageError } = await supabase.storage
    .from('knowledge-files')
    .upload(storagePath, fileBuffer, { contentType: file.type || 'application/octet-stream' })

  if (storageError) {
    await supabase
      .from('knowledge_documents')
      .update({ ingest_status: 'failed', ingest_error: storageError.message })
      .eq('id', doc.id)
    return NextResponse.json({ error: `Storage error: ${storageError.message}` }, { status: 500 })
  }

  // 3. Update status to processing
  await supabase
    .from('knowledge_documents')
    .update({ ingest_status: 'processing' })
    .eq('id', doc.id)

  // 4. Call Python backend to extract + ingest into Qdrant
  try {
    const ragForm = new FormData()
    ragForm.append('file', new Blob([fileBuffer], { type: file.type }), file.name)
    ragForm.append(
      'metadata',
      JSON.stringify({
        course_id: courseId,
        document_id: doc.id,
        source_kind: 'course_material',
        ...(assignmentId ? { assignment_id: assignmentId } : {}),
      })
    )

    const ragRes = await fetch(`${RAG_API}/documents/upload-and-ingest`, {
      method: 'POST',
      body: ragForm,
    })

    if (!ragRes.ok) {
      const detail = await ragRes.text()
      throw new Error(detail)
    }

    const ragData = await ragRes.json()

    // 5. Mark ready + store chunk count
    await supabase
      .from('knowledge_documents')
      .update({ ingest_status: 'ready', chunks_stored: ragData.chunks_stored })
      .eq('id', doc.id)

    return NextResponse.json({ success: true, document_id: doc.id, chunks_stored: ragData.chunks_stored })
  } catch (err) {
    await supabase
      .from('knowledge_documents')
      .update({ ingest_status: 'failed', ingest_error: err.message })
      .eq('id', doc.id)
    return NextResponse.json({ error: `Ingest error: ${err.message}` }, { status: 500 })
  }
}
