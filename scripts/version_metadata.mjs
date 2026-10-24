// Missing channel preserves the version format used by earlier internal builds.
export function desktopVersion(metadata) {
  if (!metadata || typeof metadata.baseVersion !== 'string'
      || !/^\d+\.\d+\.\d+$/.test(metadata.baseVersion)
      || metadata.baseVersion.trim() !== metadata.baseVersion
      || metadata.baseVersion.split('.').some(value => Number(value) > 65535)
      || !Number.isInteger(metadata.internalBuild) || metadata.internalBuild < 1
      || metadata.internalBuild > 65535
      || !['internal', 'stable'].includes(metadata.channel === undefined ? 'internal' : metadata.channel)) {
    throw new Error('version.json requires baseVersion, internalBuild (1–65535), and an internal/stable channel')
  }
  return metadata.channel === 'stable'
    ? metadata.baseVersion
    : metadata.baseVersion + '-internal.' + metadata.internalBuild
}
