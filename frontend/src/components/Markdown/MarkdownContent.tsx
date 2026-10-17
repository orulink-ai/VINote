import { isValidElement, useMemo, type ComponentType, type ReactNode } from 'react'
import { SimpleFlowchart } from './SimpleFlowchart'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import { ContentImage, type RemoteImagePolicy } from './ContentImage'
import { attachmentId } from '@/lib/workspaceAttachments'
import remarkGfm from 'remark-gfm'
import { remarkRecordingTimestamps } from '../../lib/remarkRecordingTimestamps'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import {
  extractSecondsFromHref,
  isLocalMediaHref,
  isSameVideoTarget,
  resolveContentUrl,
} from '../../lib/videoLinks'
import { slugifyHeadingText } from '../../lib/markdownKeyMoments'

interface MarkdownContentProps {
  content: string
  compact?: boolean
  className?: string
  videoUrl?: string
  mediaUrl?: string
  onVideoJump?: (seconds: number) => void
  remoteImagePolicy?: RemoteImagePolicy
  imageSessionKey?: string
}

function flattenText(children: ReactNode): string {
  if (typeof children === 'string' || typeof children === 'number') {
    return String(children)
  }

  if (Array.isArray(children)) {
    return children.map((child) => flattenText(child)).join('')
  }

  if (children && typeof children === 'object' && 'props' in children) {
    return flattenText((children as { props?: { children?: ReactNode } }).props?.children ?? '')
  }

  return ''
}

function slugifyHeading(children: ReactNode) {
  return slugifyHeadingText(flattenText(children))
}

const CodeHighlighter = SyntaxHighlighter as unknown as ComponentType<{
  style: typeof oneDark
  language?: string
  PreTag?: string
  className?: string
  children: string
}>

function createHeading(level: 'h1' | 'h2' | 'h3', className: string) {
  return function Heading({ children }: { children?: ReactNode }) {
    const id = slugifyHeading(children)
    const Tag = level
    return (
      <Tag id={id} className={`${className} group`}>
        <span>{children}</span>
        <a
          href={`#${id}`}
          className="ml-2 align-middle text-sm text-muted-foreground no-underline opacity-0 transition hover:text-primary group-hover:opacity-100"
          aria-label={`Link to ${id}`}
        >
          #
        </a>
      </Tag>
    )
  }
}

export function MarkdownContent({ content, compact = false, className, videoUrl, mediaUrl, onVideoJump, remoteImagePolicy = 'confirm', imageSessionKey = '' }: MarkdownContentProps) {
  // Keep the rendered subtree alive during unrelated workspace updates. An
  // inline Markdown component type would discard per-image load/retry state.
  const document = useMemo(() => (
      <ReactMarkdown
        key={JSON.stringify([content, remoteImagePolicy, imageSessionKey])}
        urlTransform={(url, key) => key === 'src' && attachmentId(url) ? url : defaultUrlTransform(url)}
        remarkPlugins={[remarkGfm, [remarkRecordingTimestamps, { mediaUrl: onVideoJump ? mediaUrl : undefined }]]}
        components={{
          pre: ({ children }) => isValidElement<{ className?: string }>(children) && children.props.className === 'language-mermaid' ? <>{children}</> : <pre>{children}</pre>,
          table: ({ children }) => (
            <table className="w-full border-collapse my-4 text-sm overflow-x-auto block">{children}</table>
          ),
          thead: ({ children }) => (
            <thead className="bg-muted">{children}</thead>
          ),
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => (
            <tr className="border-b border-border transition-colors hover:bg-muted/50">{children}</tr>
          ),
          th: ({ children }) => (
            <th className="border-b-2 border-border px-4 py-2.5 text-left font-semibold text-foreground">{children}</th>
          ),
          td: ({ children }) => (
            <td className="px-4 py-2.5 text-muted-foreground">{children}</td>
          ),
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            if (match?.[1] === 'mermaid') return <SimpleFlowchart source={String(children).replace(/\n$/, '')} />
            return match ? (
              <CodeHighlighter
                style={oneDark}
                language={match[1]}
                PreTag="div"
                className="rounded-lg"
              >
                {String(children).replace(/\n$/, '')}
              </CodeHighlighter>
            ) : (
              <code className={`${className} rounded bg-muted px-1 py-0.5`} {...props}>
                {children}
              </code>
            )
          },
          h1: createHeading('h1', compact ? 'text-base font-medium mb-3 scroll-mt-24' : 'text-xl font-medium mb-4 scroll-mt-24'),
          h2: createHeading('h2', compact ? 'text-sm font-medium mt-5 mb-2 scroll-mt-24' : 'text-lg font-medium mt-6 mb-3 scroll-mt-24'),
          h3: createHeading('h3', compact ? 'text-sm font-medium mt-4 mb-2 scroll-mt-24' : 'text-base font-medium mt-4 mb-2 scroll-mt-24'),
          p: ({ children }) => <p className="mb-3 leading-relaxed">{children}</p>,
          ul: ({ children }) => <ul className="list-disc pl-6 mb-3">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-6 mb-3">{children}</ol>,
          li: ({ children }) => <li className="mb-1">{children}</li>,
          a: ({ href, children }) => {
            const resolvedHref = href ? resolveContentUrl(href) : undefined
            return (
              <a
                href={resolvedHref}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline underline-offset-2"
                onClick={(event) => {
                  if (!resolvedHref || !onVideoJump) {
                    return
                  }

                  const matchesSource =
                    Boolean(videoUrl && isSameVideoTarget(resolvedHref, videoUrl)) ||
                    Boolean(mediaUrl && isLocalMediaHref(resolvedHref))

                  if (!matchesSource) {
                    return
                  }

                  const seconds = extractSecondsFromHref(resolvedHref)
                  if (seconds === null) {
                    return
                  }

                  event.preventDefault()
                  onVideoJump(seconds)
                }}
              >
                {children}
              </a>
            )
          },
          img: ({ src, alt }) => <ContentImage key={content} src={src} alt={alt} remoteImagePolicy={remoteImagePolicy} imageSessionKey={imageSessionKey} />,
          blockquote: ({ children }) => (
            <blockquote className="my-4 border-l-4 border-primary pl-4 italic text-muted-foreground">
              {children}
            </blockquote>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
  ), [content, compact, videoUrl, mediaUrl, onVideoJump, remoteImagePolicy, imageSessionKey])
  return <div className={className}>{document}</div>
}
