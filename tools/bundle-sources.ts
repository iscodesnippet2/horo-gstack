// Prints, as JSON, the node_modules package directories whose files end up in
// gstack's diagram-render bundle: the bundle rebuilt from the same entry with a
// source map, which names every input file. Run with lib/diagram-render as the
// working directory after `bun install --frozen-lockfile --ignore-scripts`.
const r = await Bun.build({
  entrypoints: ["src/entry.ts"],
  target: "browser",
  minify: true,
  sourcemap: "external",
  define: { __BUNDLE_INFO_DEPS__: "{}", "process.env.NODE_ENV": '"production"' },
});
if (!r.success) {
  for (const log of r.logs) console.error(log);
  process.exit(1);
}
const { sources } = JSON.parse(await r.outputs.find(o => o.kind === "sourcemap")!.text());
const dirs = new Set<string>();
for (const s of sources as string[]) {
  const m = s.match(/^.*node_modules\/(?:@[^/]+\/)?[^/]+/);
  if (m) dirs.add(m[0].replace(/^(\.\.\/)+/, ""));
}
console.log(JSON.stringify([...dirs].sort()));
