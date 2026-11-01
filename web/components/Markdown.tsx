import { Fragment, type ReactNode } from "react";

// Tiny markdown-light renderer: **bold**, *italic*, `code`, bullet / numbered lists,
// paragraphs and line breaks. Never uses dangerouslySetInnerHTML.

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*|__)(.+?)\1|`([^`]+)`|(?<![\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${keyBase}-${i++}`;
    if (m[2] != null) out.push(<strong key={k}>{m[2]}</strong>);
    else if (m[3] != null) out.push(<code key={k}>{m[3]}</code>);
    else if (m[4] != null) out.push(<em key={k}>{m[4]}</em>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block = { kind: "p"; lines: string[] } | { kind: "ul" | "ol"; items: string[] };

function parse(src: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of src.replace(/\r/g, "").split("\n")) {
    const line = raw.trimEnd();
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const top = blocks[blocks.length - 1];
    if (ul || ol) {
      const kind = ul ? "ul" : "ol";
      const item = (ul ?? ol)![1];
      if (top && top.kind === kind) top.items.push(item);
      else blocks.push({ kind, items: [item] });
    } else if (!line.trim()) {
      if (top && top.kind === "p" && top.lines.length) blocks.push({ kind: "p", lines: [] });
    } else {
      const heading = line.replace(/^#{1,6}\s+/, "");
      if (top && top.kind === "p") top.lines.push(heading);
      else blocks.push({ kind: "p", lines: [heading] });
    }
  }
  return blocks.filter((b) => (b.kind === "p" ? b.lines.length > 0 : b.items.length > 0));
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks = parse(text);
  return (
    <div className={className ?? "md"}>
      {blocks.map((b, bi) => {
        if (b.kind === "p")
          return (
            <p key={bi}>
              {b.lines.map((l, li) => (
                <Fragment key={li}>
                  {li > 0 && <br />}
                  {inline(l, `${bi}-${li}`)}
                </Fragment>
              ))}
            </p>
          );
        const List = b.kind;
        return (
          <List key={bi}>
            {b.items.map((it, ii) => (
              <li key={ii}>{inline(it, `${bi}-${ii}`)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
