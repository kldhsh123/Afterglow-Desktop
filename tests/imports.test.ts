import test from 'node:test'
import assert from 'node:assert/strict'
import { summarizeImport, validImportIdentities, type ImportedFile } from '../src/domain/imports'

function file(name: string, uids: string[]): ImportedFile {
  return { name, saved_as: name, size: 100, format: 'afterglow_v1', format_label: '', total_messages: 2,
    candidates: uids.map(uid => ({ uid, name: uid, role_hint: 'unknown' })), error: '' }
}

test('different files may use different accounts for the same two people', () => {
  const files = [file('qq.json', ['qq-me', 'qq-friend']), file('wechat.json', ['wx-me', 'wx-friend'])]
  assert.equal(validImportIdentities(files, ['qq-me', 'wx-me'], ['qq-friend', 'wx-friend']), true)
  assert.equal(validImportIdentities(files, ['qq-me'], ['qq-friend']), false)
  assert.equal(validImportIdentities(files, ['qq-me', 'wx-me'], ['qq-friend', 'wx-me']), false)
  assert.equal(validImportIdentities(files, ['missing'], ['qq-friend', 'wx-friend']), false)
})

test('import summary counts only actual file reports, not persona metadata', () => {
  const summary = summarizeImport({ failed_chunks: 0, files: [
    { file: 'sample.json', report: { parsed_messages: 10, skipped_messages: 0, duration_seconds: 2.141,
      upserted_friend: 5, upserted_response_pairs: 5, upserted_window: 1 } },
    { persona: { parsed_messages: 10 } },
  ], vector_indices: { friend_messages: 'skip_small (5 rows < 1000)' } })
  assert.deepEqual(summary, { files: ['sample.json'], messages: 10, written: 11, skipped: 0,
    failed: 0, seconds: 2.141, smallIndex: true })
  assert.equal(summarizeImport(null), null)
})
