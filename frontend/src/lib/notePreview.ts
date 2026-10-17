/** Lists show text; media URLs and screenshot markers belong in the reader. */
export function notePreview(content: string): string {
  return content
    .replace(/!\[[^\]]*\]\([^\n]*?\)/g, ' ')
    .replace(/\[\[Screenshot:[^\]]*\]\]/gi, ' ')
    .replace(/\[([^\]]*)\]\([^\n]*?\)/g, '$1')
    .replace(/^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)/gm, '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/(?:https?:\/\/|\/api\/)[^\s)]+/g, ' ')
    .replace(/[`*_~|]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}
