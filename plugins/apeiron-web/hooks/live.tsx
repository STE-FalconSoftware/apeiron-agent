// Apeiron Engine, live in Claude Code.
//
// Four things, one module, both plugins (`apeiron` reaches the installed editor through the
// `ngine` bridge, `apeiron-web` the browser editor through the relay; the mod calls whichever
// this plugin's manifest lists):
//   1. A band above the prompt: the editor's level, play state, selection and the agent's
//      running job, live.
//   2. Selection-aware prompts: "make THIS bigger" carries what is selected and where the
//      camera looks, so the agent never asks which one.
//   3. Readable editor tool rows: `ngine.call {op,args}` drawn as an action and the editor's
//      own one-line answer, not JSON.
//   4. Undo turn: the agent's last turn counted on its own undo history, reverted with one key,
//      and the model told it happened.
//
// It never launches an editor by itself: the installed plugin's bridge auto-launches on any
// tools/call, so the mod stays quiet until the agent (or the person, via Connect) has reached
// a live editor.

import type { Engine, Register } from 'claude-code'

import type { EditorSnap, Job, Link, Picked, TurnEdits } from '../types'

const LINK = { plugin: 'apeiron-web', key: 'link' } as const
const EDITOR = { plugin: 'apeiron-web', key: 'editor' } as const
const LAST_TURN = { plugin: 'apeiron-web', key: 'lastTurn' } as const
const BAND_HIDDEN = { plugin: 'apeiron-web', key: 'isBandHidden' } as const

// The MCP server keys the two shipping plugins use, in the order tried.
const SERVER_KEYS = ['ngine', 'apeiron-web']
// `mcp__<server>__ngine_call` / `..._batch` however the client spells the dot.
const NGINE_TOOL = /^mcp__.+__ngine[._](call|batch)$/
const POLL_MS = 2000

type Reply = { ok: boolean; text: string; data: Record<string, unknown> | undefined }

// Module state: a hot reload starts it over, which is fine (it only caches and counts).
const S = {
  server: undefined as string | undefined,
  polling: false,
  turnBaseline: null as number | null,
  turnOps: [] as string[],
  turnPrompt: '',
  names: new Map<string, Picked>(),
}

// ---------------------------------------------------------------- state

async function getLink($: Engine): Promise<Link> {
  return (await $.state.get(LINK)).value ?? { state: 'unknown' }
}

async function getEditor($: Engine): Promise<EditorSnap | null> {
  return (await $.state.get(EDITOR)).value ?? null
}

async function getLastTurn($: Engine): Promise<TurnEdits | null> {
  return (await $.state.get(LAST_TURN)).value ?? null
}

async function getBandHidden($: Engine): Promise<boolean> {
  return (await $.state.get(BAND_HIDDEN)).value ?? false
}

async function setLink($: Engine, next: Link) {
  const cur = await getLink($)
  if (cur.state === next.state && cur.message === next.message && cur.server === next.server) return
  await $.state.set(LINK, next)
  $.ui.status(next.state === 'down' ? 'Apeiron: editor not connected' : undefined)
}

// ---------------------------------------------------------------- the editor door

async function resolveServer($: Engine): Promise<string | undefined> {
  if (S.server) return S.server
  for (const key of SERVER_KEYS) {
    try {
      const got = await $.mcp.connect(key)
      if (got.isConnected) {
        S.server = got.server
        return S.server
      }
    } catch {
      // not this plugin's key
    }
  }
  return undefined
}

async function call($: Engine, op: string, args: Record<string, unknown> = {}): Promise<Reply> {
  const name = await resolveServer($)
  if (!name) return { ok: false, text: 'no Apeiron MCP server in this plugin', data: undefined }
  try {
    const r = await $.mcp.call(name, 'ngine.call', { op, args })
    const text = (r.content ?? [])
      .filter(b => b.type === 'text' && typeof b.text === 'string')
      .map(b => b.text as string)
      .join('\n')
    const sc = (r as { structuredContent?: Record<string, unknown> }).structuredContent
    const data = sc && typeof sc.json === 'object' && sc.json !== null
      ? (sc.json as Record<string, unknown>)
      : { ...(jsonIn(text) ?? {}), ...(sc ?? {}) }
    return { ok: !r.isError, text, data }
  } catch (err) {
    return { ok: false, text: String(err), data: undefined }
  }
}

