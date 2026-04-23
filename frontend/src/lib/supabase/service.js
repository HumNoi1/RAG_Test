import { createClient } from '@supabase/supabase-js'

// ⚠️ Server-side only — ห้าม import จาก Client Components เด็ดขาด!
export function createServiceClient() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
  )
}
