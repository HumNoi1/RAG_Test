'use client'
import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'
import Link from 'next/link'

export default function TeacherPage() {
  const router = useRouter()
  const [profile, setProfile] = useState(null)
  const [courses, setCourses] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ code: '', name: '', term: '' })
  const [loading, setLoading] = useState(false)
  const [pageLoading, setPageLoading] = useState(true)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return router.push('/login')

    const [{ data: prof }, { data: c }] = await Promise.all([
      supabase.from('profiles').select('role, full_name, email').eq('id', user.id).single(),
      supabase.from('courses').select('id, code, name, term, created_at').order('created_at', { ascending: false }),
    ])

    if (prof?.role !== 'teacher') return router.push('/student')
    setProfile(prof)
    setCourses(c ?? [])
    setPageLoading(false)
  }

  async function createCourse(e) {
    e.preventDefault()
    setLoading(true)
    const supabase = createClient()
    const { data, error } = await supabase
      .from('courses')
      .insert({ code: form.code, name: form.name, term: form.term || null })
      .select()
      .single()

    if (error) {
      alert(error.message)
    } else {
      setCourses([data, ...courses])
      setShowForm(false)
      setForm({ code: '', name: '', term: '' })
    }
    setLoading(false)
  }

  async function logout() {
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
  }

  if (pageLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-gray-400">
        กำลังโหลด...
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">🎓 RAG Grading</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            สวัสดี, {profile?.full_name || profile?.email}
          </p>
        </div>
        <button
          onClick={logout}
          className="text-sm text-gray-500 hover:text-gray-800 underline"
        >
          ออกจากระบบ
        </button>
      </div>

      {/* Section header */}
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold text-gray-800">
          วิชาของฉัน ({courses.length})
        </h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg transition-colors"
        >
          + สร้างวิชา
        </button>
      </div>

      {/* Create course form */}
      {showForm && (
        <form
          onSubmit={createCourse}
          className="bg-white rounded-xl border border-gray-200 p-5 mb-4 space-y-3"
        >
          <h3 className="font-medium text-gray-800">สร้างวิชาใหม่</h3>
          <input
            required
            placeholder="รหัสวิชา เช่น CS101"
            value={form.code}
            onChange={e => setForm({ ...form, code: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            required
            placeholder="ชื่อวิชา เช่น Introduction to AI"
            value={form.name}
            onChange={e => setForm({ ...form, name: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            placeholder="เทอม เช่น 1/2567 (ไม่บังคับ)"
            value={form.term}
            onChange={e => setForm({ ...form, term: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={loading}
              className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-50 transition-colors"
            >
              {loading ? 'กำลังสร้าง...' : 'สร้างวิชา'}
            </button>
            <button
              type="button"
              onClick={() => { setShowForm(false); setForm({ code: '', name: '', term: '' }) }}
              className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2 rounded-lg hover:bg-gray-100 transition-colors"
            >
              ยกเลิก
            </button>
          </div>
        </form>
      )}

      {/* Courses list */}
      <div className="space-y-3">
        {courses.length === 0 ? (
          <div className="bg-white rounded-xl border border-dashed border-gray-300 p-10 text-center">
            <p className="text-gray-400 text-sm">ยังไม่มีวิชา</p>
            <p className="text-gray-300 text-xs mt-1">กด &quot;สร้างวิชา&quot; เพื่อเริ่มต้น</p>
          </div>
        ) : (
          courses.map(c => (
            <Link
              key={c.id}
              href={`/teacher/courses/${c.id}`}
              className="block bg-white rounded-xl border border-gray-200 p-4 hover:shadow-md hover:border-blue-300 transition-all"
            >
              <div className="flex justify-between items-center">
                <div>
                  <p className="font-semibold text-gray-900">
                    {c.code} — {c.name}
                  </p>
                  <p className="text-sm text-gray-400 mt-0.5">
                    {c.term || 'ไม่ระบุเทอม'}
                  </p>
                </div>
                <span className="text-blue-500 text-sm">ดูรายละเอียด →</span>
              </div>
            </Link>
          ))
        )}
      </div>
    </div>
  )
}
