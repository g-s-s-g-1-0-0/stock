// KOFIA securities member directory, checked 2026-11-08.
// https://www.kofia.or.kr/members/m_60/sub020201.do?srchCate=4
export const brokerages = [
  'DB증권',
  'DS투자증권',
  'KB증권',
  'NH투자증권',
  '골드만삭스증권 서울지점',
  '교보증권',
  '나틱시스증권 서울지점',
  '넥스트증권',
  '노무라금융투자',
  '다올투자증권',
  '다이와증권캐피탈마켓코리아',
  '대신증권',
  '도이치증권',
  '리딩투자증권',
  '맥쿼리증권',
  '메리츠증권',
  '메릴린치인터내셔날엘엘씨증권 서울지점',
  '모간스탠리인터내셔날증권 서울지점',
  '미래에셋증권',
  '미즈호증권 아시아 서울지점',
  '부국증권',
  '비엔케이투자증권',
  '비엔피파리바증권',
  '삼성증권',
  '상상인증권',
  '신영증권',
  '신한투자증권',
  '씨엠에스증권 한국',
  '씨지에스 인터내셔널증권 홍콩 한국지점',
  '씨티그룹글로벌마켓증권',
  '씨틱코리아증권',
  '아이비케이투자증권',
  '아이엔지증권 서울지점',
  '아이엠증권',
  '에스케이증권',
  '엘에스증권',
  '우리투자증권',
  '유비에스증권리미티드 서울지점',
  '유안타증권',
  '유진투자증권',
  '유화증권',
  '제이피모간증권 서울지점',
  '카카오페이증권',
  '케이아이디비채권중개',
  '케이알투자증권',
  '케이프투자증권',
  '코리아에셋투자증권',
  '크레디 아그리콜 아시아 증권 서울지점',
  '키움증권',
  '토스증권',
  '하나증권',
  '한국스탠다드차타드증권',
  '한국아이엠씨증권',
  '한국에스지증권',
  '한국투자증권',
  '한양증권',
  '한화투자증권',
  '현대차증권',
  '홍콩상하이증권 서울지점',
  '흥국증권',
] as const

export const accountTypes = ['퇴직연금', 'IRP', 'ISA', '일반증권'] as const
export const buyTimings = {
  월초: '거래소 첫 거래일',
  중순: '15일 또는 이후 첫 거래일',
  월말: '거래소 마지막 거래일',
} as const

export type InvestmentAccount = {
  id: string
  nickname: string
  brokerage?: string
  accountNumber: string
  type: typeof accountTypes[number]
  initialCapital?: number
  frequency?: 'weekly' | 'monthly' | 'yearly'
  dayOfWeek?: number
  monthOfYear?: number
  dayOfMonth?: number
  collecting?: { ticker: string; percent: number }[]
  monthlyDeposit: number
  buyTiming: keyof typeof buyTimings
}

export function normalizeInvestmentAccounts(value: unknown): InvestmentAccount[] {
  if (!Array.isArray(value)) return []
  const ids = new Set<string>()
  return value.flatMap((row: Partial<InvestmentAccount> | null) => {
    if (!row || typeof row.id !== 'string' || !row.id || ids.has(row.id)
      || typeof row.nickname !== 'string' || !row.nickname.trim()
      || !row.type || !accountTypes.includes(row.type)
      || !row.buyTiming || !Object.hasOwn(buyTimings, row.buyTiming)
      || typeof row.monthlyDeposit !== 'number' || !Number.isSafeInteger(row.monthlyDeposit)
      || row.monthlyDeposit < 0) return []
    ids.add(row.id)
    return [{
      id: row.id,
      nickname: row.nickname.trim().slice(0, 40),
      brokerage: typeof row.brokerage === 'string' && brokerages.some((name) => name === row.brokerage) ? row.brokerage : '',
      accountNumber: typeof row.accountNumber === 'string' && /^[0-9-]{0,32}$/.test(row.accountNumber) ? row.accountNumber : '',
      type: row.type,
      initialCapital: Number.isSafeInteger(row.initialCapital) && row.initialCapital! >= 0 ? row.initialCapital : 0,
      frequency: row.frequency === 'weekly' ? 'weekly' : row.frequency === 'yearly' ? 'yearly' : 'monthly',
      dayOfWeek: Number.isInteger(row.dayOfWeek) && row.dayOfWeek! >= 0 && row.dayOfWeek! <= 6 ? row.dayOfWeek : 1,
      monthOfYear: Number.isInteger(row.monthOfYear) && row.monthOfYear! >= 1 && row.monthOfYear! <= 12 ? row.monthOfYear : 1,
      dayOfMonth: Number.isInteger(row.dayOfMonth) && row.dayOfMonth! >= 1 && row.dayOfMonth! <= 31 ? row.dayOfMonth : 1,
      collecting: Array.isArray(row.collecting) ? row.collecting.filter((item) =>
        item && typeof item.ticker === 'string' && /^[A-Z0-9.^=-]+$/.test(item.ticker)
        && Number.isInteger(item.percent) && item.percent > 0 && item.percent <= 100) : [],
      monthlyDeposit: row.monthlyDeposit,
      buyTiming: row.buyTiming,
    }]
  })
}
