import { createClient, type User } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey)

export const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl as string, supabaseAnonKey as string)
  : null

export function userDisplayName(user: User | null) {
  if (!user) return ''
  const name = user.user_metadata?.name
  return typeof name === 'string' && name.trim() ? name.trim() : user.email?.split('@')[0] ?? '사용자'
}
