import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";

const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
};

export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose">
      <ReactMarkdown components={components}>{text}</ReactMarkdown>
    </div>
  );
}
