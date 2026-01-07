import React, { useState, useEffect } from 'react';
import { 
  Zap, 
  Terminal, 
  Server, 
  Shield, 
  Globe, 
  Cpu, 
  Code, 
  CheckCircle, 
  ArrowRight, 
  Network, 
  Lock, 
  Cloud,
  Laptop,
  Copy,
  Menu,
  X
} from 'lucide-react';

// --- Components ---

const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <nav className="fixed w-full z-50 bg-slate-950/80 backdrop-blur-md border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-2">
            <img 
              src="https://raw.githubusercontent.com/ruslanmv/ollabridge/refs/heads/master/assets/logo.svg" 
              alt="OllaBridge Logo" 
              className="h-8 w-8" 
            />
            <span className="text-xl font-bold text-white tracking-tight">
              OllaBridge <span className="text-yellow-400">⚡️</span>
            </span>
          </div>
          
          <div className="hidden md:block">
            <div className="ml-10 flex items-baseline space-x-8">
              <a href="#features" className="text-slate-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium transition-colors">Features</a>
              <a href="#architecture" className="text-slate-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium transition-colors">Architecture</a>
              <a href="#docs" className="text-slate-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium transition-colors">Docs</a>
              <a href="https://github.com/ruslanmv/ollabridge" target="_blank" rel="noopener noreferrer" className="text-slate-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium transition-colors">GitHub</a>
            </div>
          </div>

          <div className="hidden md:block">
            <button className="bg-yellow-400 hover:bg-yellow-500 text-slate-900 px-5 py-2 rounded-lg font-bold text-sm transition-all transform hover:scale-105 shadow-[0_0_15px_rgba(250,204,21,0.3)]">
              Get Started
            </button>
          </div>

          <div className="-mr-2 flex md:hidden">
            <button onClick={() => setIsOpen(!isOpen)} className="inline-flex items-center justify-center p-2 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 focus:outline-none">
              {isOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {isOpen && (
        <div className="md:hidden bg-slate-900 border-b border-slate-800">
          <div className="px-2 pt-2 pb-3 space-y-1 sm:px-3">
            <a href="#features" className="text-slate-300 hover:text-white block px-3 py-2 rounded-md text-base font-medium">Features</a>
            <a href="#architecture" className="text-slate-300 hover:text-white block px-3 py-2 rounded-md text-base font-medium">Architecture</a>
            <a href="#docs" className="text-slate-300 hover:text-white block px-3 py-2 rounded-md text-base font-medium">Docs</a>
            <button className="w-full text-left bg-yellow-400 text-slate-900 mt-4 px-5 py-3 rounded-lg font-bold">
              Get Started
            </button>
          </div>
        </div>
      )}
    </nav>
  );
};

