import React from 'react';

export default function SiteFooter() {
  return (
    <footer className="bg-slate-950 border-t border-slate-900 py-12">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row justify-between items-center">
          <div className="flex items-center gap-2 mb-4 md:mb-0">
            <img
              src="https://raw.githubusercontent.com/ruslanmv/ollabridge/refs/heads/master/assets/logo.svg"
              alt="OllaBridge Logo"
              className="h-6 w-6"
            />
            <span className="text-lg font-bold text-white">OllaBridge</span>
            <span className="text-slate-500 text-sm ml-2">© {new Date().getFullYear()}</span>
          </div>

          <div className="flex flex-wrap justify-center gap-x-6 gap-y-2">
            <a href="#/docs" className="text-slate-400 hover:text-white transition-colors">
              Documentation
            </a>
            <a
              href="https://github.com/ruslanmv/ollabridge"
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-400 hover:text-white transition-colors"
            >
              GitHub
            </a>
            <a href="#" className="text-slate-400 hover:text-white transition-colors">
              License (MIT)
            </a>
          </div>
        </div>

        <div className="mt-8 text-center md:text-left">
          <a
            href="https://github.com/ruslanmv/ollabridge"
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs text-slate-400 hover:border-slate-600 transition-colors"
          >
            <div className="w-2 h-2 rounded-full bg-green-500"></div>
            <span>System Operational</span>
          </a>
        </div>
      </div>
    </footer>
  );
}