// ---------------------------------------------------------------- reading the editor

// `editor.context` is `- key: value` lines; keep the few the band and the prompt need.
function contextField(text: string, key: string): string | undefined {
  const m = text.match(new RegExp(`^- ${key}: (.+)$`, 'mi'))
  return m ? m[1].trim() : undefined
}

async function nameOf($: Engine, id: string): Promise<Picked> {
  const hit = S.names.get(id)
  if (hit) return hit
  const r = await call($, 'scene.inspect', { entity: id })
  // The first line is `Entity e6v0 "Rock_07"`; an unnamed entity keeps its token.
  const quoted = firstLine(r.text).match(/"([^"]{1,64})"/)
  const one: Picked = { id, name: quoted ? quoted[1].trim() : id }
  if (r.ok) S.names.set(id, one)
  return one
}

async function readEditor($: Engine): Promise<EditorSnap | null> {
  const [ctx, sel, follow, cam] = await Promise.all([
    call($, 'editor.context'),
    call($, 'scene.selection'),
    call($, 'ui.follow_agent'),
    call($, 'camera.get'),
  ])
  if (!ctx.ok && !sel.ok) {
    const down = /not running|no editor|503|not connected|refused|ECONN/i.test(ctx.text)
    await setLink($, { state: down ? 'down' : 'unknown', server: S.server, message: firstLine(ctx.text) })
    return null
  }
  await setLink($, { state: 'live', server: S.server })

  // `N selected — primary e6v0; set: e7v0, e6v0` then, on engines that have it, a
  // `names: e7v0 "Moss_Ball", e6v0 "Rock_07"` line. Primary first; older engines cost one
  // scene.inspect per shown entity for its name.
  const primary = sel.text.match(/primary (e\d+v\d+)/)?.[1]
  const set = (sel.text.match(/set: ([^\n—]+)/)?.[1] ?? '').match(/e\d+v\d+/g) ?? []
  const count = sel.ok ? Number(sel.text.match(/^(\d+) selected/)?.[1] ?? set.length) : 0
  const ordered = primary ? [primary, ...set.filter(t => t !== primary)] : set
  const namesLine = sel.text.match(/^names: (.+)$/m)?.[1]
  const named = new Map<string, string>()
  for (const m of (namesLine ?? '').matchAll(/(e\d+v\d+) "([^"]*)"/g)) named.set(m[1], m[2])
  const shown = ordered.slice(0, 3)
  const selection = await Promise.all(
    shown.map(id => (namesLine !== undefined ? { id, name: named.get(id) ?? id } : nameOf($, id))),
  )

  const running = follow.data?.running_job as Job | null | undefined
  const eye = cam.data?.eye as number[] | undefined
  const target = cam.data?.target as number[] | undefined

  const location = contextField(ctx.text, 'location') ?? ''
  const level = /^LAUNCHER/.test(location)
    ? 'launcher (no project open)'
    : location.match(/level '([^']+)'/)?.[1] ?? (location || undefined)

  const snap: EditorSnap = {
    level,
    play: contextField(ctx.text, 'play state') ?? contextField(ctx.text, 'play'),
    mode: contextField(ctx.text, 'mode'),
    selection,
    selectionCount: count,
    job: running && running.total ? running : null,
    camera: eye && target ? { eye, target } : undefined,
    at: Date.now(),
  }
  await $.state.set(EDITOR, snap)
  return snap
}

async function undoableNow($: Engine): Promise<number | null> {
  const r = await call($, 'agents.list')
  const convs = (r.data?.conversations as Array<{ is_you?: boolean; undoable?: number }> | undefined) ?? []
  const me = convs.find(c => c.is_you)
  return r.ok && me ? Number(me.undoable ?? 0) : null
}

async function poll($: Engine) {
  if (S.polling) return
  if ((await getLink($)).state !== 'live') return
  S.polling = true
  try {
    await readEditor($)
  } finally {
    S.polling = false
  }
}

// A person's gesture: allowed to wake the bridge (and so launch the installed editor).
async function connect($: Engine): Promise<string> {
  const snap = await readEditor($)
  if (!snap) {
    const l = await getLink($)
    return `Apeiron editor not reachable: ${l.message ?? 'no answer'}`
  }
  return `Apeiron editor connected: ${snap.level ?? 'scene'} · ${snap.play ?? 'edit'} · ${snap.selectionCount} selected`
}

