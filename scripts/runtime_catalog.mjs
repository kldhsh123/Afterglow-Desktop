// Keep the verified offline core and provide an online update catalog as well.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { desktopVersion } from './version_metadata.mjs'

export function writeRuntimeCatalog(root = resolve(dirname(fileURLToPath(import.meta.url)), '..')) {
  const source = JSON.parse(readFileSync(resolve(root, 'src-tauri/resources/catalog.json'), 'utf8'))
  const metadata = JSON.parse(readFileSync(resolve(root, 'version.json'), 'utf8'))
  const version = desktopVersion(metadata)
  const base = 'https://github.com/kldhsh123/Afterglow-Desktop/releases/download/v' + version + '/'
  const catalog = {
    format: 1,
    updateUrl: source.updateUrl || 'https://github.com/kldhsh123/Afterglow-Desktop/releases/latest/download/catalog.json',
    components: (source.components || []).map(entry => {
      const file = entry.bundled?.split('/').at(-1)
      if (entry.id !== 'core' || !/^[a-f0-9]{64}$/i.test(entry.sha256)
          || !/^[A-Za-z0-9._-]+$/.test(entry.version)
          || (!entry.url && (!file || !/^[A-Za-z0-9._-]+\.zip$/.test(file)))) {
        throw new Error('Prepare a verified core release package before generating the runtime catalog')
      }
      return { id: entry.id, version: entry.version, sha256: entry.sha256,
        ...(entry.bundled ? { bundled: entry.bundled } : {}), url: entry.url || base + file }
    }),
  }
  writeFileSync(resolve(root, 'src-tauri/resources/runtime-catalog.json'), JSON.stringify(catalog, null, 2) + '\n')
  return catalog
}
