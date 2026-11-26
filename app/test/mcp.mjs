// Test für den MCP-Server (soma mcp, mcp.py): Protokoll über stdio, die drei Werkzeuge, und vor allem die Zusagen, die
// ihn sicher machen — kein Argument trägt Code, einen Befehl oder einen Pfad; Export schreibt nur nach exports/; --read-only
// nimmt Bauen und Exportieren aus der Liste; was das Modell auf stdout druckt, stört das Protokoll nicht.
// Aufruf: npm run test:mcp (SOMA_PYTHON zeigt auf das Python mit cadquery).
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checker, cleanup } from './harness.mjs';

const t = checker();
const { check } = t;

const PY = process.env.SOMA_PYTHON || path.join(process.env.LOCALAPPDATA ?? '', 'soma-dev', 'venv', 'Scripts', 'python.exe');

// Ein Agent: schreibt JSON-Zeilen, wartet auf die Antwort mit derselben id. Nichts anderes spricht hier mit dem Server.
class Client {
  constructor(args, cwd) {
    this.child = spawn(PY, ['-m', 'soma', 'mcp', ...args], {
      cwd, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
    });
    this.next = 1;
    this.waiting = new Map();
    this.stderr = '';
    this.broken = null; // Zeile, die kein JSON war: das Protokoll ist dann kaputt
    let buf = '';
    this.child.stdout.on('data', (d) => {
      buf += d;
      for (let i = buf.indexOf('\n'); i >= 0; i = buf.indexOf('\n')) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line) continue;
        let msg;
        try { msg = JSON.parse(line); } catch { this.broken = line.slice(0, 120); continue; }
        const p = this.waiting.get(msg.id);
        if (p) { this.waiting.delete(msg.id); p(msg); }
      }
    });
    this.child.stderr.on('data', (d) => { this.stderr += d; });
  }

  request(method, params = {}, timeoutMs = 180000) {
    const id = this.next++;
    const msg = { jsonrpc: '2.0', id, method, params };
    return new Promise((resolve) => {
      const timer = setTimeout(() => { this.waiting.delete(id); resolve({ timeout: true }); }, timeoutMs);
      this.waiting.set(id, (m) => { clearTimeout(timer); resolve(m); });
      this.child.stdin.write(JSON.stringify(msg) + '\n');
    });
  }

  notify(method, params = {}) {
    this.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method, params }) + '\n');
  }

  stop() {
    this.child.stdin.end();
    this.child.kill();
  }
}

// Alle Eigenschaftsnamen eines Schemas, auch verschachtelt
function props(schema) {
  const out = [];
  for (const [name, spec] of Object.entries(schema.properties ?? {})) {
    out.push([name, spec]);
    if (spec.items) out.push(...props(spec.items));
  }
  return out;
}

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-mcp-'));
// print() im Modell: darf das Protokoll nicht kaputt machen
const MODEL = `import cadquery as cq
from soma import add_part, param
from soma.fasteners import Screw, Nut

print("building the probe model")   # absichtlich: der Server muss das nach stderr schicken
W = param(40.0, "Width", min=20, max=80, unit="mm")
plate = cq.Workplane().box(W, 30, 5).faces(">Z").workplane().hole(4)
lid = cq.Workplane().box(W, 30, 3).translate((0, 0, 8))
for i, x in enumerate((-10, 10), 1):
    s = Screw("ISO 4762", "M3x10", at=(x, 0), on=lid)
    plate = plate.cut(s.clearance_hole())
    add_part(f"Screw {i}", s, group="Hardware")
add_part("Nut", Nut("ISO 4032", "M3", at=(0, 0, 0), direction="+Z"), group="Hardware")
add_part("Plate", plate)
add_part("Lid", lid, group="Housing")
print("done")
`;