function promptContext(snap: EditorSnap): string {
  const lines = ['Apeiron editor, as the person submitted this prompt:']
  if (snap.level) lines.push(`- level: ${snap.level}`)
  if (snap.play) lines.push(`- play state: ${snap.play}`)
  if (snap.selectionCount === 0) {
    lines.push('- selection: nothing selected')
  } else {
    const list = snap.selection.map(p => `${p.name} (${p.id}${p.kind ? `, ${p.kind}` : ''})`).join(', ')
    const rest = snap.selectionCount - snap.selection.length
    lines.push(`- selection (primary first): ${list}${rest > 0 ? ` and ${rest} more (scene.selection lists all)` : ''}`)
  }
  if (snap.camera) {
    const f = (v: number[]) => v.map(n => Math.round(n * 100) / 100).join(', ')
    lines.push(`- camera: eye [${f(snap.camera.eye)}] looking at [${f(snap.camera.target)}]`)
  }
  lines.push(
    'When the prompt says "this", "these", "it" or "the selected ...", it means the selection above; "here" means the camera target. Do not ask which entity.',
  )
  return lines.join('\n')
}

// The turn's edits are counted on the agent's OWN undo history (agents.list `undoable` for this
// conversation), so Undo turn steps exactly those back with per-conversation edit.undo — never the
// person's edits or another agent's, even ones made in the middle of the turn.
async function endTurn($: Engine): Promise<TurnEdits | null> {
  const now = await undoableNow($)
  const edits = now === null || S.turnBaseline === null ? 0 : Math.max(0, now - S.turnBaseline)
  if (edits === 0) return null
  return { edits, ops: S.turnOps.slice(-40), prompt: S.turnPrompt, undone: false }
}

async function undoTurn($: Engine) {
  const turn = await getLastTurn($)
  if (!turn || turn.undone) return
  let undid = 0
  for (let i = 0; i < turn.edits; i++) {
    const r = await call($, 'edit.undo')
    if (!r.ok) break
    undid += 1
  }
  await $.state.set(LAST_TURN, { ...turn, undone: true, edits: undid })
  $.ui.toast(undid === turn.edits ? `Reverted the agent's last turn (${undid} edits)` : `Reverted ${undid} of ${turn.edits} edits`)
  // The model must not believe its edits still stand.
  try {
    await $.session.append({
      message: {
        type: 'user',
        content: [{
          type: 'text',
          text: `[Apeiron] The person pressed "Undo turn" in Claude Code: ${undid} of your editor edits from the turn answering "${turn.prompt.slice(0, 120)}" were reverted on your undo history. The scene no longer has them; re-read it before building on that work.`,
        }],
      },
    })
  } catch {
    // headless or refused: the toast already told the person
  }
  void readEditor($)
}

async function keepTurn($: Engine) {
  await $.state.set(LAST_TURN, null)
}

