import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { writeRuntimeCatalog } from './runtime_catalog.mjs'
import { desktopVersion } from './version_metadata.mjs'

const root = fileURLToPath(new URL('../', import.meta.url))
const read = path => JSON.parse(readFileSync(resolve(root, path), 'utf8'))
const write = (path, value) => writeFileSync(resolve(root, path), JSON.stringify(value, null, 2) + '\n')
const metadata = read('version.json')
desktopVersion(metadata)
if (process.argv.includes('--bump')) {
  const parts = metadata.baseVersion.split('.').map(Number)
  if (parts[2] === 65535) throw new Error('Choose the next minor or major baseVersion in version.json')
  if (metadata.internalBuild === 65535) throw new Error('Set the next baseVersion and reset the Windows build counter in version.json')
  parts[2]++
  metadata.baseVersion = parts.join('.')
  metadata.internalBuild++
  metadata.channel = 'stable'
  write('version.json', metadata)
}
const version = desktopVersion(metadata)
for (const path of ['package.json', 'src-tauri/tauri.conf.json']) {
  const data = read(path)
  data.version = version
  if (path === 'src-tauri/tauri.conf.json') {
    data.bundle.windows.nsis = { ...data.bundle.windows.nsis, installMode: 'currentUser', languages: ['SimpChinese', 'English'], displayLanguageSelector: true, compression: 'lzma' }
  }
  write(path, data)
}
const lock = read('package-lock.json')
lock.version = version
lock.packages[''].version = version
write('package-lock.json', lock)
const cargoPath = resolve(root, 'src-tauri/Cargo.toml')
writeFileSync(cargoPath, readFileSync(cargoPath, 'utf8').replace(/^(version\s*=\s*)"[^"]+"/m, '$1"' + version + '"'))
const cargoLockPath = resolve(root, 'src-tauri/Cargo.lock')
writeFileSync(cargoLockPath, readFileSync(cargoLockPath, 'utf8').replace(
  /(\[\[package\]\]\r?\nname = "afterglow-desktop"\r?\nversion = )"[^"]+"/,
  '$1"' + version + '"',
))
writeRuntimeCatalog(root)
console.log(version)
