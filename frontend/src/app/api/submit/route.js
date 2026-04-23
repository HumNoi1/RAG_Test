import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";

const RAG_BASE = process.env.NEXT_PUBLIC_RAG_API_URL ?? "http://localhost:8000";

// Decode .txt bytes → string (UTF-8 → TIS-620 fallback, same as Python backend)
function decodeTxt(buffer) {
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
    return text;
  } catch {
    return new TextDecoder("windows-874").decode(buffer); // TIS-620 / Thai Windows
  }
}

export async function POST(request) {
  // ── Auth ───────────────────────────────────────────────────────────────
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user)
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  // ── Parse form ─────────────────────────────────────────────────────────
  let form;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json({ error: "FormData ไม่ถูกต้อง" }, { status: 400 });
  }

  const file = form.get("file");
  const assignmentId = form.get("assignmentId");
  const studentId = form.get("studentId");

  if (!file || !assignmentId || !studentId) {
    return NextResponse.json(
      { error: "file, assignmentId และ studentId จำเป็นต้องมี" },
      { status: 400 },
    );
  }

  // ── Validate file type ─────────────────────────────────────────────────
  const nameLower = file.name.toLowerCase();
  const isTxt = nameLower.endsWith(".txt");
  const isPdf = nameLower.endsWith(".pdf");
  const isDocx = nameLower.endsWith(".docx");

  if (!isTxt && !isPdf && !isDocx) {
    return NextResponse.json(
      { error: "รองรับเฉพาะไฟล์ .txt, .pdf และ .docx เท่านั้น" },
      { status: 400 },
    );
  }

  const timestamp = Date.now();
  const safeFilename = file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
  const storagePath = `${assignmentId}/${timestamp}-${safeFilename}`;
  const fileBuffer = await file.arrayBuffer();

  // ── 1. Insert submission record (status: uploaded) ─────────────────────
  const { data: submission, error: insertError } = await supabase
    .from("submissions")
    .insert({
      assignment_id: assignmentId,
      student_id: studentId,
      original_filename: file.name,
      storage_path: storagePath,
      mime_type: file.type || "text/plain",
      file_size_bytes: fileBuffer.byteLength,
      status: "uploaded",
      uploaded_by: user.id,
    })
    .select()
    .single();

  if (insertError) {
    console.error("[submit] DB insert error:", insertError);
    return NextResponse.json(
      { error: `DB error: ${insertError.message}` },
      { status: 500 },
    );
  }

  // ── 2. Upload to Storage (service role — bypass storage RLS) ───────────
  const serviceClient = createServiceClient();
  const { error: storageError } = await serviceClient.storage
    .from("submission-files")
    .upload(storagePath, fileBuffer, {
      contentType: file.type || "text/plain",
      upsert: false,
    });

  if (storageError) {
    console.error("[submit] Storage error:", storageError);
    await supabase
      .from("submissions")
      .update({ status: "failed", processing_error: storageError.message })
      .eq("id", submission.id);
    return NextResponse.json(
      { error: `Storage error: ${storageError.message}` },
      { status: 500 },
    );
  }

  // ── 3. Extract text ────────────────────────────────────────────────────
  // .txt  → decode directly in JS (no Python needed)
  // .pdf / .docx → call Python backend extract-text endpoint
  let extractedText = "";

  if (isTxt) {
    // Fast path: decode bytes locally
    extractedText = decodeTxt(fileBuffer);
  } else {
    // PDF / DOCX → Python backend
    try {
      const ragForm = new FormData();
      ragForm.append(
        "file",
        new Blob([fileBuffer], { type: file.type }),
        file.name,
      );

      const ragRes = await fetch(`${RAG_BASE}/documents/extract-text`, {
        method: "POST",
        body: ragForm,
        signal: AbortSignal.timeout(60_000),
      });

      if (!ragRes.ok) {
        const detail = await ragRes.text();
        throw new Error(`RAG backend ${ragRes.status}: ${detail}`);
      }

      const json = await ragRes.json();
      extractedText = json.text ?? "";
    } catch (err) {
      console.error("[submit] extract-text error:", err);
      await supabase
        .from("submissions")
        .update({ status: "failed", processing_error: err.message })
        .eq("id", submission.id);

      const cantReach =
        err.message?.includes("ECONNREFUSED") ||
        err.message?.includes("fetch failed") ||
        err.message?.includes("timeout") ||
        err.name === "TimeoutError";

      return NextResponse.json(
        {
          error: cantReach
            ? `ไม่สามารถเชื่อมต่อ RAG backend ได้ — ตรวจสอบว่า Python server รันอยู่ที่ ${RAG_BASE}`
            : `Extract error: ${err.message}`,
        },
        { status: 500 },
      );
    }
  }

  if (!extractedText.trim()) {
    await supabase
      .from("submissions")
      .update({ status: "failed", processing_error: "ไม่พบข้อความในไฟล์" })
      .eq("id", submission.id);
    return NextResponse.json(
      { error: "ไม่พบข้อความในไฟล์ กรุณาตรวจสอบว่าไฟล์ไม่ว่างเปล่า" },
      { status: 400 },
    );
  }

  // ── 4. Save extracted text → status: text_ready ───────────────────────
  const { data: updated, error: updateError } = await supabase
    .from("submissions")
    .update({ extracted_text: extractedText, status: "text_ready" })
    .eq("id", submission.id)
    .select()
    .single();

  if (updateError) {
    console.error("[submit] update error:", updateError);
    return NextResponse.json(
      { error: `Update error: ${updateError.message}` },
      { status: 500 },
    );
  }

  return NextResponse.json({ success: true, submission: updated });
}
