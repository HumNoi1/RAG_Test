"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

const INGEST_STATUS_COLOR = {
  pending: "bg-gray-100 text-gray-600",
  processing: "bg-yellow-100 text-yellow-700",
  ready: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

const INGEST_STATUS_LABEL = {
  pending: "รอดำเนินการ",
  processing: "กำลัง ingest...",
  ready: "พร้อมใช้งาน",
  failed: "ล้มเหลว",
};

const STATUS_SORT_ORDER = { ready: 0, processing: 1, pending: 2, failed: 3 };

export default function CoursePage() {
  const params = useParams();
  const courseId = params.courseId;
  const router = useRouter();

  const [course, setCourse] = useState(null);
  const [docs, setDocs] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);

  // Knowledge file upload
  const [showDocForm, setShowDocForm] = useState(false);
  const [docFile, setDocFile] = useState(null);
  const [docTitle, setDocTitle] = useState("");
  const [docLoading, setDocLoading] = useState(false);
  const [docError, setDocError] = useState("");

  // Doc delete
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [deletingDocId, setDeletingDocId] = useState(null);
  const [docDeleteError, setDocDeleteError] = useState("");

  // Assignment creation
  const [showAssignForm, setShowAssignForm] = useState(false);
  const [assignForm, setAssignForm] = useState({ title: "", description: "" });
  const [rubric, setRubric] = useState([
    { criterion_name: "", description: "", max_score: "" },
  ]);
  const [assignLoading, setAssignLoading] = useState(false);
  const [assignError, setAssignError] = useState("");

  // Student enrollment
  const [showEnrollForm, setShowEnrollForm] = useState(false);
  const [enrollEmail, setEnrollEmail] = useState("");
  const [enrollLoading, setEnrollLoading] = useState(false);
  const [enrollError, setEnrollError] = useState("");
  const [enrollMessage, setEnrollMessage] = useState("");

  useEffect(() => {
    loadAll();
  }, [courseId]);

  async function loadAll() {
    const supabase = createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return router.push("/login");

    const [courseRes, docsRes, assignRes, studentsRes] = await Promise.all([
      supabase.from("courses").select("*").eq("id", courseId).single(),
      supabase
        .from("knowledge_documents")
        .select("*")
        .eq("course_id", courseId)
        .order("created_at", { ascending: false }),
      supabase
        .from("assignments")
        .select("id, title, status, max_score, created_at")
        .eq("course_id", courseId)
        .order("created_at", { ascending: false }),
      supabase
        .from("course_students")
        .select("student_id, profiles(id, full_name, email)")
        .eq("course_id", courseId),
    ]);

    if (!courseRes.data) return router.push("/teacher");
    setCourse(courseRes.data);
    setDocs(docsRes.data ?? []);
    setAssignments(assignRes.data ?? []);
    setStudents(studentsRes.data?.map((s) => s.profiles).filter(Boolean) ?? []);
    setLoading(false);
  }

  // --- Upload knowledge file ---
  async function uploadDoc(e) {
    e.preventDefault();
    if (!docFile) return;
    setDocLoading(true);
    setDocError("");

    const form = new FormData();
    form.append("file", docFile);
    form.append("courseId", courseId);
    form.append("documentTitle", docTitle || docFile.name);

    const res = await fetch("/api/ingest", { method: "POST", body: form });
    const data = await res.json();

    if (!res.ok) {
      setDocError(data.error ?? "เกิดข้อผิดพลาด");
    } else {
      setShowDocForm(false);
      setDocFile(null);
      setDocTitle("");
      await loadAll();
    }
    setDocLoading(false);
  }

  // --- Delete knowledge file ---
  async function deleteDoc(docId) {
    setDeletingDocId(docId);
    setDocDeleteError("");

    const res = await fetch(`/api/ingest?documentId=${docId}`, {
      method: "DELETE",
    });
    const data = await res.json();

    setDeletingDocId(null);
    setConfirmDeleteId(null);

    if (!res.ok) {
      setDocDeleteError(data.error ?? "ลบไม่สำเร็จ");
    } else {
      await loadAll();
    }
  }

  // --- Create assignment with rubric ---
  async function createAssignment(e) {
    e.preventDefault();
    setAssignLoading(true);
    setAssignError("");

    const validRubric = rubric.filter(
      (r) => r.criterion_name.trim() && Number(r.max_score) > 0,
    );
    if (validRubric.length === 0) {
      setAssignError("เพิ่มเกณฑ์การตรวจ (Rubric) อย่างน้อย 1 รายการ");
      setAssignLoading(false);
      return;
    }

    const totalScore = validRubric.reduce(
      (sum, r) => sum + Number(r.max_score),
      0,
    );
    const supabase = createClient();

    const { data: assignment, error: assignErr } = await supabase
      .from("assignments")
      .insert({
        course_id: courseId,
        title: assignForm.title,
        description: assignForm.description,
        max_score: totalScore,
      })
      .select()
      .single();

    if (assignErr) {
      setAssignError(assignErr.message);
      setAssignLoading(false);
      return;
    }

    const { error: rubricErr } = await supabase
      .from("assignment_rubrics")
      .insert(
        validRubric.map((r, i) => ({
          assignment_id: assignment.id,
          criterion_name: r.criterion_name.trim(),
          description: r.description.trim(),
          max_score: Number(r.max_score),
          sort_order: i,
        })),
      );

    if (rubricErr) {
      setAssignError(rubricErr.message);
    } else {
      setShowAssignForm(false);
      setAssignForm({ title: "", description: "" });
      setRubric([{ criterion_name: "", description: "", max_score: "" }]);
      await loadAll();
    }
    setAssignLoading(false);
  }

  function addRubricRow() {
    setRubric([
      ...rubric,
      { criterion_name: "", description: "", max_score: "" },
    ]);
  }

  function removeRubricRow(idx) {
    if (rubric.length <= 1) return;
    setRubric(rubric.filter((_, i) => i !== idx));
  }

  function updateRubricRow(idx, field, value) {
    setRubric(rubric.map((r, i) => (i === idx ? { ...r, [field]: value } : r)));
  }

  // --- Enroll student ---
  async function enrollStudent(e) {
    e.preventDefault();
    setEnrollLoading(true);
    setEnrollError("");
    setEnrollMessage("");

    const res = await fetch("/api/enroll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: enrollEmail, courseId }),
    });
    const data = await res.json();

    if (!res.ok) {
      setEnrollError(data.error ?? "เกิดข้อผิดพลาด");
    } else {
      setEnrollMessage(data.message ?? `เพิ่ม ${enrollEmail} สำเร็จ`);
      setEnrollEmail("");
      await loadAll();
    }
    setEnrollLoading(false);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-gray-400">
        กำลังโหลด...
      </div>
    );
  }

  const totalRubricScore = rubric.reduce(
    (sum, r) => sum + (Number(r.max_score) || 0),
    0,
  );
  const readyDocs = docs.filter((d) => d.ingest_status === "ready");
  const sortedDocs = [...docs].sort(
    (a, b) =>
      (STATUS_SORT_ORDER[a.ingest_status] ?? 9) -
      (STATUS_SORT_ORDER[b.ingest_status] ?? 9),
  );

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <Link
          href="/teacher"
          className="text-gray-400 hover:text-gray-700 text-sm"
        >
          ← กลับ
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {course.code} — {course.name}
          </h1>
          {course.term && (
            <p className="text-sm text-gray-500">{course.term}</p>
          )}
        </div>
      </div>

      {/* ==================== KNOWLEDGE FILES ==================== */}
      <section className="mb-10">
        <div className="flex justify-between items-center mb-3">
          <h2 className="text-lg font-semibold text-gray-900">
            📄 เอกสารความรู้
            {docs.length > 0 && (
              <span className="ml-2 text-sm font-normal text-gray-400">
                {readyDocs.length} พร้อมใช้งาน
                {docs.length !== readyDocs.length &&
                  ` / ${docs.length} ทั้งหมด`}
              </span>
            )}
          </h2>
          <button
            onClick={() => {
              setShowDocForm(!showDocForm);
              setDocError("");
            }}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg"
          >
            + อัปโหลดไฟล์
          </button>
        </div>

        {showDocForm && (
          <form
            onSubmit={uploadDoc}
            className="bg-white rounded-xl border p-5 mb-4 space-y-3"
          >
            <h3 className="font-medium text-gray-800">อัปโหลดเอกสารความรู้</h3>
            <input
              type="file"
              required
              accept=".txt,.pdf,.docx"
              onChange={(e) => {
                setDocFile(e.target.files[0]);
                if (!docTitle) setDocTitle(e.target.files[0]?.name ?? "");
              }}
              className="w-full text-sm text-gray-600 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
            <input
              type="text"
              placeholder="ชื่อเอกสาร (ไม่บังคับ)"
              value={docTitle}
              onChange={(e) => setDocTitle(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {docError && <p className="text-red-500 text-sm">{docError}</p>}
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={docLoading}
                className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-50"
              >
                {docLoading ? "กำลัง ingest..." : "อัปโหลด"}
              </button>
              <button
                type="button"
                onClick={() => setShowDocForm(false)}
                className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2"
              >
                ยกเลิก
              </button>
            </div>
          </form>
        )}

        {docDeleteError && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 mb-3 text-sm text-red-600">
            {docDeleteError}
          </div>
        )}

        {docs.length === 0 ? (
          <p className="text-gray-400 text-sm py-4">
            ยังไม่มีเอกสาร กด &quot;อัปโหลดไฟล์&quot; เพื่อเพิ่มความรู้ให้ระบบ
          </p>
        ) : (
          <div className="space-y-2">
            {sortedDocs.map((doc) => (
              <div
                key={doc.id}
                className={`bg-white rounded-lg border px-4 py-3 flex justify-between items-start gap-3 ${
                  doc.ingest_status === "failed"
                    ? "border-red-200 bg-red-50/40"
                    : ""
                }`}
              >
                {/* Left: title + filename + error */}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {doc.title}
                  </p>
                  <p className="text-xs text-gray-400 truncate">
                    {doc.original_filename}
                  </p>
                  {doc.ingest_status === "failed" && doc.ingest_error && (
                    <p
                      className="text-xs text-red-500 mt-1 truncate"
                      title={doc.ingest_error}
                    >
                      ⚠ {doc.ingest_error}
                    </p>
                  )}
                </div>

                {/* Right: chunks + status badge + delete */}
                <div className="flex items-center gap-2 shrink-0">
                  {doc.chunks_stored > 0 && (
                    <span className="text-xs text-gray-400 hidden sm:inline">
                      {doc.chunks_stored} chunks
                    </span>
                  )}
                  <span
                    className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                      INGEST_STATUS_COLOR[doc.ingest_status] ??
                      "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {INGEST_STATUS_LABEL[doc.ingest_status] ??
                      doc.ingest_status}
                  </span>

                  {/* Inline delete confirm */}
                  {confirmDeleteId === doc.id ? (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => deleteDoc(doc.id)}
                        disabled={deletingDocId === doc.id}
                        className="text-xs bg-red-600 hover:bg-red-700 text-white px-2.5 py-1 rounded-md disabled:opacity-50 transition-colors"
                      >
                        {deletingDocId === doc.id ? "..." : "ยืนยันลบ"}
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="text-xs text-gray-400 hover:text-gray-700 px-1.5 py-1"
                      >
                        ยกเลิก
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => {
                        setConfirmDeleteId(doc.id);
                        setDocDeleteError("");
                      }}
                      disabled={deletingDocId === doc.id}
                      className="text-gray-300 hover:text-red-500 disabled:opacity-30 transition-colors px-1 text-base leading-none"
                      title="ลบเอกสาร"
                    >
                      🗑
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ==================== ASSIGNMENTS ==================== */}
      <section className="mb-10">
        <div className="flex justify-between items-center mb-3">
          <h2 className="text-lg font-semibold text-gray-900">
            📝 งาน ({assignments.length})
          </h2>
          <button
            onClick={() => {
              setShowAssignForm(!showAssignForm);
              setAssignError("");
            }}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg"
          >
            + สร้างงาน
          </button>
        </div>

        {showAssignForm && (
          <form
            onSubmit={createAssignment}
            className="bg-white rounded-xl border p-5 mb-4 space-y-4"
          >
            <h3 className="font-medium text-gray-800">สร้างงานใหม่</h3>

            <input
              required
              placeholder="ชื่องาน"
              value={assignForm.title}
              onChange={(e) =>
                setAssignForm({ ...assignForm, title: e.target.value })
              }
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <textarea
              placeholder="คำอธิบายงาน / คำสั่ง (ไม่บังคับ)"
              value={assignForm.description}
              onChange={(e) =>
                setAssignForm({ ...assignForm, description: e.target.value })
              }
              rows={2}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />

            {/* Rubric Builder */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <p className="text-sm font-medium text-gray-700">
                  เกณฑ์การตรวจ (Rubric)
                  {totalRubricScore > 0 && (
                    <span className="ml-2 text-blue-600">
                      คะแนนรวม: {totalRubricScore}
                    </span>
                  )}
                </p>
                <button
                  type="button"
                  onClick={addRubricRow}
                  className="text-xs text-blue-600 hover:text-blue-800"
                >
                  + เพิ่มเกณฑ์
                </button>
              </div>

              <div className="space-y-2">
                {rubric.map((r, idx) => (
                  <div key={idx} className="flex gap-2 items-start">
                    <input
                      required
                      placeholder="ชื่อเกณฑ์ เช่น ความถูกต้อง"
                      value={r.criterion_name}
                      onChange={(e) =>
                        updateRubricRow(idx, "criterion_name", e.target.value)
                      }
                      className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <input
                      placeholder="คำอธิบาย"
                      value={r.description}
                      onChange={(e) =>
                        updateRubricRow(idx, "description", e.target.value)
                      }
                      className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <input
                      required
                      type="number"
                      min="0.01"
                      step="0.01"
                      placeholder="คะแนน"
                      value={r.max_score}
                      onChange={(e) =>
                        updateRubricRow(idx, "max_score", e.target.value)
                      }
                      className="w-24 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <button
                      type="button"
                      onClick={() => removeRubricRow(idx)}
                      disabled={rubric.length <= 1}
                      className="text-gray-400 hover:text-red-500 disabled:opacity-30 px-1 py-2 text-lg leading-none"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </div>

            {assignError && (
              <p className="text-red-500 text-sm">{assignError}</p>
            )}

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={assignLoading}
                className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-50"
              >
                {assignLoading ? "กำลังสร้าง..." : "สร้างงาน"}
              </button>
              <button
                type="button"
                onClick={() => setShowAssignForm(false)}
                className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2"
              >
                ยกเลิก
              </button>
            </div>
          </form>
        )}

        {assignments.length === 0 ? (
          <p className="text-gray-400 text-sm py-4">
            ยังไม่มีงาน กด &quot;สร้างงาน&quot; เพื่อเริ่มต้น
          </p>
        ) : (
          <div className="space-y-2">
            {assignments.map((a) => (
              <Link
                key={a.id}
                href={`/teacher/assignments/${a.id}`}
                className="flex justify-between items-center bg-white rounded-lg border px-4 py-3 hover:shadow-sm hover:border-blue-300 transition-all"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">{a.title}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    คะแนนรวม {Number(a.max_score).toFixed(0)} คะแนน
                  </p>
                </div>
                <span className="text-blue-500 text-sm">จัดการ →</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* ==================== STUDENTS ==================== */}
      <section>
        <div className="flex justify-between items-center mb-3">
          <h2 className="text-lg font-semibold text-gray-900">
            👥 นักเรียน ({students.length})
          </h2>
          <button
            onClick={() => {
              setShowEnrollForm(!showEnrollForm);
              setEnrollError("");
              setEnrollMessage("");
            }}
            className="bg-gray-700 hover:bg-gray-900 text-white text-sm px-4 py-2 rounded-lg"
          >
            + เพิ่มนักเรียน
          </button>
        </div>

        {showEnrollForm && (
          <form
            onSubmit={enrollStudent}
            className="bg-white rounded-xl border p-5 mb-4 space-y-3"
          >
            <h3 className="font-medium text-gray-800">เพิ่มนักเรียนเข้าวิชา</h3>
            <p className="text-xs text-gray-400">
              นักเรียนต้องสมัครสมาชิกในระบบก่อน
            </p>
            <div className="flex gap-2">
              <input
                required
                type="email"
                placeholder="อีเมลนักเรียน"
                value={enrollEmail}
                onChange={(e) => setEnrollEmail(e.target.value)}
                className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                type="submit"
                disabled={enrollLoading}
                className="bg-gray-700 hover:bg-gray-900 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-50"
              >
                {enrollLoading ? "กำลังเพิ่ม..." : "เพิ่ม"}
              </button>
            </div>
            {enrollError && (
              <p className="text-red-500 text-sm">{enrollError}</p>
            )}
            {enrollMessage && (
              <p className="text-green-600 text-sm">{enrollMessage}</p>
            )}
          </form>
        )}

        {students.length === 0 ? (
          <p className="text-gray-400 text-sm py-4">
            ยังไม่มีนักเรียนในวิชานี้
          </p>
        ) : (
          <div className="space-y-2">
            {students.map((s) => (
              <div
                key={s.id}
                className="bg-white rounded-lg border px-4 py-3 flex justify-between items-center"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">
                    {s.full_name || "(ไม่มีชื่อ)"}
                  </p>
                  <p className="text-xs text-gray-400">{s.email}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
