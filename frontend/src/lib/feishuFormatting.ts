/** Format evidence is independent from a document URL or notification success. */
export type FormattingReceipt = {
  protocol?: string;
  status?: string;
  native_required?: string[];
  native_write_confirmed?: boolean;
  image_source_preserved?: boolean;
  images_embedded?: boolean;
};

export function feishuFormattingMessage(formatting?: FormattingReceipt, deliveryStatus?: string): string {
  if (formatting?.protocol === 'feishu-task-native-images-v1') {
    return deliveryStatus === 'completed' && formatting.status === 'written'
      && formatting.native_write_confirmed === true && formatting.images_embedded === true
      && formatting.image_source_preserved === false
      ? '原生图文及段落顺序已回读核验。'
      : '图文写入尚未完整核验，请查询原回执。';
  }
  if (!formatting || !['legacy-safe-v1', 'feishu-markdown-selective-v2', 'feishu-markdown-descendant-v1'].includes(formatting.protocol || '')) {
    return '正文格式尚未核验。';
  }
  if (formatting.status === 'unsupported') {
    return formatting.image_source_preserved
      ? '正文含图片，当前不支持图片发布。'
      : '此正文格式尚不支持，未确认完成格式写入。';
  }
  if (formatting.image_source_preserved || formatting.status === 'partial') {
    return '正文格式未完整确认，图片嵌入尚未核验。';
  }
  if (formatting.protocol === 'legacy-safe-v1' && formatting.status === 'basic') return '基础正文格式。';
  const labels: Record<string, string> = { table: '表格', code: '代码块', inline: '行内样式' };
  const kinds = Array.isArray(formatting.native_required)
    ? [...new Set(formatting.native_required.filter(kind => Object.prototype.hasOwnProperty.call(labels, kind)).map(kind => labels[kind]))]
    : [];
  if (!kinds.length) return '正文格式尚未核验。';
  return deliveryStatus === 'completed' && formatting.status === 'written' && formatting.native_write_confirmed === true
    ? `原生${kinds.join('、')}已确认写入。`
    : `原生${kinds.join('、')}写入结果尚未确认。`;
}
