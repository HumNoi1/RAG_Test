import { NextResponse } from "next/server";
import crypto from "crypto";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";

const RAG_API = process.env.NEXT_PUBLIC_RAG_API_URL ?? "http://localhost:8000";

function computeMd5(buffer) {
  return crypto.createHash("md5").update(Buffer.from(buffer)).digest("hex");
}

async function purgeOldDocument(supabase, serviceClient, oldDoc) {
  // 1. ลบ Qdrant chunks (best-effort)
  try {
    const params = new URLSearchParams({
      collection_name: oldDoc.qdrant_collection,
      document_id: oldDoc.id,
    });
    await fetch(`${RAG_API}/documents/chunks?${params}`, {
      method: "DELETE",
      signal: AbortSignal.timeout(15_000),
    });
  } catch (err) {
    console.warn("[ingest] purge Qdrant chunks failed:", err.message);
  }

  // 2. ลบ Storage file (best-effort)
  try {
    await serviceClient.storage
      .from("knowledge-files")
      .remove([oldDoc.storage_path]);
  } catch (err) {
    console.warn("[ingest] purge storage file failed:", err.message);
  }

  // 3. ลบ DB record
  await supabase.from("knowledge_documents").delete().eq("id", oldDoc.id);
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
  const courseId = form.get("courseId");
  const documentTitle = form.get("documentTitle") || file?.name;
  const assignmentId = form.get("assignmentId") || null;

  if (!file || !courseId) {
    return NextResponse.json(
      { error: "file และ courseId จำเป็นต้องมี" },
      { status: 400 },
    );
  }

  const fileBuffer = await file.arrayBuffer();
  const md5Hash = computeMd5(fileBuffer);

  // ── ตรวจ duplicate: same MD5 + same course ──────────────────────────────
  const serviceClient = createServiceClient();
  const { data: dupDoc } = await supabase
    .from("knowledge_documents")
    .select("id, storage_path, qdrant_collection")
    .eq("course_id", courseId)
    .eq("md5_hash", md5Hash)
    .maybeSingle();

  if (dupDoc) {
    console.log(
      `[ingest] duplicate MD5 ${md5Hash} — purging old doc ${dupDoc.id}`,
    );
    await purgeOldDocument(supabase, serviceClient, dupDoc);
  }

  const storagePath = `${courseId}/${Date.now()}-${file.name}`;

  // ── 1. Insert DB record ────────────────────────────────────────────────
  const { data: doc, error: insertError } = await supabase
    .from("knowledge_documents")
    .insert({
      course_id: courseId,
      assignment_id: assignmentId,
      title: documentTitle,
      original_filename: file.name,
      storage_path: storagePath,
      mime_type: file.type || "text/plain",
      file_size_bytes: fileBuffer.byteLength,
      md5_hash: md5Hash,
      qdrant_collection: process.env.QDRANT_COLLECTION ?? "rag_demo_bge_m3",
      ingest_status: "pending",
      uploaded_by: user.id,
    })
    .select()
    .single();

  if (insertError) {
    console.error("[ingest] DB insert error:", insertError);
    return NextResponse.json(
      { error: `DB error: ${insertError.message}` },
      { status: 500 },
    );
  }

  // ── 2. Upload Storage (service role — bypass storage RLS entirely) ─────
  const { error: storageError } = await serviceClient.storage
    .from("knowledge-files")
    .upload(storagePath, fileBuffer, {
      contentType: file.type || "text/plain",
      upsert: false,
    });

  if (storageError) {
    console.error("[ingest] Storage error:", storageError);
    await supabase
      .from("knowledge_documents")
      .update({ ingest_status: "failed", ingest_error: storageError.message })
      .eq("id", doc.id);
    return NextResponse.json(
      { error: `Storage error: ${storageError.message}` },
      { status: 500 },
    );
  }

  // ── 3. Mark processing ─────────────────────────────────────────────────
  await supabase
    .from("knowledge_documents")
    .update({ ingest_status: "processing" })
    .eq("id", doc.id);

  // ── 4. Call Python RAG backend ─────────────────────────────────────────
  try {
    const ragForm = new FormData();
    ragForm.append(
      "file",
      new Blob([fileBuffer], { type: file.type || "text/plain" }),
      file.name,
    );
    ragForm.append(
      "metadata",
      JSON.stringify({
        course_id: courseId,
        document_id: doc.id,
        source_kind: "course_material",
        ...(assignmentId ? { assignment_id: assignmentId } : {}),
      }),
    );

    const ragRes = await fetch(`${RAG_API}/documents/upload-and-ingest`, {
      method: "POST",
      body: ragForm,
      signal: AbortSignal.timeout(60_000), // 60s timeout
    });

    if (!ragRes.ok) {
      const detail = await ragRes.text();
      throw new Error(`RAG backend ${ragRes.status}: ${detail}`);
    }

    const ragData = await ragRes.json();

    // ── 5. Mark ready ──────────────────────────────────────────────────
    await supabase
      .from("knowledge_documents")
      .update({
        ingest_status: "ready",
        chunks_stored: ragData.chunks_stored ?? 0,
      })
      .eq("id", doc.id);

    return NextResponse.json({
      success: true,
      document_id: doc.id,
      chunks_stored: ragData.chunks_stored ?? 0,
    });
  } catch (err) {
    console.error("[ingest] RAG backend error:", err);
    await supabase
      .from("knowledge_documents")
      .update({ ingest_status: "failed", ingest_error: err.message })
      .eq("id", doc.id);

    const cantReach =
      err.message?.includes("ECONNREFUSED") ||
      err.message?.includes("fetch failed") ||
      err.message?.includes("timeout") ||
      err.name === "TimeoutError";

    return NextResponse.json(
      {
        error: cantReach
          ? `ไม่สามารถเชื่อมต่อ RAG backend ได้ — ตรวจสอบว่า Python server รันอยู่ที่ ${RAG_API}`
          : `Ingest error: ${err.message}`,
      },
      { status: 500 },
    );
  }
}