let client;
let ro;
try {
  fs.writeFileSync(path.join(dir, 'model.py'), MODEL);

  client = new Client(['--project', dir], dir);

  // 1) Handshake
  const init = await client.request('initialize', {
    protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '1' },
  });
  check('initialize: dieselbe Protokollfassung, Server "soma", Werkzeuge angekündigt',
    init.result?.protocolVersion === '2025-06-18' && init.result.serverInfo?.name === 'soma'
    && init.result.capabilities?.tools && !!init.result.instructions, JSON.stringify(init.result?.serverInfo));
  client.notify('notifications/initialized');

  // 2) Werkzeugliste
  const list = await client.request('tools/list');
  const tools = list.result?.tools ?? [];
  check('tools/list: vier Werkzeuge (build, inspect, bom, export)',
    tools.map((x) => x.name).join() === 'soma_build,soma_inspect,soma_bom,soma_export', tools.map((x) => x.name).join());

  // 3) Die Sicherheitszusagen, strukturell geprüft
  const FORBIDDEN = ['code', 'script', 'python', 'cmd', 'command', 'exec', 'execute', 'eval', 'shell', 'run',
    'source', 'snippet', 'path', 'file', 'filename', 'out', 'output', 'dir', 'folder', 'cwd', 'url', 'module'];
  const names = tools.flatMap((x) => props(x.inputSchema).map(([n]) => `${x.name}.${n}`));
  const bad = names.filter((n) => FORBIDDEN.includes(n.split('.').pop()));
  check('Kein Argument heißt code, script, command, path, file, dir …', bad.length === 0, bad.join(' ') || names.join(' '));
  const freeStrings = tools.flatMap((x) => props(x.inputSchema)
    .filter(([, s]) => s.type === 'string' && !s.enum).map(([n]) => `${x.name}.${n}`));
  check('Jedes Text-Argument hat eine feste Liste (enum): kein freier Text erreicht ein Werkzeug',
    freeStrings.length === 0, freeStrings.join(' '));
  const open = tools.filter((x) => x.inputSchema.additionalProperties !== false).map((x) => x.name);
  check('Jedes Schema verbietet unbekannte Argumente (additionalProperties: false)', open.length === 0, open.join());

  // 4) Messen
  const ins = await client.request('tools/call', { name: 'soma_inspect', arguments: {} });
  const doc = ins.result?.structuredContent;
  check('soma_inspect: Dokument mit Schema, Volumen und fünf Teilen',
    ins.result?.isError === false && doc?.schema === 'soma.inspect/1' && doc.totals.parts === 5
    && Math.abs(doc.parts.find((p) => p.name === 'Lid').volume - 3600) < 0.01, JSON.stringify(doc?.totals));
  check('soma_inspect: Textfassung als content, damit auch ein Agent ohne structuredContent etwas hat',
    /Volume\s+[\d.]+ mm³/.test(ins.result?.content?.[0]?.text ?? ''), (ins.result?.content?.[0]?.text ?? '').slice(0, 60));

  // 4b) Kosovnica: gekaufte Teile nach Oznaka, eigene mit Volumen
  const bm = await client.request('tools/call', { name: 'soma_bom', arguments: { density: 1.24 } });
  const bomDoc = bm.result?.structuredContent;
  check('soma_bom: zwei Schrauben als eine Zeile mit Anzahl 2, Mutter und zwei eigene Teile',
    bm.result?.isError === false && bomDoc?.schema === 'soma.bom/1' && bomDoc.purchased.length === 2
    && bomDoc.purchased.find((x) => x.designation === 'ISO 4762 M3x10')?.count === 2
    && bomDoc.manufactured.length === 2 && bomDoc.totals.purchased === 3,
    JSON.stringify(bomDoc?.purchased?.map((x) => `${x.designation}x${x.count}`)));
  check('soma_bom: Masse aus der Dichte, Textfassung mit beiden Tabellen',
    Math.abs(bomDoc.manufactured.find((x) => x.name === 'Lid').mass_g - 3600 * 1.24 / 1000) < 1e-3
    && /Purchased parts/.test(bm.result?.content?.[0]?.text ?? ''), String(bomDoc?.manufactured?.[0]?.mass_g));

  // 5) Ein Argument, das Code tragen könnte, wird abgelehnt
  const codeArg = await client.request('tools/call', { name: 'soma_inspect', arguments: { code: 'print(1)' } });
  check('soma_inspect mit "code": abgelehnt, unbekanntes Argument genannt',
    codeArg.result?.isError === true && /unknown argument/.test(codeArg.result.content[0].text)
    && /code/.test(codeArg.result.content[0].text), codeArg.result?.content?.[0]?.text?.slice(0, 80));
  const pathArg = await client.request('tools/call', {
    name: 'soma_export', arguments: { format: 'step', path: '../../etc/passwd' },
  });
  check('soma_export mit "path": abgelehnt — ein Zielpfad ist nicht vorgesehen',
    pathArg.result?.isError === true && /unknown argument/.test(pathArg.result.content[0].text),
    pathArg.result?.content?.[0]?.text?.slice(0, 80));

  // 6) Bauen (das Modell druckt dabei auf stdout)
  const build = await client.request('tools/call', { name: 'soma_build', arguments: {} });
  check('soma_build: ok, fünf Teile, kein kaputtes Protokoll trotz print() im Modell',
    build.result?.isError === false && build.result.structuredContent?.parts?.length === 5 && !client.broken,
    client.broken ?? build.result?.content?.[0]?.text?.slice(0, 80));
  check('Die Ausgabe des Modells landet auf stderr, nicht im Protokoll', /building the probe model/.test(client.stderr),
    client.stderr.trim().slice(0, 60));

  // 7) Exportieren: nur nach exports/
  const ex = await client.request('tools/call', { name: 'soma_export', arguments: { format: 'step' } });
  const files = ex.result?.structuredContent?.files ?? [];
  check('soma_export: zwei STEP-Dateien in exports/', ex.result?.isError === false && files.length === 2
    && files.every((f) => f.startsWith('exports/') && fs.existsSync(path.join(dir, f))), files.join(' '));
  const asm = await client.request('tools/call', { name: 'soma_export', arguments: { format: 'step', assembly: true } });
  check('soma_export assembly: eine Datei mit allen Teilen', asm.result?.isError === false
    && (asm.result.structuredContent?.files ?? []).length === 1, asm.result?.content?.[0]?.text?.slice(0, 60));
  const badFmt = await client.request('tools/call', { name: 'soma_export', arguments: { format: 'exe' } });
  check('soma_export mit format "exe": abgelehnt, Liste der Formate genannt',
    badFmt.result?.isError === true && /must be one of/.test(badFmt.result.content[0].text), badFmt.result?.content?.[0]?.text?.slice(0, 70));
  const meshOnly = await client.request('tools/call', {
    name: 'soma_export', arguments: { format: 'step', tolerance: 0.1 },
  });
  check('--tolerance nur für Netzformate: abgelehnt statt still ignoriert',
    meshOnly.result?.isError === true && /only apply to mesh formats/.test(meshOnly.result.content[0].text),
    meshOnly.result?.content?.[0]?.text?.slice(0, 70));

  // 8) Nichts außerhalb des Projekts geschrieben
  const stray = fs.readdirSync(os.tmpdir()).filter((f) => f.startsWith('passwd'));
  check('Kein Schreiben außerhalb des Projektordners', stray.length === 0, stray.join(' '));

  // 9) Unbekanntes Werkzeug, unbekannte Methode
  const unknownTool = await client.request('tools/call', { name: 'soma_shell', arguments: {} });
  check('Unbekanntes Werkzeug: JSON-RPC-Fehler -32602 mit der Liste der vorhandenen',
    unknownTool.error?.code === -32602 && /soma_inspect/.test(unknownTool.error.message), unknownTool.error?.message?.slice(0, 70));
  const unknownMethod = await client.request('resources/list');
  check('Unbekannte Methode: JSON-RPC-Fehler -32601', unknownMethod.error?.code === -32601, unknownMethod.error?.message);

  client.stop();

  // 10) --read-only: nur messen
  ro = new Client(['--project', dir, '--read-only'], dir);
  await ro.request('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 't', version: '1' } });
  const roList = await ro.request('tools/list');
  check('--read-only: nur messende Werkzeuge in der Liste', (roList.result?.tools ?? []).map((x) => x.name).join() === 'soma_inspect,soma_bom',
    (roList.result?.tools ?? []).map((x) => x.name).join());
  const roBuild = await ro.request('tools/call', { name: 'soma_build', arguments: {} });
  check('--read-only: soma_build ist unbekannt (nicht nur verboten)', roBuild.error?.code === -32602,
    roBuild.error?.message?.slice(0, 60));
  ro.stop();
} catch (e) {
  console.log('ABBRUCH:', e.message);
  t.fail();
}
client?.stop();
ro?.stop();
cleanup(dir);
console.log(t.fails ? `\n${t.fails} Prüfung(en) fehlgeschlagen` : '\nALLE PRÜFUNGEN BESTANDEN');
process.exit(t.fails ? 1 : 0);
