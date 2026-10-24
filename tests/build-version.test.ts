import test from 'node:test'
import assert from 'node:assert/strict'
import metadata from '../version.json'
import { appVersion, internalBuild, isInternalBuild } from '../src/domain/build'

test('the UI uses the public release version and keeps its Windows build number', () => {
  assert.equal(internalBuild, metadata.internalBuild)
  assert.equal(isInternalBuild, metadata.channel !== 'stable')
  assert.equal(appVersion, isInternalBuild ? `${metadata.baseVersion}-internal.${internalBuild}` : metadata.baseVersion)
})
