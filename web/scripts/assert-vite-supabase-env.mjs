#!/usr/bin/env node
/**
 * Fail closed when Vite would bake an empty Supabase client into the bundle.
 * A successful production deploy without these vars takes login offline.
 */
const url = String(process.env.VITE_SUPABASE_URL || '').trim()
const key = String(process.env.VITE_SUPABASE_ANON_KEY || '').trim()

if (!url || !key) {
  console.error(
    'Refusing to build: VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY must both be set.',
  )
  process.exit(1)
}

if (!/supabase\.co/i.test(url)) {
  console.error('Refusing to build: VITE_SUPABASE_URL does not look like a supabase.co URL.')
  process.exit(1)
}

console.log('Vite Supabase env present; continuing build.')
