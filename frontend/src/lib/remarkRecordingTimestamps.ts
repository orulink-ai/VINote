type Node = { type: string; value?: string; url?: string; children?: Node[] }

/** Link plain evidence references, preserving authored links and code. */
export function remarkRecordingTimestamps({ mediaUrl }: { mediaUrl?: string }) {
  return (tree: Node) => {
    if (!mediaUrl) return
    const walk = (parent: Node) => {
      if (!parent.children || ['link', 'linkReference', 'code', 'inlineCode', 'html'].includes(parent.type)) return
      parent.children = parent.children.flatMap(child => {
        if (child.type !== 'text' || !child.value) { walk(child); return [child] }
        const point = '(?:\\d{1,3}:[0-5]\\d(?::[0-5]\\d)?|\\d{1,7}(?:\\.\\d+)?\\s*秒)'
        const reference = `${point}(?:[–-]${point})?`
        const pattern = new RegExp(`\\[(${reference}(?:\\s*[；;，,、]\\s*${reference})*)\\]`, 'g')
        const seconds = (label: string) => {
          const start = label.split(/[–-]/)[0].trim()
          return start.includes('秒') ? Number(start.replace(/\s*秒$/, '')) : start.split(':').reduce((total, value) => total * 60 + Number(value), 0)
        }
        const link = (label: string, time: string): Node => ({ type: 'link', url: `${mediaUrl}${mediaUrl.includes('?') ? '&' : '?'}t=${seconds(time)}`, children: [{ type: 'text', value: label }] })
        const nodes: Node[] = []
        let position = 0
        for (const match of child.value.matchAll(pattern)) {
          const index = match.index!
          if (index > position) nodes.push({ type: 'text', value: child.value.slice(position, index) })
          const references = [...match[1].matchAll(new RegExp(reference, 'g'))]
          if (references.length === 1) nodes.push(link(match[0], match[1]))
          else {
            nodes.push({ type: 'text', value: '[' })
            let innerPosition = 0
            for (const item of references) {
              if (item.index! > innerPosition) nodes.push({ type: 'text', value: match[1].slice(innerPosition, item.index) })
              nodes.push(link(item[0], item[0]))
              innerPosition = item.index! + item[0].length
            }
            nodes.push({ type: 'text', value: ']' })
          }
          position = index + match[0].length
        }
        if (!position) return [child]
        if (position < child.value.length) nodes.push({ type: 'text', value: child.value.slice(position) })
        return nodes
      })
    }
    walk(tree)
  }
}
