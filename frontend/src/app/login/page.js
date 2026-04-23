"use client";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";

const ALLOWED_DOMAINS = ["gmail.com", "up.ac.th"];

function getEmailDomain(email) {
  return email.split("@")[1]?.toLowerCase() ?? "";
}

function isAllowedEmail(email) {
  return ALLOWED_DOMAINS.includes(getEmailDomain(email));
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("student");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Real-time domain hint — only shown in signup after user has typed "@"
  const showDomainWarning =
    mode === "signup" && email.includes("@") && !isAllowedEmail(email);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError("");

    // ── SIGN-UP ──────────────────────────────────────────────────────────
    if (mode === "signup") {
      // Frontend domain guard (backend validates too)
      if (!isAllowedEmail(email)) {
        setError("อนุญาตเฉพาะอีเมล @gmail.com และ @up.ac.th เท่านั้น");
        setLoading(false);
        return;
      }

      // Call server-side route that uses admin API with email_confirm: true
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, name, role }),
      });

      const json = await res.json();

      if (!res.ok) {
        setError(json.error ?? "เกิดข้อผิดพลาด กรุณาลองใหม่");
        setLoading(false);
        return;
      }

      // Auto-login immediately after successful registration
      const supabase = createClient();
      const { data: signInData, error: signInError } =
        await supabase.auth.signInWithPassword({ email, password });

      if (signInError) {
        // Account created but auto-login failed — ask user to sign in manually
        setError(
          "สมัครสมาชิกสำเร็จ! กรุณาเข้าสู่ระบบด้วยอีเมลและรหัสผ่านของคุณ",
        );
        setMode("signin");
        setLoading(false);
        return;
      }

      const { data: profile } = await supabase
        .from("profiles")
        .select("role")
        .eq("id", signInData.user.id)
        .single();

      router.push(profile?.role === "teacher" ? "/teacher" : "/student");
      router.refresh();
      return;
    }

    // ── SIGN-IN ──────────────────────────────────────────────────────────
    const supabase = createClient();
    const { data, error: signInError } = await supabase.auth.signInWithPassword(
      { email, password },
    );

    if (signInError) {
      setError(signInError.message);
    } else {
      const { data: profile } = await supabase
        .from("profiles")
        .select("role")
        .eq("id", data.user.id)
        .single();
      router.push(profile?.role === "teacher" ? "/teacher" : "/student");
      router.refresh();
    }

    setLoading(false);
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 w-full max-w-sm">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-gray-900">🎓 RAG Grading</h1>
          <p className="text-sm text-gray-500 mt-1">ระบบตรวจงานด้วย AI</p>
        </div>

        {/* Mode Toggle */}
        <div className="flex bg-gray-100 rounded-lg p-1 mb-6">
          <button
            onClick={() => {
              setMode("signin");
              setError("");
            }}
            className={`flex-1 text-sm py-2 rounded-md transition-all ${
              mode === "signin"
                ? "bg-white shadow-sm font-medium text-gray-900"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            เข้าสู่ระบบ
          </button>
          <button
            onClick={() => {
              setMode("signup");
              setError("");
            }}
            className={`flex-1 text-sm py-2 rounded-md transition-all ${
              mode === "signup"
                ? "bg-white shadow-sm font-medium text-gray-900"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            สมัครสมาชิก
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Signup-only fields */}
          {mode === "signup" && (
            <>
              <input
                required
                type="text"
                placeholder="ชื่อ-นามสกุล"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />

              {/* Role Selector */}
              <div>
                <p className="text-xs text-gray-500 mb-2">สมัครในฐานะ</p>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setRole("student")}
                    className={`py-2.5 px-3 rounded-lg border text-sm font-medium transition-all ${
                      role === "student"
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700"
                    }`}
                  >
                    🎒 นักเรียน
                  </button>
                  <button
                    type="button"
                    onClick={() => setRole("teacher")}
                    className={`py-2.5 px-3 rounded-lg border text-sm font-medium transition-all ${
                      role === "teacher"
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700"
                    }`}
                  >
                    👩‍🏫 อาจารย์
                  </button>
                </div>
              </div>
            </>
          )}

          <div>
            <input
              required
              type="email"
              placeholder="อีเมล (@gmail.com หรือ @up.ac.th)"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError("");
              }}
              className={`w-full border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                showDomainWarning
                  ? "border-amber-400 bg-amber-50"
                  : "border-gray-300"
              }`}
            />
            {showDomainWarning && (
              <p className="text-amber-600 text-xs mt-1 pl-1">
                ⚠️ อนุญาตเฉพาะ @gmail.com และ @up.ac.th เท่านั้น
              </p>
            )}
          </div>

          <input
            required
            type="password"
            placeholder="รหัสผ่าน (อย่างน้อย 6 ตัวอักษร)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />

          {/* Allowed domains hint */}
          {mode === "signup" && (
            <p className="text-xs text-gray-400 pl-1">
              ✉️ รับอีเมล:{" "}
              <span className="font-medium text-gray-500">@gmail.com</span> และ{" "}
              <span className="font-medium text-gray-500">@up.ac.th</span>{" "}
              เท่านั้น
            </p>
          )}

          {error && (
            <p className="text-red-500 text-sm bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium disabled:opacity-50 transition-colors mt-1"
          >
            {loading
              ? "กำลังดำเนินการ..."
              : mode === "signin"
                ? "เข้าสู่ระบบ"
                : `สมัครสมาชิกในฐานะ${role === "teacher" ? "อาจารย์" : "นักเรียน"}`}
          </button>
        </form>
      </div>
    </div>
  );
}
