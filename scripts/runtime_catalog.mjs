// Core installation uses verified bundled resources; only desktop updates use
// the published release catalog. Core source updates use the upstream repo.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export function writeRuntimeCatalog(root = resolve(dirname(fileURLToPath(import.meta.url)), '..')) {
  const source = JSON.parse(readFileSync(resolve(root, 'src-tauri/resources/catalog.json'), 'utf8'))
  const catalog = {
    format: 1,
    updateUrl: source.updateUrl || 'https://github.com/kldhsh123/Afterglow-Desktop/releases/latest/download/catalog.json',
    components: (source.components || []).map(entry => {
      if (entry.id !== 'core' || !/^[a-f0-9]{64}$/i.test(entry.sha256)
          || !/^[A-Za-z0-9._-]+$/.test(entry.version)
          || typeof entry.bundled !== 'string'
          || !/^packages\/[A-Za-z0-9._-]+\.zip$/.test(entry.bundled)) {
        throw new Error('Prepare a verified core release package before generating the runtime catalog')
      }
      return { id: entry.id, version: entry.version, sha256: entry.sha256, bundled: entry.bundled }
    }),
  }
  writeFileSync(resolve(root, 'src-tauri/resources/runtime-catalog.json'), JSON.stringify(catalog, null, 2) + '\n')
  return catalog
}
