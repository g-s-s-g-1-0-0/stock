import assert from 'node:assert/strict'
import { test } from 'node:test'
import { scheduledPublishAtForCron } from '../api/admin/trigger-refresh.js'

test('Sunday preparation and late Monday dispatch share the midnight target', () => {
  for (const instant of ['2026-11-01T14:50:00Z', '2026-11-01T15:00:30Z', '2026-11-01T17:59:59Z']) {
    assert.equal(scheduledPublishAtForCron('market-trends', new Date(instant)), '2026-11-01T15:00:00Z')
  }
})

test('weekly target crosses year boundaries in Korea time', () => {
  assert.equal(scheduledPublishAtForCron('market-trends', new Date('2027-01-03T14:50:00Z')), '2027-01-03T15:00:00Z')
  assert.equal(scheduledPublishAtForCron('market-trends', new Date('2026-11-01T18:00:00Z')), '')
  assert.equal(scheduledPublishAtForCron('market-trends', new Date('2026-12-31T14:50:00Z')), '')
})
