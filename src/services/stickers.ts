import { rpc } from './desktop'
export interface Sticker { name: string; description: string; owner: 'self' | 'ai' | 'shared'; tags: string[]; sha: string; extension: string }
const images = new Map<string, Promise<string>>()
let active = 0
const queue: (() => void)[] = []
function release() { const next = queue.shift(); if (next) next(); else active-- }
async function fetchImage(instanceId: string, name: string) {
  if (active >= 4) await new Promise<void>(resolve => queue.push(resolve))
  else active++
  try { return (await rpc<{ dataUrl: string }>('stickers_image', { instanceId, name })).dataUrl }
  finally { release() }
}
export function stickerImage(instanceId: string, name: string, sha = ''): Promise<string> {
  const key = JSON.stringify([instanceId, name, sha])
  let result = images.get(key)
  if (!result) {
    result = fetchImage(instanceId, name).catch(error => { images.delete(key); throw error })
    images.set(key, result)
    if (images.size > 48) images.delete(images.keys().next().value!)
  }
  return result
}
export function invalidateStickers(instanceId: string) {
  for (const key of images.keys()) if (JSON.parse(key)[0] === instanceId) images.delete(key)
}
