import { t } from '../i18n'

export interface ChatImage { id?: string; name: string; dataUrl?: string; preview: string }
export async function prepareChatImage(name: string, dataUrl: string): Promise<ChatImage> {
  const image = new Image()
  await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error(t('chat.image_invalid'))); image.src = dataUrl })
  if (!image.naturalWidth || !image.naturalHeight || image.naturalWidth * image.naturalHeight > 40_000_000) throw new Error(t('chat.image_invalid'))
  function jpeg(maximum: number, quality: number) {
    const scale = Math.min(1, maximum / Math.max(image.naturalWidth, image.naturalHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale)); canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error(t('chat.image_invalid'))
    context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', quality)
  }
  let full = jpeg(1920, .84)
  if (full.length > 2 * 1024 * 1024 * 4 / 3) full = jpeg(1280, .72)
  if (full.length > 2 * 1024 * 1024 * 4 / 3) throw new Error(t('chat.image_invalid'))
  return { name: name.slice(0, 240), dataUrl: full, preview: jpeg(240, .7) }
}
