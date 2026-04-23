import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createServiceClient } from '@/lib/supabase/service'

export async function POST(request) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { email, courseId } = await request.json()
  if (!email || !courseId) {
    return NextResponse.json({ error: 'email and courseId are required' }, { status: 400 })
  }

  // Use service role to find the student profile by email (bypasses RLS)
  const serviceClient = createServiceClient()
  const { data: student, error: lookupError } = await serviceClient
    .from('profiles')
    .select('id, full_name, email')
    .eq('email', email)
    .single()

  if (lookupError || !student) {
    return NextResponse.json(
      { error: `ไม่พบผู้ใช้ที่มีอีเมล ${email} กรุณาให้นักเรียนสมัครสมาชิกก่อน` },
      { status: 404 }
    )
  }

  // Enroll student into the course using the authenticated teacher's client
  const { error: enrollError } = await supabase
    .from('course_students')
    .insert({ course_id: courseId, student_id: student.id })

  if (enrollError) {
    // Ignore duplicate enrollment
    if (enrollError.code === '23505') {
      return NextResponse.json({ message: 'นักเรียนเข้าร่วมวิชานี้อยู่แล้ว', student })
    }
    return NextResponse.json({ error: enrollError.message }, { status: 500 })
  }

  return NextResponse.json({ success: true, student })
}
