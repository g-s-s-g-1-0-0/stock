import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addDays, buildUsageReport, seoulDate } from '../src/usageMetrics.ts'

test('seoul calendar date follows Asia/Seoul, not UTC', () => {
  assert.equal(seoulDate('2026-10-12T14:30:00.000Z'), '2026-10-12')
  assert.equal(seoulDate('2026-10-12T15:30:00.000Z'), '2026-10-13')
})

test('addDays stays on the calendar across month and leap-year boundaries', () => {
  assert.equal(addDays('2026-10-31', 1), '2026-11-01')
  assert.equal(addDays('2026-03-01', -1), '2026-02-28')
  assert.equal(addDays('2024-03-01', -1), '2024-02-29')
})

test('retention ignores admins and days before logging started', () => {
  const report = buildUsageReport({
    today: '2026-10-12',
    loggingStartedOn: '2026-10-10',
    excludeEmails: ['hidden@friend.test'],
    users: [
      { id: 'admin', email: 'admin@gongsu.local', name: '관리자', isAdmin: true, createdAt: '2026-10-01T00:00:00+09:00' },
      { id: 'hidden', email: 'Hidden@friend.test', name: '숨김', isAdmin: false, createdAt: '2026-10-11T00:00:00+09:00' },
      { id: 'early', email: 'early@friend.test', name: '일찍', isAdmin: false, createdAt: '2026-10-05T00:00:00+09:00' },
      { id: 'next', email: 'next@friend.test', name: '다음날', isAdmin: false, createdAt: '2026-10-11T00:00:00+09:00' },
      { id: 'new', email: 'new@friend.test', name: '', isAdmin: false, createdAt: '2026-10-12T00:00:00+09:00' },
    ],
    events: [
      { actorId: 'admin', page: 'home', occurredOn: '2026-10-12' },
      { actorId: 'hidden', page: 'home', occurredOn: '2026-10-12' },
      { actorId: 'early', page: 'home', occurredOn: '2026-10-12' },
      { actorId: 'early', page: 'home', occurredOn: '2026-10-12' },
      { actorId: 'early', page: 'technical-analysis', occurredOn: '2026-10-11' },
      { actorId: 'next', page: 'value-analysis', occurredOn: '2026-10-11' },
    ],
  })

  assert.equal(report.friendCount, 3)
  assert.equal(report.visitedToday, 1)
  assert.equal(report.visitedLast7Days, 2)
  assert.equal(report.neverVisited, 1)
  assert.deepEqual(report.retention.map((item) => [item.horizon, item.retained, item.eligible, item.rate]), [
    [1, 0, 1, 0],
    [7, 1, 1, 1],
    [30, 0, 0, null],
  ])
  assert.equal(report.returnWithin7.retained, 1)
  assert.equal(report.returnWithin7.eligible, 1)
  assert.deepEqual(report.friends.map((friend) => [friend.email, friend.lastVisit, friend.activeDays, friend.retention[1], friend.retention[7], friend.returnWithin7, friend.pages]), [
    ['early@friend.test', '2026-10-12', 2, 'unobserved', 'yes', 'yes', ['HOME', '기술 분석']],
    ['next@friend.test', '2026-10-11', 1, 'no', 'pending', 'pending', ['가치 분석']],
    ['new@friend.test', null, 0, 'pending', 'pending', 'pending', []],
  ])
  assert.equal(report.friends[2].name, 'new')
  assert.equal(report.pages.find((page) => page.page === 'home')?.userDays, 1)
  assert.equal(report.daily.at(-1)?.users, 1)
  assert.equal(report.daily.at(-2)?.users, 2)
})
