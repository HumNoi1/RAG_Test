'use client'
import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'

const STATUS_COLOR = {
  approved: 'bg-green-100 text-green-700',
  overridden: 'bg-purple-100 text-purple-700',
}

export default function StudentPage() {
  const router = useRouter()
  const [profile, setProfile] = useState(null)
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return router.push('/login')

    const { data: prof } = await supabase
      .from('profiles')
      .select('role, full_name, email')
      .eq('id', user.id)
      .single()

    if (prof?.role === 'teacher') return router.push('/teacher')
    setProfile(prof)

    const { data: res } = await supabase
      .from('student_results')
      .select('*')
      .order('published_at', { ascending: false })

    setResults(res ?? [])
    setLoading(false)
  }

  async function logout() {
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
  }

  if (loading) {
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
          <h1 className="text-2xl font-bold text-gray-900">🎓 ผลการเรียน</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {profile?.full_name || profile?.email}
          </p>
        </div>
        <button
          onClick={logout}
          className="text-sm text-gray-500 hover:text-gray-800 underline"
        >
          ออกจากระบบ
        </button>
      </div>

      {/* Results */}
      {results.length === 0 ? (
        <div className="bg-white rounded-xl border p-10 text-center">
          <p className="text-gray-400 text-sm">ยังไม่มีผลการตรวจงาน</p>
          <p className="text-gray-300 text-xs mt-1">
            ผลจะแสดงเมื่ออาจารย์อนุมัติคะแนนแล้ว
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {results.map((r) => (
            <div
              key={r.submission_id}
              className="bg-white rounded-xl border p-5 hover:shadow-sm transition-shadow"
            >
              <div className="flex justify-between items-start mb-3">
                <div>
                  <p className="font-semibold text-gray-900">{r.assignment_title}</p>
                  <p className="text-sm text-gray-500 mt-0.5">
                    {r.course_code} — {r.course_name}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold text-blue-600">
                    {Number(r.final_total_score).toFixed(1)}
                  </p>
                  <p className="text-xs text-gray-400">คะแนน</p>
                </div>
              </div>

              {r.final_reason && (
                <div className="bg-gray-50 rounded-lg px-4 py-3 mt-2">
                  <p className="text-sm text-gray-700 leading-relaxed">
                    {r.final_reason}
                  </p>
                </div>
              )}

              <p className="text-xs text-gray-400 mt-3">
                ประกาศผล{' '}
                {new Date(r.published_at).toLocaleDateString('th-TH', {
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric',
                })}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
