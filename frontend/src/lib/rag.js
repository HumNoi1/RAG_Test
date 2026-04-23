const BASE = process.env.NEXT_PUBLIC_RAG_API_URL ?? 'http://localhost:8000'

export async function ingestFile(file, metadata = {}) {
  const form = new FormData()
  form.append('file', file)
  if (Object.keys(metadata).length > 0) {
    form.append('metadata', JSON.stringify(metadata))
  }
  const res = await fetch(`${BASE}/documents/upload-and-ingest`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function extractText(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/documents/extract-text`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function gradeSubmission({ submissionText, rubric, assignmentTitle, assignmentInstructions, metadataFilters }) {
  const res = await fetch(`${BASE}/grading/grade-submission`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      submission_text: submissionText,
      rubric,
      assignment_title: assignmentTitle ?? '',
      assignment_instructions: assignmentInstructions ?? '',
      metadata_filters: metadataFilters ?? {},
    }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