const Hero = () => {
  return (
    <div className="relative bg-slate-950 pt-32 pb-20 lg:pt-48 lg:pb-32 overflow-hidden">
      {/* Background Grid */}
      <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-20"></div>
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px]"></div>
      <div className="absolute left-0 right-0 top-0 -z-10 m-auto h-[310px] w-[310px] rounded-full bg-yellow-400 opacity-20 blur-[100px]"></div>

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center z-10">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-900 border border-slate-700 text-yellow-400 text-xs font-semibold uppercase tracking-wide mb-6 animate-fade-in-up">
          <Zap className="w-3 h-3" /> v1.0 Public Release
        </div>
        
        <h1 className="text-5xl md:text-7xl font-extrabold text-white tracking-tight mb-6 leading-tight">
          Your single gateway to <br className="hidden md:block" />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-yellow-300 to-amber-500">
            ALL your LLMs
          </span>
        </h1>
        
        <p className="mt-4 max-w-2xl mx-auto text-xl text-slate-400 mb-10">
          Unify local GPUs, Colab notebooks, and cloud instances into one OpenAI-compatible API endpoint. No VPNs. No port forwarding. Just code.
        </p>
        
        <div className="flex flex-col sm:flex-row justify-center gap-4">
          <button className="flex items-center justify-center gap-2 bg-yellow-400 hover:bg-yellow-500 text-slate-950 px-8 py-4 rounded-lg font-bold text-lg transition-all transform hover:-translate-y-1 shadow-[0_0_20px_rgba(250,204,21,0.4)]">
            Get Started in 60s
            <ArrowRight className="w-5 h-5" />
          </button>
          <button className="flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 px-8 py-4 rounded-lg font-semibold text-lg transition-all">
            <Code className="w-5 h-5 text-slate-400" />
            View Documentation
          </button>
        </div>

        {/* Terminal Strip */}
        <div className="mt-16 mx-auto max-w-4xl">
          <div className="bg-slate-900 rounded-lg shadow-2xl border border-slate-700 overflow-hidden text-left ring-1 ring-white/10">
            <div className="flex items-center px-4 py-3 bg-slate-800 border-b border-slate-700">
              <div className="flex space-x-2">
                <div className="w-3 h-3 rounded-full bg-red-500/80 border border-red-600/50"></div>
                <div className="w-3 h-3 rounded-full bg-yellow-500/80 border border-yellow-600/50"></div>
                <div className="w-3 h-3 rounded-full bg-green-500/80 border border-green-600/50"></div>
              </div>
              <div className="ml-4 text-xs text-slate-400 font-mono flex items-center gap-2">
                <Terminal className="w-3 h-3" />
                ollabridge — zsh — 80x24
              </div>
            </div>
            
            <div className="p-6 bg-slate-950 font-mono text-sm leading-relaxed text-slate-300 relative">
              <div className="mb-4">
                <span className="text-green-500 font-bold mr-2">➜</span>
                <span className="text-blue-400 font-bold mr-2">~</span>
                <span className="text-white">pip install ollabridge</span>
              </div>

              <div className="mb-6">
                <span className="text-green-500 font-bold mr-2">➜</span>
                <span className="text-blue-400 font-bold mr-2">~</span>
                <span className="text-white">ollabridge start</span>
                
                <div className="mt-2 text-slate-400">
                  <div>✅ Ollama installed</div>
                  <div>✅ Model downloaded</div>
                  <div>✅ Gateway online at <span className="text-blue-400 underline decoration-blue-400/30 underline-offset-2">http://localhost:11435</span></div>
                </div>
              </div>

              {/* TUI Box using CSS Borders for clean rendering */}
              <div className="relative border border-yellow-500/80 rounded-sm p-5 my-6 bg-slate-900/50">
                {/* Title intersecting the top border */}
                <div className="absolute -top-3 left-4 bg-slate-950 px-2 text-yellow-500 font-bold flex items-center gap-2 text-xs uppercase tracking-wider">
                   🚀 Gateway Ready 
                </div>

                <div className="grid grid-cols-[80px_1fr] gap-y-2 text-sm">
                   <div className="text-slate-500">Status:</div>
                   <div className="text-green-400 font-bold flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                      OllaBridge is Online
                   </div>

                   <div className="text-slate-500">Model:</div>
                   <div className="text-cyan-400">deepseek-r1</div>

                   <div className="text-slate-500">Local API:</div>
                   <div className="text-blue-400 underline decoration-blue-400/30 underline-offset-2">http://localhost:11435/v1</div>

                   <div className="text-slate-500">Key:</div>
                   <div className="text-purple-400 font-mono">sk-ollabridge-xY9kL2mN8...</div>
                </div>

                <div className="mt-4 pt-4 border-t border-slate-800/50">
                   <div className="text-slate-500 text-xs mb-1 uppercase tracking-wide">Join Command</div>
                   <div className="bg-slate-950 p-2 rounded border border-slate-800 text-slate-300 text-xs font-mono break-all">
                      ollabridge-node join --control http://localhost:11435 --token eyJ0eX...
                   </div>
                </div>
              </div>

              <div className="mt-4">
                <span className="text-green-500 font-bold mr-2">➜</span>
                <span className="text-blue-400 font-bold mr-2">~</span>
                <span className="animate-pulse inline-block w-2.5 h-5 bg-slate-500 align-middle"></span>
              </div>

            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const Architecture = () => {
  return (
    <section id="architecture" className="py-24 bg-slate-900 relative overflow-hidden">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">The Anti-Fragile Architecture</h2>
          <p className="text-slate-400 max-w-2xl mx-auto">
            Traditional setups require complex networking. OllaBridge flips the model: 
            compute nodes dial <span className="text-yellow-400 font-semibold">out</span> to the gateway.
          </p>
        </div>

        <div className="relative h-[400px] md:h-[500px] w-full bg-slate-950 rounded-2xl border border-slate-800 shadow-2xl flex items-center justify-center overflow-hidden">
          {/* Central Hub */}
          <div className="relative z-20 flex flex-col items-center">
            <div className="w-24 h-24 bg-slate-800 rounded-full border-2 border-yellow-400 flex items-center justify-center shadow-[0_0_30px_rgba(250,204,21,0.2)] z-20">
              <img 
                src="https://raw.githubusercontent.com/ruslanmv/ollabridge/refs/heads/master/assets/logo.svg" 
                alt="Logo" 
                className="h-12 w-12" 
              />
            </div>
            <div className="mt-4 bg-slate-800 px-4 py-1 rounded-full border border-slate-700 text-xs font-mono text-yellow-400">
              Central Gateway
            </div>
          </div>

          {/* Nodes */}
          {/* Node 1: Laptop */}
          <div className="absolute top-10 left-10 md:top-20 md:left-32 flex flex-col items-center z-20">
            <div className="w-16 h-16 bg-slate-800 rounded-xl border border-slate-600 flex items-center justify-center">
              <Laptop className="text-blue-400 w-8 h-8" />
            </div>
            <span className="text-slate-400 text-xs mt-2">Local Laptop (NAT)</span>
          </div>

          {/* Node 2: Colab */}
          <div className="absolute top-10 right-10 md:top-20 md:right-32 flex flex-col items-center z-20">
            <div className="w-16 h-16 bg-slate-800 rounded-xl border border-slate-600 flex items-center justify-center">
              <Code className="text-orange-400 w-8 h-8" />
            </div>
            <span className="text-slate-400 text-xs mt-2">Google Colab</span>
          </div>

          {/* Node 3: Cloud GPU */}
          <div className="absolute bottom-10 flex flex-col items-center z-20">
            <div className="w-16 h-16 bg-slate-800 rounded-xl border border-slate-600 flex items-center justify-center">
              <Server className="text-green-400 w-8 h-8" />
            </div>
            <span className="text-slate-400 text-xs mt-2">Private Cloud</span>
          </div>

          {/* Connecting Lines (SVG Overlay) */}
          <svg className="absolute inset-0 w-full h-full pointer-events-none z-10">
            {/* Defs for gradients */}
            <defs>
              <linearGradient id="line-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#334155" />
                <stop offset="50%" stopColor="#fbbf24" />
                <stop offset="100%" stopColor="#334155" />
              </linearGradient>
            </defs>

            {/* Paths would ideally be calculated dynamically based on positions, simplified here for demo */}
            {/* Line to Laptop */}
            <path d="M 120 120 L 50% 50%" stroke="url(#line-gradient)" strokeWidth="2" strokeDasharray="5,5" className="animate-pulse opacity-50" />
            
            {/* Line to Colab */}
            <path d="M calc(100% - 120px) 120 L 50% 50%" stroke="url(#line-gradient)" strokeWidth="2" strokeDasharray="5,5" className="animate-pulse opacity-50" />

            {/* Line to Server */}
            <path d="M 50% calc(100% - 100px) L 50% 50%" stroke="url(#line-gradient)" strokeWidth="2" strokeDasharray="5,5" className="animate-pulse opacity-50" />
          </svg>
          
          {/* Floating Particles (Simulating Data Packets) */}
          <div className="absolute inset-0 overflow-hidden pointer-events-none">
             <div className="absolute top-[28%] left-[28%] w-2 h-2 bg-yellow-400 rounded-full shadow-[0_0_10px_#facc15] animate-ping"></div>
             <div className="absolute top-[28%] right-[28%] w-2 h-2 bg-yellow-400 rounded-full shadow-[0_0_10px_#facc15] animate-ping delay-75"></div>
             <div className="absolute bottom-[28%] left-[50%] w-2 h-2 bg-yellow-400 rounded-full shadow-[0_0_10px_#facc15] animate-ping delay-150"></div>
          </div>

        </div>
      </div>
    </section>
  );
};

const CodeIntegration = () => {
  const [activeTab, setActiveTab] = useState('python');

  const codeSnippets = {
    python: `from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA"
)

# Use it exactly like OpenAI
response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Explain quantum computing"}]
)

print(response.choices[0].message.content)`,
    javascript: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:11435/v1",
  apiKey: process.env.OLLABRIDGE_KEY
});

const completion = await client.chat.completions.create({
  model: "deepseek-r1",
  messages: [{ role: "user", content: "Hello!" }]
});

console.log(completion.choices[0].message);`,
    curl: `curl -X POST http://localhost:11435/v1/chat/completions \\
  -H "Authorization: Bearer sk-ollabridge-..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "deepseek-r1",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`
  };

  return (
    <section className="py-24 bg-slate-950 border-t border-slate-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col lg:flex-row gap-12 items-center">
        
        <div className="lg:w-1/2">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-6">
            Drop-in <span className="text-yellow-400">OpenAI Compatibility</span>
          </h2>
          <p className="text-slate-400 text-lg mb-8">
            Don't rewrite your codebase. OllaBridge mimics the OpenAI API standard perfectly. Whether you're using LangChain, Vercel AI SDK, or raw cURL, it just works.
          </p>
          
          <ul className="space-y-4">
            {[
              "Works with LangChain & LlamaIndex",
              "Streaming support out of the box",
              "Compatible with AutoGen and CrewAI",
              "Zero code changes, just swap the URL"
            ].map((item, idx) => (
              <li key={idx} className="flex items-center text-slate-300">
                <CheckCircle className="w-5 h-5 text-yellow-400 mr-3" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        <div className="lg:w-1/2 w-full">
          <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
              <div className="flex space-x-2">
                <button 
                  onClick={() => setActiveTab('python')}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${activeTab === 'python' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}
                >
                  python
                </button>
                <button 
                  onClick={() => setActiveTab('javascript')}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${activeTab === 'javascript' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}
                >
                  node.js
                </button>
                <button 
                  onClick={() => setActiveTab('curl')}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${activeTab === 'curl' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}
                >
                  curl
                </button>
              </div>
              <div className="flex items-center text-slate-500 hover:text-white cursor-pointer" title="Copy code">
                 <Copy className="w-4 h-4" />
              </div>
            </div>
            <div className="p-6 overflow-x-auto">
              <pre className="text-sm font-mono text-slate-300">
                <code>
                  {codeSnippets[activeTab]}
                </code>
              </pre>
            </div>
          </div>
        </div>

      </div>
    </section>
  );
};

const Features = () => {
  const features = [
    {
      icon: <Globe className="w-6 h-6 text-yellow-400" />,
      title: "Universal Endpoint",
      desc: "One https URL for all your fragmented models. Stop juggling localhost IP addresses."
    },
    {
      icon: <Shield className="w-6 h-6 text-yellow-400" />,
      title: "NAT & Firewall Traversal",
      desc: "Connect home GPUs or office workstations without touching router settings or VPNs."
    },
    {
      icon: <Lock className="w-6 h-6 text-yellow-400" />,
      title: "Secure by Default",
      desc: "End-to-end TLS encryption, API key management, and rate limiting built-in."
    },
    {
      icon: <Network className="w-6 h-6 text-yellow-400" />,
      title: "Load Balancing",
      desc: "Distribute traffic across multiple GPUs. If one node dies, traffic routes to the next."
    },
    {
      icon: <Code className="w-6 h-6 text-yellow-400" />,
      title: "Colab Integration",
      desc: "Run a free T4 GPU on Google Colab and expose it as a persistent API in 2 lines of code."
    },
    {
      icon: <Cpu className="w-6 h-6 text-yellow-400" />,
      title: "MCP Server Built-in",
      desc: "Agents can control your infrastructure. Create tokens, list nodes, and check health via MCP."
    }
  ];

  return (
    <section id="features" className="py-24 bg-slate-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">Why Developers Choose OllaBridge</h2>
          <p className="text-slate-400 max-w-2xl mx-auto">
            Infrastructure headaches shouldn't stop you from shipping AI apps.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {features.map((feature, index) => (
            <div key={index} className="p-8 bg-slate-950 rounded-2xl border border-slate-800 hover:border-yellow-400/50 transition-all duration-300 group">
              <div className="w-12 h-12 bg-slate-900 rounded-lg flex items-center justify-center mb-6 group-hover:scale-110 transition-transform border border-slate-800 group-hover:border-yellow-400/30">
                {feature.icon}
              </div>
              <h3 className="text-xl font-bold text-white mb-3">{feature.title}</h3>
              <p className="text-slate-400 leading-relaxed">
                {feature.desc}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

const CTA = () => {
  return (
    <section className="py-24 bg-gradient-to-br from-slate-900 to-slate-950 relative overflow-hidden">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-yellow-400 to-transparent opacity-50"></div>
      
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center relative z-10">
        <h2 className="text-4xl md:text-5xl font-extrabold text-white mb-6">
          Stop paying cloud tokens. <br />
          <span className="text-yellow-400">Use your own compute.</span>
        </h2>
        <p className="text-xl text-slate-400 mb-10">
          Join thousands of developers routing requests to local machines and Colab instances. Open source and production ready.
        </p>
        
        <div className="flex flex-col sm:flex-row justify-center gap-4">
          <button className="bg-yellow-400 hover:bg-yellow-500 text-slate-900 px-8 py-4 rounded-lg font-bold text-lg transition-all shadow-lg transform hover:-translate-y-1">
            Get Started Now
          </button>
          <button className="bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 px-8 py-4 rounded-lg font-bold text-lg transition-all flex items-center justify-center gap-2">
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
            </svg>
            Star on GitHub
          </button>
        </div>
      </div>
    </section>
  );
};

const Footer = () => {
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
            <span className="text-slate-500 text-sm ml-2">© 2024</span>
          </div>
          
          <div className="flex space-x-6">
            <a href="#" className="text-slate-400 hover:text-white transition-colors">Documentation</a>
            <a href="#" className="text-slate-400 hover:text-white transition-colors">Twitter</a>
            <a href="#" className="text-slate-400 hover:text-white transition-colors">GitHub</a>
            <a href="#" className="text-slate-400 hover:text-white transition-colors">License (MIT)</a>
          </div>
        </div>
        
        <div className="mt-8 text-center md:text-left">
            <a href="https://github.com/ruslanmv/ollabridge" className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs text-slate-400 hover:border-slate-600 transition-colors">
              <div className="w-2 h-2 rounded-full bg-green-500"></div>
              <span>System Operational</span>
            </a>
        </div>
      </div>
    </footer>
  );
};

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 font-sans selection:bg-yellow-400 selection:text-black">
      <Navbar />
      <Hero />
      <Architecture />
      <Features />
      <CodeIntegration />
      <CTA />
      <Footer />
    </div>
  );
}