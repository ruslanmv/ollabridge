import React, { useEffect } from 'react';
import { BookOpen, CheckCircle, ChevronRight, KeyRound, Network, PlugZap, Shield, Terminal } from 'lucide-react';
import SiteNavbar from '../components/SiteNavbar.jsx';
import SiteFooter from '../components/SiteFooter.jsx';
import CodeWindow from '../components/CodeWindow.jsx';

const SectionTitle = ({ icon: Icon, overline, title, desc, id }) => (
  <div id={id} className="scroll-mt-28">
    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-yellow-400 text-xs font-semibold uppercase tracking-wide">
      {Icon ? <Icon className="w-3.5 h-3.5" /> : null}
      {overline}
    </div>
    <h2 className="mt-4 text-3xl md:text-4xl font-extrabold text-white tracking-tight">{title}</h2>
    {desc ? <p className="mt-3 text-slate-400 max-w-2xl">{desc}</p> : null}
  </div>
);

const Pill = ({ children }) => (
  <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-900 border border-slate-800 text-slate-200">
    {children}
  </span>
);

export default function Documentation({ initialSection = "" }) {
  const toc = [
    { id: 'quickstart', label: 'Quickstart' },
    { id: 'commands', label: 'CLI commands' },
    { id: 'nodes', label: 'Add GPU nodes' },
    { id: 'sdk', label: 'OpenAI SDK usage' },
    { id: 'docker', label: 'Docker usage' },
    { id: 'best-practices', label: 'Best practices' },
    { id: 'troubleshooting', label: 'Troubleshooting' },
  ];

  useEffect(() => {
    if (!initialSection) return;
    const el = document.getElementById(initialSection);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [initialSection]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 font-sans selection:bg-yellow-400 selection:text-black">
      <SiteNavbar />

      <header className="pt-28 pb-10 bg-slate-950 relative overflow-hidden">
        <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-15"></div>
        <div className="absolute left-0 right-0 top-0 -z-10 m-auto h-[340px] w-[340px] rounded-full bg-yellow-400 opacity-15 blur-[110px]"></div>

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3 text-slate-400 text-sm">
            <a href="#/" className="hover:text-white transition-colors">
              Home
            </a>
            <ChevronRight className="w-4 h-4" />
            <span className="text-slate-200">Documentation</span>
          </div>

          <div className="mt-6 flex items-start gap-4">
            <div className="w-12 h-12 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center">
              <BookOpen className="w-6 h-6 text-yellow-400" />
            </div>
            <div>
              <h1 className="text-4xl md:text-5xl font-extrabold text-white tracking-tight">OllaBridge Documentation</h1>
              <p className="mt-2 text-slate-400 max-w-2xl">
                A practical guide to install, start the gateway, attach GPU nodes, and use a single OpenAI-compatible API across
                all your compute.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Pill>OpenAI compatible</Pill>
                <Pill>No port forwarding</Pill>
                <Pill>Nodes dial out</Pill>
                <Pill>Works local + remote</Pill>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-24">
        <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-10">
          {/* TOC */}
          <aside className="hidden lg:block">
            <div className="sticky top-24 rounded-2xl border border-slate-800 bg-slate-950/60 backdrop-blur p-5">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">On this page</div>
              <nav className="mt-3 space-y-1">
                {toc.map((item) => (
                  <a
                    key={item.id}
                    href={`#/docs?section=${item.id}`}
                    className="flex items-center justify-between px-3 py-2 rounded-lg text-sm text-slate-300 hover:text-white hover:bg-slate-900 transition-colors"
                  >
                    <span>{item.label}</span>
                    <span className="text-slate-600">#</span>
                  </a>
                ))}
              </nav>
            </div>
          </aside>

          {/* Content */}
          <div className="space-y-16">
            {/* Quickstart */}
            <section>
              <SectionTitle
                id="quickstart"
                icon={PlugZap}
                overline="Quickstart"
                title="Start a gateway in ~60 seconds"
                desc="Install, start, copy your API key, and you’re ready to use any OpenAI SDK or toolchain."
              />

              <div className="mt-8 grid grid-cols-1 xl:grid-cols-2 gap-8">
                <CodeWindow
                  title="Install"
                  subtitle="local machine"
                  code={`pip install ollabridge`}
                />

                <CodeWindow
                  title="Start the gateway"
                  subtitle="prints URL + key + join token"
                  code={`ollabridge start\n\n# Gateway online at http://localhost:11435\n# Local OpenAI base_url: http://localhost:11435/v1`}
                />
              </div>

              <div className="mt-8 rounded-2xl border border-slate-800 bg-slate-950/60 p-6">
                <div className="flex items-start gap-3">
                  <KeyRound className="w-5 h-5 text-yellow-400 mt-0.5" />
                  <div>
                    <h3 className="text-lg font-bold text-white">What you get after start</h3>
                    <p className="mt-1 text-slate-400">
                      When you run <span className="font-mono text-slate-200">ollabridge start</span>, it prints:
                    </p>
                    <ul className="mt-3 space-y-2 text-slate-300">
                      <li className="flex gap-2">
                        <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                        <span>
                          A local gateway URL (default <span className="font-mono">http://localhost:11435</span>)
                        </span>
                      </li>
                      <li className="flex gap-2">
                        <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                        <span>An API key you pass as an OpenAI key</span>
                      </li>
                      <li className="flex gap-2">
                        <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                        <span>A node join token + example join command for remote GPUs</span>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
            </section>

            {/* Commands */}
            <section>
              <SectionTitle
                id="commands"
                icon={Terminal}
                overline="CLI"
                title="Commands you’ll use most"
                desc="OllaBridge ships two entry points: the gateway controller and the node client."
              />

              <div className="mt-8 grid grid-cols-1 xl:grid-cols-2 gap-8">
                <div className="space-y-4">
                  <h3 className="text-xl font-bold text-white">Gateway (control plane)</h3>
                  <p className="text-slate-400">
                    Start and manage the gateway that exposes an OpenAI-compatible API endpoint.
                  </p>
                  <CodeWindow
                    title="ollabridge"
                    subtitle="common subcommands"
                    code={`# Start the gateway (auto-installs Ollama / models if needed)\nollabridge start\n\n# Show current gateway status\nollabridge status\n\n# Stop the gateway\nollabridge stop\n\n# Show configuration / paths (if available in your build)\nollabridge config --help`}
                  />
                </div>

                <div className="space-y-4">
                  <h3 className="text-xl font-bold text-white">Nodes (compute clients)</h3>
                  <p className="text-slate-400">
                    Join extra machines (laptop, workstation, Colab, cloud) to your gateway. Nodes dial out to the gateway, so
                    they work behind NAT/firewalls.
                  </p>
                  <CodeWindow
                    title="ollabridge-node"
                    subtitle="join a gateway"
                    code={`# Join a gateway (use the command printed by 'ollabridge start')\nollabridge-node join \\\n  --control http://YOUR_GATEWAY_IP:11435 \\\n  --token eyJ0eXAi...\n\n# Tip: if you use a public domain, prefer HTTPS\nollabridge-node join --control https://gateway.example.com --token eyJ0eXAi...`}
                  />
                </div>
              </div>
            </section>

            {/* Nodes */}
            <section>
              <SectionTitle
                id="nodes"
                icon={Network}
                overline="Distributed compute"
                title="Add a GPU node (Colab, workstation, cloud)"
                desc="Run this on the remote machine. The node will auto-install prerequisites if needed and then connect back to your gateway."
              />

              <div className="mt-8 grid grid-cols-1 xl:grid-cols-2 gap-8">
                <CodeWindow
                  title="Remote machine"
                  subtitle="Linux/macOS/Windows (WSL)"
                  code={`pip install ollabridge\n\n# Paste the join command from gateway startup\nollabridge-node join --control http://YOUR_GATEWAY_IP:11435 --token eyJ0eXAi...`}
                />

                <CodeWindow
                  title="Google Colab"
                  subtitle="run in a notebook cell"
                  code={`!pip -q install ollabridge\n!ollabridge-node join --control https://your-gateway.com --token eyJ0eXAi...`}
                />
              </div>

              <div className="mt-8 rounded-2xl border border-slate-800 bg-slate-950/60 p-6">
                <div className="flex items-start gap-3">
                  <Shield className="w-5 h-5 text-yellow-400 mt-0.5" />
                  <div>
                    <h3 className="text-lg font-bold text-white">Security note</h3>
                    <p className="mt-1 text-slate-400">
                      Treat the join token like a password. Use HTTPS for public gateways, rotate tokens/keys when sharing access, and
                      avoid posting tokens in logs or screenshots.
                    </p>
                  </div>
                </div>
              </div>
            </section>

            {/* SDK */}
            <section>
              <SectionTitle
                id="sdk"
                icon={PlugZap}
                overline="SDK"
                title="Use with the OpenAI SDK"
                desc="Point the OpenAI client at your gateway's /v1 endpoint and use the key printed on startup."
              />

              <div className="mt-8 grid grid-cols-1 xl:grid-cols-2 gap-8">
                <CodeWindow
                  title="Python"
                  subtitle="openai SDK"
                  code={`from openai import OpenAI\n\nclient = OpenAI(\n    base_url="http://localhost:11435/v1",\n    api_key="sk-ollabridge-..."\n)\n\nresp = client.chat.completions.create(\n    model="deepseek-r1",\n    messages=[{"role": "user", "content": "Hello!"}]\n)\n\nprint(resp.choices[0].message.content)`}
                />

                <CodeWindow
                  title="curl"
                  subtitle="OpenAI-compatible REST"
                  code={`curl http://localhost:11435/v1/chat/completions \\\n  -H "Authorization: Bearer sk-ollabridge-..." \\\n  -H "Content-Type: application/json" \\\n  -d '{
    "model": "deepseek-r1",
    "messages": [{"role": "user", "content": "Say hi"}]
  }'`}
                />
              </div>
            </section>

            {/* Scenarios */}
            <section>
              <SectionTitle
                id="scenarios"
                icon={Network}
                overline="Scenarios"
                title="Common usage patterns"
                desc="These are the most popular ways people deploy OllaBridge in practice."
              />

              <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-6">
                {[
                  {
                    title: 'Home gaming PC as your “GPU cloud”',
                    desc: 'Join your desktop GPU to a gateway so your laptop can use it from anywhere.',
                    cmd: 'ollabridge-node join --control https://your-gateway.com --token ...',
                  },
                  {
                    title: 'Free Colab GPU for burst compute',
                    desc: 'Attach a Colab session as a node; if it dies, start a new one—your app URL stays the same.',
                    cmd: '!ollabridge-node join --control https://your-gateway.com --token ...',
                  },
                  {
                    title: 'Team-wide gateway in a VPC',
                    desc: 'Expose one internal OpenAI base_url; let OllaBridge load-balance across multiple nodes.',
                    cmd: 'ollabridge start  # on a small control-plane VM',
                  },
                  {
                    title: 'Hybrid: local + remote routing',
                    desc: 'Keep a fast local model for dev and a bigger remote model for heavy jobs; same API surface.',
                    cmd: 'client = OpenAI(base_url="http://gateway/v1", api_key="...")',
                  },
                ].map((s) => (
                  <div key={s.title} className="p-6 bg-slate-950 rounded-2xl border border-slate-800">
                    <h3 className="text-lg font-bold text-white">{s.title}</h3>
                    <p className="mt-2 text-slate-400">{s.desc}</p>
                    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/40 p-3 font-mono text-xs text-slate-200">
                      {s.cmd}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* Best practices */}
            <section>
              <SectionTitle
                id="best-practices"
                icon={Shield}
                overline="Best practices"
                title="Production-ready defaults"
                desc="A short checklist that keeps your gateway stable, secure, and easy to operate."
              />

              <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="p-6 bg-slate-950 rounded-2xl border border-slate-800">
                  <h3 className="text-lg font-bold text-white">Security</h3>
                  <ul className="mt-3 space-y-2 text-slate-300">
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Use HTTPS when exposing a gateway publicly.</span>
                    </li>
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Rotate API keys / join tokens if shared.</span>
                    </li>
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Keep join tokens out of logs and screenshots.</span>
                    </li>
                  </ul>
                </div>

                <div className="p-6 bg-slate-950 rounded-2xl border border-slate-800">
                  <h3 className="text-lg font-bold text-white">Reliability</h3>
                  <ul className="mt-3 space-y-2 text-slate-300">
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Run the gateway on a small always-on machine/VM.</span>
                    </li>
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Attach multiple nodes for failover and load balancing.</span>
                    </li>
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Prefer stable model names in your app config.</span>
                    </li>
                  </ul>
                </div>

                <div className="p-6 bg-slate-950 rounded-2xl border border-slate-800">
                  <h3 className="text-lg font-bold text-white">Performance</h3>
                  <ul className="mt-3 space-y-2 text-slate-300">
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Keep nodes close (region-wise) to reduce latency.</span>
                    </li>
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Reserve a small local model for fast iterations.</span>
                    </li>
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Use multiple GPUs/nodes for higher throughput.</span>
                    </li>
                  </ul>
                </div>

                <div className="p-6 bg-slate-950 rounded-2xl border border-slate-800">
                  <h3 className="text-lg font-bold text-white">Operational hygiene</h3>
                  <ul className="mt-3 space-y-2 text-slate-300">
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Document your base_url + key distribution for teammates.</span>
                    </li>
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Use a process manager (systemd, Docker, etc.) in production.</span>
                    </li>
                    <li className="flex gap-2">
                      <CheckCircle className="w-4 h-4 text-green-400 mt-0.5" />
                      <span>Keep your gateway host updated and locked down.</span>
                    </li>
                  </ul>
                </div>
              </div>
            </section>

            {/* Troubleshooting */}
            <section>
              <SectionTitle
                id="troubleshooting"
                icon={Shield}
                overline="Help"
                title="Troubleshooting"
                desc="The most common gotchas and how to fix them."
              />

              <div className="mt-8 space-y-6">
                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-6">
                  <h3 className="text-lg font-bold text-white">Gateway starts but requests fail</h3>
                  <p className="mt-2 text-slate-400">
                    Double-check your <span className="font-mono text-slate-200">base_url</span> ends with{' '}
                    <span className="font-mono text-slate-200">/v1</span> and that you’re sending the printed API key.
                  </p>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-6">
                  <h3 className="text-lg font-bold text-white">Remote node can’t connect</h3>
                  <p className="mt-2 text-slate-400">
                    Ensure the gateway URL is reachable from the node (public IP/DNS for internet nodes). If exposing publicly,
                    prefer HTTPS and allow outbound traffic from the node environment.
                  </p>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-6">
                  <h3 className="text-lg font-bold text-white">Model not found</h3>
                  <p className="mt-2 text-slate-400">
                    Confirm the model name your client requests matches what your gateway/node has available. Start with the model
                    printed by the gateway on startup.
                  </p>
                </div>
              </div>

              <div className="mt-10 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-6 rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 to-slate-950">
                <div>
                  <div className="text-white font-bold text-lg">Ready to run your first request?</div>
                  <div className="text-slate-400">Jump back to Quickstart and copy/paste the examples.</div>
                </div>
                <a
                  href="#quickstart"
                  className="inline-flex items-center gap-2 bg-yellow-400 hover:bg-yellow-500 text-slate-900 px-5 py-3 rounded-lg font-bold transition-all"
                >
                  Go to Quickstart
                  <ChevronRight className="w-4 h-4" />
                </a>
              </div>
            </section>
          </div>
        </div>
      </main>

      <SiteFooter />
    </div>
  );
}
