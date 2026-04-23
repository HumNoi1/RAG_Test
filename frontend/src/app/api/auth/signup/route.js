import { createServiceClient } from "@/lib/supabase/service";
import { NextResponse } from "next/server";

const ALLOWED_DOMAINS = ["gmail.com", "up.ac.th"];

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  const { email, password, name, role } = body;

  // --- Basic field validation ---
  if (!email || !password || !name || !role) {
    return NextResponse.json(
      { error: "กรุณากรอกข้อมูลให้ครบถ้วน" },
      { status: 400 }
    );
  }

  if (!["student", "teacher"].includes(role)) {
    return NextResponse.json({ error: "Role ไม่ถูกต้อง" }, { status: 400 });
  }

  if (password.length < 6) {
    return NextResponse.json(
      { error: "รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร" },
      { status: 400 }
    );
  }

  // --- Domain validation ---
  const emailDomain = email.split("@")[1]?.toLowerCase();
  if (!emailDomain || !ALLOWED_DOMAINS.includes(emailDomain)) {
    return NextResponse.json(
      {
        error: `อนุญาตเฉพาะอีเมล @gmail.com และ @up.ac.th เท่านั้น`,
      },
      { status: 400 }
    );
  }

  // --- Create user via admin API (email_confirm: true skips confirmation email) ---
  const supabase = createServiceClient();

  const { data, error } = await supabase.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
    user_metadata: { full_name: name, role },
  });

  if (error) {
    // Surface a friendly message for duplicate email
    if (
      error.message?.toLowerCase().includes("already") ||
      error.message?.toLowerCase().includes("duplicate") ||
      error.status === 422
    ) {
      return NextResponse.json(
        { error: "อีเมลนี้ถูกใช้งานแล้ว กรุณาใช้อีเมลอื่น" },
        { status: 409 }
      );
    }
    return NextResponse.json({ error: error.message }, { status: 400 });
  }

  return NextResponse.json(
    { message: "สมัครสมาชิกสำเร็จ", userId: data.user.id },
    { status: 201 }
  );
}
