/* AIM preview only: a fake supabase client with sample data, so the page can be seen without signing in.
   Served by aim_preview/preview.py in place of the supabase-js script. window.__mock.ctl(id, data) and
   window.__mock.msg(row) push live changes like realtime does. */
(function () {
  const now = Date.now(), M = 60e3;
  const conv = "c" + (now - 40 * M), gconv = "g" + (now - 15 * M);
  const tool = (o) => JSON.stringify(o);
  const store = {
    conversations: [
      { id: conv, title: "Purchase summary swipe actions", project: "shop-app", created_at: new Date(now - 40 * M).toISOString() },
      { id: "c" + (now - 2e8), title: "AIM step cards", project: ".aim", created_at: new Date(now - 2e8).toISOString() },
      { id: gconv, title: "Review the checkout design", project: "gpt-work", created_at: new Date(now - 15 * M).toISOString() },
    ],
    messages: [
      { id: "m1-me", sender: "me", kind: "command", text: "Restore SaleStatusResponse and keep only ticketViewUrl", ts: now - 30 * M, seen: true, conv },
      { id: "m2-c", sender: "claude", kind: "tool", text: tool({ t: "Bash", title: "Show the original SaleStatusResponse and ev_api diff", in: "$ git diff main -- lib/models/sale_status_response.dart", out: "@@ -12,6 +12,7 @@\n+  final String? ticketViewUrl;" }), ts: now - 29 * M, conv },
      { id: "m3-c", sender: "claude", kind: "reply", text: "I'm restoring the original `SaleStatusResponse` with only `ticketViewUrl` added, and removing the duplicate endpoint, method and import I put in `ev_api`.", ts: now - 28 * M, conv },
      { id: "m4-c", sender: "claude", kind: "tool", text: tool({ t: "Bash", title: "Restore SaleStatusResponse with added field", in: "$ git checkout main -- lib/models/sale_status_response.dart", out: "" }), ts: now - 27 * M, conv },
      { id: "m5-c", sender: "claude", kind: "reply", text: "The model fields are back to original with `ticketViewUrl` added, but the import fix removed the wrong line and left it out of order. I'll move it back to its proper position.", ts: now - 26 * M, conv },
      { id: "m6-c", sender: "claude", kind: "tool", text: tool({ t: "Edit", title: "Edited ev_api.dart", in: "lib/api/ev_api.dart\n\n- import 'package:dio/dio.dart';\n+ import '../models/sale_status_response.dart';", out: "", diff: 1, add: 1, del: 1 }), ts: now - 25 * M, conv },
      { id: "m7-c", sender: "claude", kind: "tool", text: tool({ t: "Bash", title: "Format the touched files", in: "$ dart format lib/api/ev_api.dart", out: "Formatted 1 file (0 changed)" }), ts: now - 24.5 * M, conv },
      { id: "m8-c", sender: "claude", kind: "reply", text: "Both fixes are in place, with only the added `ticketViewUrl` field and receipt endpoint changes. Now I'll re-run analyze on the touched files.", ts: now - 24 * M, conv },
      { id: "m9-c", sender: "claude", kind: "tool", text: (JSON.stringify({"t": "Write", "title": "Created p6.py", "in": "C:/Users/demo/p6.py\n\nimport io\np = r\"C:/x/index.html\"\ns = io.open(p, encoding=\"utf-8\").read()\n\n\ndef rep(a, b):\n    global s\n    assert s.count(a) == 1\n    s = s.replace(a, b)\n", "out": "", "add": 29, "del": 0})), ts: now - 3 * M, conv },
      { id: "m10-c", sender: "claude", kind: "tool", text: (JSON.stringify({"t": "Bash", "title": "Applying confirm UI patch and syntax check", "in": "$ cd ~/aim-launcher && python p6.py && node --check index.html", "out": "ok\njs parses"})), ts: now - 2 * M, conv },
      { id: "m11-c", sender: "claude", kind: "tool", text: (JSON.stringify({"t": "Edit", "title": "Edited ev_api.dart", "in": "lib/api/ev_api.dart\n\n- import 'package:dio/dio.dart';\n+ import '../models/sale_status_response.dart';", "out": "", "diff": 1, "add": 1, "del": 1})), ts: now - 1 * M, conv },
      { id: "g1-me", sender: "me", kind: "command", text: "Review the checkout design and add an integration test for refunds", ts: now - 14 * M, seen: true, conv: gconv },
      { id: "g2-gk", sender: "claude", kind: "tool", text: tool({ t: "Reasoning", title: "Copying the project tree", in: "", out: "I'll copy the tree into a scratch folder first so the capture can run against a stable snapshot." }), ts: now - 13 * M, conv: gconv },
      { id: "g3-g", sender: "claude", kind: "reply", text: "The existing missing-eligibility check still matters. I'm retaining it: a later Sale update can stay in the group only when committed history or an earlier prepared job supplies affirmative eligibility. I'll test that excluded and no-report results cannot manufacture it.", ts: now - 12 * M, conv: gconv },
      { id: "g4-gk", sender: "claude", kind: "tool", text: tool({ t: "Command", title: "npm test -- staged-history", in: "$ npm test -- staged-history", out: "PASS staged-history.integration.js (4 tests)", code: 0 }), ts: now - 11 * M, conv: gconv },
      { id: "g5-gk", sender: "claude", kind: "tool", text: tool({ t: "FileChange", kind: "add", title: "/Users/demo/projects/shop-api/tests/staged-history.integration.js", in: "/Users/demo/projects/shop-api/tests/staged-history.integration.js\n\n+ const { capture } = require('./capture');\n+ \n+ test('excluded results cannot manufacture eligibility', () => {\n+   expect(capture([{ excluded: true }]).eligible).toBe(false);\n+ });", out: "", diff: 1, add: 5, del: 0 }), ts: now - 10 * M, conv: gconv },
      { id: "g6-gk", sender: "claude", kind: "tool", text: tool({ t: "Read", title: "capture.js", in: "$ sed -n 1,80p capture.js", out: "module.exports.capture = ..." }), ts: now - 9 * M, conv: gconv },
      { id: "g7-gk", sender: "claude", kind: "tool", text: tool({ t: "Command", title: "node capture.js --check", in: "$ node capture.js --check", out: "Error: source sequence mismatch\nexit code 1", code: 1 }), ts: now - 8 * M, conv: gconv },
      { id: "g8-gk", sender: "claude", kind: "tool", text: tool({ t: "FileChange", kind: "update", title: "/Users/demo/projects/shop-api/tests/capture.js", in: "/Users/demo/projects/shop-api/tests/capture.js\n\n  function align(a, b) {\n-   return a.seq === b.seq;\n+   return a.sourceSeq === b.sourceSeq;\n  }", out: "", diff: 1, add: 1, del: 1 }), ts: now - 7 * M, conv: gconv },
    ],
    control: {
      "gpt-models": { host: "MY-PC", dir: "gpt-work", model: "gpt-6-astra", effort: "xhigh", sandbox: "workspace-write", sandboxes: ["read-only", "workspace-write"], list: [{ slug: "gpt-6.1-sol", name: "GPT 6.1 Sol", efforts: ["low", "medium", "high", "xhigh", "max", "ultra"], def: "low" }, { slug: "gpt-6-astra", name: "GPT 6 Astra", efforts: ["low", "medium", "high", "xhigh", "max", "ultra"], def: "low" }, { slug: "gpt-6-luna", name: "GPT 6 Luna", efforts: ["low", "medium", "high", "xhigh", "max"], def: "medium" }] },
      "status-gpt": { state: "working", activity: "Aligning target source sequence", stepAt: now - 42e3, updatedAt: new Date().toISOString() },
      "watcher-gpt": { at: new Date().toISOString(), ts: now },
      settings: { lang: new URLSearchParams(location.search).get("lang") || "en", mode: "on" },
      status: { state: "working", activity: "", project: "shop-app", updatedAt: new Date().toISOString() },
      watcher: { at: new Date().toISOString(), ts: now },
      current: { conv, gpt: gconv },
      step: { text: "Running new and existing purchase summary tests", at: now - 19 * M - 37e3, conv },
      tasks: { list: [{ id: "t1", title: "flutter test test/purchase_summary_test.dart", at: now - 19 * M }, { id: "t2", title: "Analyze touched files", at: now - 3 * M }], conv },
      pc: { at: new Date().toISOString(), cpu: 45, ram: 89, gpu: 28, battery: 100, plugged: true, use5h: 9, useWeek: 60 },
      model: { ok: true, same: true, model: "Opus 5.5", effort: "Medium", level: 1, levels: 6, sessions: [{ title: "Phone", status: "Idle", folder: "" }, { title: "שינויים באפליקציית AIM", status: "Running", folder: ".aim" }, { title: "Purchase summary swipe actions", status: "Unread response", folder: "shop-app" }, { title: "Jarvis plan", status: "Idle", folder: "shop-app" }], title: "שינויים באפליקציית AIM", mode: "Auto", modes: ["Auto", "Manual", "Accept edits", "Plan"], efforts: ["Low", "Medium", "High", "Extra", "Max", "Ultracode"], models: [{ name: "Opus 5.5", note: "" }, { name: "Sonnet 5.5", note: "" }, { name: "Fable 5.1", note: "credits" }, { name: "Haiku 5.5", note: "" }] },
      commands: { list: [{ name: "phone-off", desc: "Turn the AIM phone line off" }, { name: "code-review", desc: "Review the current changes for bugs" }, { name: "simplify", desc: "Clean up the changed code" }] },
    },
  };
  const subs = [];
  const emit = (table, row, ev) => subs.forEach((s) => { if (s.table === table) s.cb({ eventType: ev || "INSERT", new: row, old: {} }); });

  class Q {
    constructor(t) { this.t = t; this.f = []; this.op = "select"; this.lim = 0; this.ord = null; }
    select() { return this; } eq(k, v) { this.f.push((r) => r[k] === v); return this; } neq(k, v) { this.f.push((r) => r[k] !== v); return this; }
    like() { return this; } ilike(k, v) { const s = v.replace(/%/g, "").toLowerCase(); this.f.push((r) => (r[k] || "").toLowerCase().includes(s)); return this; }
    not() { return this; } in() { return this; } is() { return this; } gt() { return this; } lt() { return this; }
    order(k, o) { this.ord = [k, !o || o.ascending !== false]; return this; } limit(n) { this.lim = n; return this; }
    maybeSingle() { this.one = true; return this; } single() { this.one = true; return this; }
    insert(r) { this.op = "insert"; this.p = r; return this; } update(r) { this.op = "update"; this.p = r; return this; }
    upsert(r) { this.op = "upsert"; this.p = r; return this; } delete() { this.op = "delete"; return this; }
    run() {
      if (this.t === "control") {
        const rows = Object.entries(store.control).map(([id, data]) => ({ id, data }));
        if (this.op === "upsert") { [].concat(this.p).forEach((r) => { store.control[r.id] = r.data; emit("control", r, "UPDATE"); }); return { data: null, error: null }; }
        const d = rows.filter((r) => this.f.every((f) => f(r)));
        return { data: this.one ? d[0] || null : d, error: null };
      }
      const list = store[this.t] || [];
      if (this.op === "insert" || this.op === "upsert") { [].concat(this.p).forEach((r) => { list.push(r); emit(this.t, r); }); return { data: null, error: null }; }
      let d = list.filter((r) => this.f.every((f) => f(r)));
      if (this.op === "update") { d.forEach((r) => { Object.assign(r, this.p); emit(this.t, r, "UPDATE"); }); return { data: null, error: null }; }
      if (this.op === "delete") { store[this.t] = list.filter((r) => !d.includes(r)); return { data: null, error: null }; }
      if (this.ord) { const [k, asc] = this.ord; d = d.slice().sort((a, b) => ((a[k] > b[k]) - (a[k] < b[k])) * (asc ? 1 : -1)); }
      if (this.lim) d = d.slice(0, this.lim);
      return { data: this.one ? d[0] || null : d, error: null };
    }
    then(res, rej) { return Promise.resolve(this.run()).then(res, rej); }
  }
  const session = { user: { email: "preview@aim" } };
  const client = {
    from: (t) => new Q(t),
    auth: {
      getSession: async () => ({ data: { session } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      signInWithPassword: async () => ({}), signOut: async () => ({}), signUp: async () => ({}),
    },
    channel: () => {
      const ch = { on: (_e, cfg, cb) => { subs.push({ table: cfg.table, cb }); return ch; }, subscribe: () => ch, unsubscribe() {} };
      return ch;
    },
    removeChannel() {},
    storage: { from: () => ({ createSignedUrls: async () => ({ data: [] }), download: async () => ({ data: null }), upload: async () => ({}) }) },
  };
  window.supabase = { createClient: () => client };
  window.__mock = {
    store,
    ctl: (id, data) => { store.control[id] = data; emit("control", { id, data }, "UPDATE"); },
    msg: (row) => { store.messages.push(row); emit("messages", row); },
  };
})();
