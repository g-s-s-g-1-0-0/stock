# Supabase 서비스 설정

## 1. 프로젝트 생성

Supabase에서 새 프로젝트를 만든 뒤 `Project Settings > API`에서 아래 값을 확인합니다.

- Project URL
- anon public key

확인한 값은 `web/.env`에 입력합니다.

```bash
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
```

## 2. DB 스키마 적용

Supabase SQL Editor에서 `supabase/migrations/001_initial_service_schema.sql` 내용을 실행합니다.

관리자 계정은 회원가입과 이메일 인증을 마친 뒤 아래 SQL로 지정합니다.

```sql
update public.profiles
set is_admin = true
where email = 'admin@example.com';
```

프론트의 관리자 메뉴 노출 기준도 `web/.env`의 `VITE_ADMIN_EMAILS`에 같은 이메일을 넣어 맞춥니다.

## 3. 이메일 인증 설정

`Authentication > URL Configuration`에서 Site URL과 Redirect URL을 서비스 주소로 설정합니다.
로컬 개발 중에는 `http://localhost:5173`을 추가합니다.

Supabase 기본 메일러는 테스트 용도 제한이 있으므로, 공개 서비스 전에는 `Authentication > SMTP Settings`에서 커스텀 SMTP를 연결하는 것을 권장합니다.