// ---------------------------------------------------------------- hooks

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'editor',
      description: 'Connect to the Apeiron editor and show what it has open',
    })
    $.clock.every(POLL_MS, () => void poll($))
    // The web relay never launches anything, so it is safe to look right away.
    const name = await resolveServer($)
    if (name && /apeiron-web/.test(name)) void readEditor($)
    return next(e)
  })

  on('command.run', { command: 'editor' }, async $ => ({ text: await connect($) }))

  // The agent's own editor calls: the first good answer turns the band on, and the op names
  // feed the turn summary.
  on('tool.call', async ($, e, next) => {
    if (!NGINE_TOOL.test(e.tool)) return next(e)
    const input = e as unknown as { op?: unknown }
    S.turnOps.push(typeof input.op === 'string' ? input.op : e.tool.endsWith('batch') ? 'batch' : 'call')
    const ran = await next(e)
    const failed = ran.deny !== undefined || (ran as { isError?: boolean }).isError === true
    if (!failed && (await getLink($)).state !== 'live') {
      await setLink($, { state: 'live', server: S.server })
      // The editor may have just launched, so this conversation's history began empty.
      if (S.turnBaseline === null) S.turnBaseline = 0
      void readEditor($)
    }
    return ran
  })

  // 2. Selection-aware prompts.
  on('prompt.submit', async ($, e, next) => {
    S.turnOps = []
    S.turnPrompt = e.text
    S.turnBaseline = null
    if ((await getLink($)).state !== 'live') return next(e)
    const snap = (await readEditor($)) ?? (await getEditor($))
    S.turnBaseline = await undoableNow($)
    if (!snap) return next(e)
    return next({ ...e, context: [...(e.context ?? []), promptContext(snap)] })
  })

  // 4. Undo turn: count the turn's edits on the agent's own undo history.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if ((await getLink($)).state === 'live' && S.turnBaseline !== null) {
      const turn = await endTurn($)
      if (turn) {
        await $.state.set(LAST_TURN, turn)
        await $.state.set(BAND_HIDDEN, false)
      }
      void readEditor($)
    }
    S.turnBaseline = null
    return result
  })

  // 1. The band above the prompt.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const l = await getLink($)
    if (e.props.hasSurvey || l.state === 'unknown' || (await getBandHidden($))) return next(e)
    const snap = await getEditor($)
    const turn = await getLastTurn($)
    const { Box, Text, Button } = $.ui.resolve(e)

    if (l.state === 'down') {
      return (
        <Box flexDirection="row" gap={1}>
          <Text color="yellow">○ Apeiron</Text>
          <Text dimColor wrap="truncate">editor not connected</Text>
          <Button key="connect" label="Connect" hotkey="c" plain onPress={() => void connect($)} />
        </Box>
      )
    }

    const picked = snap?.selectionCount ?? 0
    const sel = !snap || picked === 0
      ? 'nothing selected'
      : `${picked} selected: ${snap.selection.map(p => p.name).join(', ')}${picked > snap.selection.length ? ', …' : ''}`
    const job = snap?.job ?? null

    return (
      <Box flexDirection="column" width={e.props.bodyColumns}>
        <Box flexDirection="row" gap={1}>
          <Text color="cyan" bold>◆ Apeiron</Text>
          <Text color="green">●</Text>
          <Text wrap="truncate">{snap?.level ?? 'editor'}</Text>
          {snap?.play ? <Text dimColor>· {snap.play}</Text> : null}
          <Text dimColor>·</Text>
          <Text color={picked ? 'magenta' : undefined} dimColor={!picked} wrap="truncate">
            ▸ {sel}
          </Text>
        </Box>
        {job ? (
          <Box flexDirection="row" gap={1}>
            <Text color="cyan">⟳</Text>
            <Text>{humanOp(job.op)}</Text>
            <Text color="cyan">{progressBar(job.done / Math.max(1, job.total), 12)}</Text>
            <Text dimColor>{job.done}/{job.total}{job.phase ? ` · ${job.phase}` : ''}</Text>
          </Box>
        ) : null}
        {turn && turn.edits > 0 && !e.props.isWorking ? (
          turn.undone ? (
            <Text dimColor>↶ Last turn reverted ({turn.edits} edits)</Text>
          ) : (
            <Box flexDirection="row" gap={1}>
              <Text color="yellow">✎</Text>
              <Text>Last turn changed the scene: {turn.edits} edit{turn.edits === 1 ? '' : 's'}</Text>
              <Text dimColor wrap="truncate">
                ({summarizeOps(turn.ops)})
              </Text>
              <Button key="undo" label="Undo turn" hotkey="u" variant="primary" onPress={() => void undoTurn($)} />
              <Button key="keep" label="Keep" hotkey="k" plain onPress={() => void keepTurn($)} />
            </Box>
          )
        ) : null}
      </Box>
    )
  })

  // 3. Readable editor tool rows.
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (!NGINE_TOOL.test(e.props.tool)) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const input = (e.props.input ?? {}) as { op?: unknown; args?: unknown; ops?: unknown }
    const isBatch = /batch$/.test(e.props.tool)
    const op = isBatch ? 'batch' : String(input.op ?? 'call')
    const steps = isBatch && Array.isArray(input.ops) ? (input.ops as Array<{ op?: unknown }>) : []
    const title = isBatch ? `${steps.length} editor actions` : humanOp(op)
    const detail = isBatch ? summarizeOps(steps.map(s => String(s?.op ?? '?'))) : argHint(input.args)
    const answer = firstLine(outputText(e.props.output))
    const mark = e.props.isRunning ? '…' : e.props.isErrored ? '✗' : e.props.isInterrupted ? '■' : '◆'
    const color = e.props.isErrored ? 'red' : e.props.isRunning ? 'cyan' : 'green'

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" gap={1}>
          <Text color={color}>{mark}</Text>
          <Text bold>{title}</Text>
          {isBatch || !domainOf(op) ? null : <Text dimColor>{domainOf(op)}</Text>}
          {detail ? <Text dimColor wrap="truncate">{detail}</Text> : null}
        </Box>
        {answer && !e.props.isRunning ? (
          <Box paddingLeft={2}>
            <Text color={e.props.isErrored ? 'red' : undefined} dimColor={!e.props.isErrored} wrap="truncate">
              ⎿ {answer}
            </Text>
          </Box>
        ) : null}
      </Box>
    )
  })
}

