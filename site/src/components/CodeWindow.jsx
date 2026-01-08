import React, { useMemo, useState } from 'react';
import { Copy, Check, Terminal } from 'lucide-react';

/**
 * A "terminal window" style code block with a copy button.
 */
export default function CodeWindow({ title = 'terminal', subtitle = '', code = '' }) {
  const [copied, setCopied] = useState(false);

  const lines = useMemo(() => {
    const text = String(code || '').replace(/\n\s+$/g, '\n').trimEnd();
    return text.split('\n');
  }, [code]);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(String(code || '').trim());
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Fallback: select & copy via a temporary textarea.
      const ta = document.createElement('textarea');
      ta.value = String(code || '').trim();
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }
  };

  return (
    <div className="bg-slate-900 rounded-xl shadow-2xl border border-slate-700 overflow-hidden text-left ring-1 ring-white/10">
      <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center">
          <div className="flex space-x-2">
            <div className="w-3 h-3 rounded-full bg-red-500/80 border border-red-600/50"></div>
            <div className="w-3 h-3 rounded-full bg-yellow-500/80 border border-yellow-600/50"></div>
            <div className="w-3 h-3 rounded-full bg-green-500/80 border border-green-600/50"></div>
          </div>
          <div className="ml-4 text-xs text-slate-400 font-mono flex items-center gap-2">
            <Terminal className="w-3 h-3" />
            <span className="text-slate-300">{title}</span>
            {subtitle ? <span className="text-slate-500">— {subtitle}</span> : null}
          </div>
        </div>

        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-md border border-slate-600 bg-slate-900 hover:bg-slate-950 text-slate-200 transition-colors"
          aria-label="Copy to clipboard"
        >
          {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4 text-slate-300" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>

      <div className="p-5 bg-slate-950 font-mono text-sm leading-relaxed text-slate-200 overflow-x-auto">
        <pre className="whitespace-pre">
          {lines.map((ln, i) => (
            <div key={i} className="min-w-max">
              {ln}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