// ── DELETE /api/ingest?documentId=xxx ──────────────────────────────────────
export async function DELETE(request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user)
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(request.url);
  const documentId = searchParams.get("documentId");
  if (!documentId) {
    return NextResponse.json({ error: "documentId required" }, { status: 400 });
  }

  // ── ตรวจว่า doc นี้เป็นของ teacher คนนี้ (RLS ช่วยกรองอยู่แล้ว) ──────────
  const { data: doc, error: fetchError } = await supabase
    .from("knowledge_documents")
    .select("id, storage_path, qdrant_collection")
    .eq("id", documentId)
    .single();

  if (fetchError || !doc) {
    return NextResponse.json({ error: "Document not found" }, { status: 404 });
  }

  // ── 1. ลบ Qdrant chunks (best-effort) ────────────────────────────────────
  try {
    const params = new URLSearchParams({
      collection_name: doc.qdrant_collection,
      document_id: doc.id,
    });
    await fetch(`${RAG_API}/documents/chunks?${params}`, {
      method: "DELETE",
      signal: AbortSignal.timeout(15_000),
    });
  } catch (err) {
    console.warn("[ingest DELETE] Qdrant cleanup failed:", err.message);
  }

  // ── 2. ลบ Storage file (best-effort) ─────────────────────────────────────
  const serviceClient = createServiceClient();
  try {
    await serviceClient.storage
      .from("knowledge-files")
      .remove([doc.storage_path]);
  } catch (err) {
    console.warn("[ingest DELETE] Storage cleanup failed:", err.message);
  }

  // ── 3. ลบ DB record ───────────────────────────────────────────────────────
  const { error: deleteError } = await supabase
    .from("knowledge_documents")
    .delete()
    .eq("id", documentId);

  if (deleteError) {
    return NextResponse.json({ error: deleteError.message }, { status: 500 });
  }

  return NextResponse.json({ success: true });
}
