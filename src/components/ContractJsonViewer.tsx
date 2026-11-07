/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { Copy, Check, FileJson, Hash } from 'lucide-react';
import { MergeGateResult } from '../types/mergeGate';

interface ContractJsonViewerProps {
  gateResult: MergeGateResult | null;
}

export const ContractJsonViewer: React.FC<ContractJsonViewerProps> = ({ gateResult }) => {
  const [copied, setCopied] = useState(false);

  if (!gateResult) {
    return (
      <div className="rounded-xl border border-yellow-500/20 bg-neutral-950 p-8 text-center text-neutral-500 font-mono text-xs">
        No evaluation result generated yet. Run gate check to inspect JSON contract.
      </div>
    );
  }

  const jsonString = JSON.stringify(gateResult, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-xl border border-yellow-500/20 bg-black overflow-hidden font-mono text-xs">
      <div className="bg-neutral-950 px-4 py-2.5 border-b border-neutral-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileJson className="w-4 h-4 text-yellow-400" />
          <span className="font-bold text-yellow-400">Owner Interface Contract (Fixed Format)</span>
          <span className="text-[10px] text-neutral-500">· {new Blob([jsonString]).size} bytes</span>
        </div>

        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1 text-black font-bold bg-yellow-400 hover:bg-yellow-300 rounded transition-colors text-[11px]"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-black" />
              <span>Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy JSON</span>
            </>
          )}
        </button>
      </div>

      <div className="p-4 overflow-x-auto text-neutral-300 leading-relaxed max-h-[460px]">
        <pre className="text-yellow-100/90">
          <code>{jsonString}</code>
        </pre>
      </div>
    </div>
  );
};
