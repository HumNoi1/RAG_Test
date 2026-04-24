import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";

const RAG_BASE = process.env.NEXT_PUBLIC_RAG_API_URL ?? "http://localhost:8000";

// Decode .txt bytes → string (UTF-8 → TIS-620 fallback, same as Python backend)
function decodeTxt(buffer) {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    return new TextDecoder("windows-874").decode(buffer);
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

  const fileBuffer = await file.arrayBuffer();
  const safeFilename = file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
  const storagePath = `${assignmentId}/${Date.now()}-${safeFilename}`;
  const serviceClient = createServiceClient();

  // ── 1. Check for existing submission (for re-upload) ───────────────────
  const { data: existing } = await supabase
    .from("submissions")
    .select("id, storage_path, status")
    .eq("assignment_id", assignmentId)
    .eq("student_id", studentId)
    .maybeSingle();

  // ── 2. Delete old storage file (best-effort, ignore errors) ───────────
  if (existing?.storage_path) {
    try {
      await serviceClient.storage
        .from("submission-files")
        .remove([existing.storage_path]);
    } catch {
      // best-effort — ignore if file already gone
    }
  }

  // ── 3. Upsert submission row ───────────────────────────────────────────
  // onConflict targets the unique(assignment_id, student_id) constraint.
  // The existing row's UUID is preserved so foreign keys stay intact.
  const { data: submission, error: upsertError } = await supabase
    .from("submissions")
    .upsert(
      {
        assignment_id: assignmentId,
        student_id: studentId,
        original_filename: file.name,
        storage_path: storagePath,
        mime_type: file.type || "text/plain",
        file_size_bytes: fileBuffer.byteLength,
        status: "uploaded",
        uploaded_by: user.id,
        // Reset fields from any previous attempt
        extracted_text: null,
        processing_error: null,
        approved_by: null,
        approved_at: null,
      },
      { onConflict: "assignment_id,student_id" },
    )
    .select()
    .single();

  if (upsertError) {
    console.error("[submit] upsert error:", upsertError);
    return NextResponse.json(
      { error: `DB error: ${upsertError.message}` },
      { status: 500 },
    );
  }

  // ── 4. Delete stale grade proposals for this submission ────────────────
  // (submission_id FK is preserved across upsert, so we clean up manually)
  if (existing?.id) {
    try {
      await supabase
        .from("submission_grade_proposals")
        .delete()
        .eq("submission_id", existing.id);
    } catch {
      // best-effort
    }

    try {
      await supabase
        .from("submission_final_results")
        .delete()
        .eq("submission_id", existing.id);
    } catch {
      // best-effort
    }
  }

  // ── 5. Upload new file to Storage (service role — bypass RLS) ──────────
  const { error: storageError } = await serviceClient.storage
    .from("submission-files")
    .upload(storagePath, fileBuffer, {
      contentType: file.type || "text/plain",
      upsert: false,
    });

  if (storageError) {
    console.error("[submit] storage error:", storageError);
    await supabase
      .from("submissions")
      .update({ status: "failed", processing_error: storageError.message })
      .eq("id", submission.id);
    return NextResponse.json(
      { error: `Storage error: ${storageError.message}` },
      { status: 500 },
    );
  }

  // ── 6. Extract text ────────────────────────────────────────────────────
  // .txt  → decode in JS directly (fast, no Python dependency)
  // .pdf / .docx → call Python backend
  let extractedText = "";

  if (isTxt) {
    extractedText = decodeTxt(fileBuffer);
  } else {
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

      extractedText = (await ragRes.json()).text ?? "";
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

  // ── 7. Mark text_ready ─────────────────────────────────────────────────
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

  const isResubmit = !!existing;
  return NextResponse.json({
    success: true,
    resubmit: isResubmit,
    submission: updated,
  });
}
