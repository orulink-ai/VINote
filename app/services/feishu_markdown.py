"""Official Markdown conversion, validated and frozen before native writes.

No generative model or content rewriting. Unsupported assets fail explicitly.
"""
from copy import deepcopy
import hashlib
import uuid
import re

PROTOCOL = "feishu-markdown-descendant-v1"
MAX_BLOCKS = 1000
SELECTIVE_PROTOCOL = "feishu-markdown-selective-v2"


def table_delimiter(line):
    cells = line.strip().strip("|").split("|")
    return bool(cells) and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells)


def segments(content):
    """Conservative line segmentation; false positives never downgrade tables.

    Preserve image-containing paragraphs as source, without fetching any URL.
    A table containing images is blocked rather than published as raw pipes.
    """
    lines = content.splitlines(keepends=True)
    result = []
    i = 0
    while i < len(lines):
        start = i
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", lines[i])
        if fence:
            marker = fence[1]
            i += 1
            while i < len(lines):
                line = lines[i]
                i += 1
                if re.match(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$", line):
                    break
            kind = "code"
        elif (i + 1 < len(lines) and "|" in lines[i] and
              table_delimiter(lines[i + 1])):
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                i += 1
            kind = "table"
        elif re.match(r"^( {4}|\t)\S", lines[i]):
            i += 1
            while i < len(lines) and (not lines[i].strip() or re.match(r"^( {4}|\t)", lines[i])):
                i += 1
            kind = "code"
        else:
            i += 1
            kind = "legacy"
        text = "".join(lines[start:i])
        image = bool(re.search(r"!\[|<img\b", text, re.I)) if kind != "code" else False
        if kind == "table" and image:
            kind = "blocked_image_table"
        elif image:
            kind = "image_source"
        elif kind == "legacy" and re.search(r"(?<!\\)(`[^`]+`|~~.+?~~|(?<!\*)\*[^*]+\*(?!\*)|_[^_]+_|\[[^\]]+\]\([^)]*\))", text):
            kind = "inline"
        if result and result[-1]["kind"] == kind and kind in ("legacy", "inline", "image_source"):
            result[-1]["content"] += text
        else:
            result.append({"kind": kind, "content": text})
    return result


def format_selection(content):
    parts = segments(content)
    needs = sorted({p["kind"] for p in parts if p["kind"] in ("table", "code", "inline")})
    images = any(p["kind"] in ("image_source", "blocked_image_table") for p in parts)
    blocked = any(p["kind"] == "blocked_image_table" for p in parts)
    return {"protocol": SELECTIVE_PROTOCOL if needs or blocked else "legacy-safe-v1",
            "needs_converter": bool(needs or blocked), "native_required": needs,
            "image_source_preserved": images, "blocked_image_table": blocked,
            "message": ("正文含图片，尚不支持原生图片写入；不能以原始引用冒充图片完成。" if images else "")}


def legacy_blocks(content):
    """Exact old line writer; used only for simple/image source segments."""
    blocks = []
    for line in content.splitlines():
        if not line.strip():
            continue
        level = len(line) - len(line.lstrip("#"))
        kind = f"heading{level}" if 1 <= level <= 6 and line[level:level + 1] == " " else "text"
        text = line[level + 1:] if kind != "text" else line
        block_type = level + 2 if kind != "text" else 2
        if kind == "text" and re.match(r"^\s*[-*+]\s+", text):
            kind, block_type = "bullet", 12
            text = re.sub(r"^\s*[-*+]\s+", "", text)
        elif kind == "text" and re.match(r"^\s*\d+\.\s+", text):
            kind, block_type = "ordered", 13
            text = re.sub(r"^\s*\d+\.\s+", "", text)
        elements = []
        for piece in re.split(r"(\*\*[^*]+\*\*)", text):
            bold = piece.startswith("**") and piece.endswith("**") and len(piece) > 4
            value = piece[2:-2] if bold else piece
            for offset in range(0, len(value), 1000):
                elements.append({"text_run": {"content": value[offset:offset + 1000],
                                             **({"text_element_style": {"bold": True}} if bold else {})}})
        for offset in range(0, len(elements), 20):
            blocks.append({"block_type": block_type, kind: {"elements": elements[offset:offset + 20]}})
    return blocks


def required_inline_styles(text):
    """Conservative supported inline syntax; code contents are literal."""
    text = re.sub(r"\\([\\`*_\[\]~])", " ", text)
    required = set()
    code = r"(?<!`)(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)"
    if re.search(code, text):
        required.add("inline_code")
        text = re.sub(code, " ", text)
    link = r"(?<!!)\[([^\]]+)\]\([^)]*\)"
    if re.search(link, text):
        required.add("link")
        # Retain labels for emphasis checks, but never parse URL characters.
        text = re.sub(link, r"\1", text)
    if re.search(r"~~.+?~~", text):
        required.add("strikethrough")
    if re.search(r"\*\*[^*]+\*\*|__[^_]+__", text):
        required.add("bold")
    if re.search(r"(?<!\*)\*[^*]+\*(?!\*)|(?<!_)_[^_]+_(?!_)", text):
        required.add("italic")
    if re.search(r"\*{3}[^*]+\*{3}|_{3}[^_]+_{3}", text):
        required.update(("bold", "italic"))
    return required


def validate_inline_styles(text, blocks):
    required = required_inline_styles(text)
    present = set()
    for block in blocks:
        for value in block.values():
            if not isinstance(value, dict):
                continue
            for element in value.get("elements", []):
                style = element.get("text_run", {}).get("text_element_style", {})
                present.update(key for key in ("italic", "bold", "inline_code", "strikethrough")
                               if style.get(key) is True)
                link = style.get("link")
                if isinstance(link, dict) and isinstance(link.get("url"), str) and link["url"].strip():
                    present.add("link")
    if not required or not required <= present:
        raise FormatError("飞书未保留全部所需行内样式，禁止标为格式转换完成")


def validate_frozen_inline_styles(content, plan, frozen_parts=None):
    if plan.get("protocol") != SELECTIVE_PROTOCOL:
        return
    parts = frozen_parts if frozen_parts is not None else segments(content)
    if "".join(part["content"] for part in parts) != content:
        raise FormatError("冻结转换范围与原正文不一致")
    for index, part in enumerate(parts):
        if part["kind"] == "inline":
            prefix = f"segment-{index}-"
            blocks = [node for batch in plan["batches"] for node in batch["body"]["descendants"]
                      if node["block_id"].startswith(prefix)]
            validate_inline_styles(part["content"], blocks)


def selective_plan(content, convert, frozen_parts=None):
    selection = format_selection(content)
    if selection["image_source_preserved"]:
        raise FormatError("正文含图片引用，图片原生写入尚未支持；禁止写入原始引用冒充完成")
    batches = []
    offset = 0
    parts = frozen_parts if frozen_parts is not None else segments(content)
    if "".join(part["content"] for part in parts) != content:
        raise FormatError("冻结转换范围与原正文不一致")
    for index, part in enumerate(parts):
        kind, text = part["kind"], part["content"]
        if kind in ("table", "code", "inline"):
            converted = convert(text)
            if kind == "table" and not any(b.get("block_type") == 31 for b in converted.get("blocks", [])):
                raise FormatError("飞书未生成原生表格，禁止将原始管道文本标为完成")
            if kind == "code" and not any(b.get("block_type") == 14 for b in converted.get("blocks", [])):
                raise FormatError("飞书未生成原生代码块")
            if kind == "inline":
                validate_inline_styles(text, converted.get("blocks", []))
            planned = prepare_plan(text, converted)["batches"]
        else:
            nodes = legacy_blocks(text)
            for n, node in enumerate(nodes):
                node["block_id"] = f"legacy-{index}-{n}"
            planned = []
            if nodes:
                planned = prepare_plan(text, {"first_level_block_ids": [n["block_id"] for n in nodes], "blocks": nodes})["batches"]
        for batch in planned:
            # Conversion IDs are only unique within one conversion response.
            # Prefix each segment so multiple conversions cannot collide.
            rename = lambda key: f"segment-{index}-{key}"
            batch["body"]["children_id"] = [rename(key) for key in batch["body"]["children_id"]]
            for node in batch["body"]["descendants"]:
                node["block_id"] = rename(node["block_id"])
                if "children" in node:
                    node["children"] = [rename(key) for key in node["children"]]
            batch["offset"] = offset
            batch["body"]["index"] = offset
            batches.append(batch)
            offset += len(batch["body"]["children_id"])
    return {"protocol": SELECTIVE_PROTOCOL, "source_hash": source_hash(content), "batches": batches}


class FormatError(ValueError):
    pass


def source_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def prepare_plan(content, converted):
    if not 1 <= len(content) <= 10485760:
        raise FormatError("Markdown must contain 1–10485760 characters")
    roots = converted.get("first_level_block_ids")
    blocks = deepcopy(converted.get("blocks"))
    if not isinstance(roots, list) or not roots or not isinstance(blocks, list):
        raise FormatError("Conversion returned no valid block tree")
    by_id = {}
    for block in blocks:
        if not isinstance(block, dict):
            raise FormatError("Invalid block")
        key = block.get("block_id")
        if not isinstance(key, str) or not key or key in by_id:
            raise FormatError("Missing or duplicate block ID")
        kind = block.get("block_type")
        if kind not in {*range(2, 16), 17, 22, 31, 32, 34}:
            raise FormatError("Unsupported block/asset; native image upload is not implemented")
        # Conversion returns read-only fields not accepted by descendant creation.
        block.pop("parent_id", None)
        block.pop("revision_id", None)
        if kind == 31:
            table = block.get("table", {})
            prop = table.get("property", {})
            rows, cols = prop.get("row_size"), prop.get("column_size")
            if (type(rows) is not int or type(cols) is not int or
                    rows < 1 or not 1 <= cols <= 100 or rows * cols > 2000):
                raise FormatError("Table dimensions exceed official limits")
            if any(item.get("row_span", 1) != 1 or item.get("col_span", 1) != 1
                   for item in prop.get("merge_info", [])):
                raise FormatError("Merged cells require a separate confirmed merge operation")
            prop.pop("merge_info", None)
            table.pop("merge_info", None)
            # cells is a read-only response field; children carries cell IDs.
            table.pop("cells", None)
            if len(block.get("children", [])) != rows * cols:
                raise FormatError("Table cells do not match dimensions")
        if kind in (32, 34) and not block.get("children"):
            raise FormatError("Cell/container has no content block")
        by_id[key] = block
    visited = set()

    def subtree(key, depth=0):
        if depth > 100 or key not in by_id or key in visited:
            raise FormatError("Cyclic, shared or missing child")
        visited.add(key)
        block = by_id[key]
        children = block.get("children", [])
        if not isinstance(children, list):
            raise FormatError("Invalid children")
        result = [block]
        for child in children:
            result.extend(subtree(child, depth + 1))
        return result

    batches, pending_ids, pending_blocks, offset = [], [], [], 0

    def flush():
        nonlocal pending_ids, pending_blocks, offset
        if pending_ids:
            batches.append({"offset": offset, "client_token": str(uuid.uuid4()),
                            "body": {"children_id": pending_ids, "index": offset,
                                     "descendants": pending_blocks}})
            offset += len(pending_ids)
            pending_ids, pending_blocks = [], []

    for root in roots:
        tree = subtree(root)
        if len(tree) > MAX_BLOCKS:
            raise FormatError("A single subtree exceeds 1000 blocks; cannot split faithfully")
        if len(pending_blocks) + len(tree) > MAX_BLOCKS:
            flush()
        pending_ids.append(root)
        pending_blocks.extend(tree)
    flush()
    if visited != set(by_id):
        raise FormatError("Conversion contains orphaned blocks")
    return {"protocol": PROTOCOL, "source_hash": source_hash(content), "batches": batches}