// ---------------------------------------------------------------- text helpers

const VERB: Record<string, string> = {
  spawn: 'Spawn', place: 'Place', set: 'Set', get: 'Read', add: 'Add', remove: 'Remove', delete: 'Delete',
  despawn: 'Remove', select: 'Select', describe: 'Describe', inspect: 'Inspect', query: 'Query',
  screenshot: 'Screenshot', frame: 'Frame', duplicate: 'Duplicate', rename: 'Rename', group: 'Group',
  undo: 'Undo', redo: 'Redo', apply: 'Apply', revert: 'Revert', capture: 'Capture', save: 'Save',
}

// `scene.set_transform` -> "Set transform"; `place.actor` -> "Place actor" (the domain IS the verb);
// `render.gpu_timings` -> "Gpu timings" with the domain shown beside it.
function humanOp(op: string): string {
  const dot = op.indexOf('.')
  const domain = dot >= 0 ? op.slice(0, dot) : ''
  const words = (dot >= 0 ? op.slice(dot + 1) : op).split('_')
  if (VERB[words[0]]) return [VERB[words[0]], ...words.slice(1)].join(' ')
  if (VERB[domain]) return [VERB[domain], ...words].join(' ')
  return [cap(words[0]), ...words.slice(1)].join(' ')
}

// The domain, unless humanOp already spoke it as the verb.
function domainOf(op: string): string {
  const dot = op.indexOf('.')
  if (dot < 0) return ''
  const domain = op.slice(0, dot)
  return VERB[domain] && !VERB[op.slice(dot + 1).split('_')[0]] ? '' : domain
}

function cap(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

function argHint(args: unknown): string {
  if (!args || typeof args !== 'object') return ''
  const a = args as Record<string, unknown>
  for (const k of ['name', 'asset', 'entity', 'path', 'preset', 'mode', 'field']) {
    if (typeof a[k] === 'string') return `${k} ${a[k]}`
  }
  const n = Object.keys(a).length
  return n ? `${n} arg${n === 1 ? '' : 's'}` : ''
}

function summarizeOps(ops: string[]): string {
  const counts = new Map<string, number>()
  for (const op of ops) {
    const k = humanOp(op).toLowerCase()
    counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  const shown = [...counts].slice(0, 4).map(([k, n]) => (n > 1 ? `${k} ×${n}` : k))
  return shown.join(', ') + (counts.size > 4 ? ', …' : '')
}

function outputText(out: unknown): string {
  if (out == null) return ''
  if (typeof out === 'string') return out
  if (Array.isArray(out)) {
    return out.map(b => (b && typeof b === 'object' && 'text' in b ? String((b as { text: unknown }).text) : '')).join('\n')
  }
  if (typeof out === 'object' && Array.isArray((out as { content?: unknown }).content)) {
    return outputText((out as { content: unknown }).content)
  }
  return ''
}

// Deferred ops answer `[applied] op: {json}` (or a lead line, then JSON): the object after the
// first brace, when it parses.
function jsonIn(text: string): Record<string, unknown> | undefined {
  const at = text.indexOf('{')
  if (at < 0) return undefined
  try {
    const v = JSON.parse(text.slice(at))
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : undefined
  } catch {
    return undefined
  }
}

function firstLine(s: string): string {
  return (s.split('\n').find(l => l.trim()) ?? '').trim()
}

function progressBar(fraction: number, cells: number): string {
  const n = Math.round(Math.min(1, Math.max(0, fraction)) * cells)
  return '█'.repeat(n) + '░'.repeat(cells - n)
}
