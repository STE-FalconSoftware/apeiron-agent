// The live mod (hooks/live.tsx) against a fake editor: `claude plugin test sdk/claude-plugin/plugins/apeiron`.
//
// The fake answers `ngine.call` with the editor's real reply texts (copied from a live editor,
// 2026-10-03), so a change in how the mod parses them shows up here. What this does NOT cover:
// the real bridge/relay, a real undo stack, and the paint of any surface.

import { describe, expect, test } from 'claude-code/testing'

const SURFACES = ['terminal', 'desktop'] as const
const AGENT_TOOL = 'mcp__plugin_apeiron_ngine__ngine_call'

type Fake = {
  undoable: number
  calls: string[]
  undos: number
}

function fakeEditor(): Fake {
  return { undoable: 0, calls: [], undos: 0 }
}

function text(t: string, isError = false) {
  return { value: { content: [{ type: 'text', text: t }], isError } }
}

function answer(f: Fake, op: string, args: Record<string, unknown>) {
  f.calls.push(op)
  switch (op) {
    case 'editor.context':
      return text("Editor context:\n- location: in a scene — level 'main'\n- play state: edit\n- mode: select\n- selection: e7v0, e6v0")
    case 'scene.selection':
      return text('2 selected — primary e6v0; set: e7v0, e6v0\nnames: e7v0 "Moss_Ball", e6v0 "Rock_07"')
    case 'ui.follow_agent':
      return text('reading agent presence (the reply below carries it).\n[applied] ui.follow_agent: {"running_job":null}')
    case 'camera.get':
      return text('{"eye":[6.07,4.79,6.92],"target":[0.00,0.90,0.00],"fov_deg":60.0}')
    case 'agents.list':
      return text(`[applied] agents.list: {"conversations":[{"conv":"s-1","is_you":true,"undoable":${f.undoable}}]}`)
    case 'edit.undo':
      if (f.undoable === 0) return text('nothing to undo — the undo stack is empty', true)
      f.undoable -= 1
      f.undos += 1
      return text("undid 'place actor' in conversation s-1's history")
    default:
      return text(`ok ${op}`)
  }
}

function wire(on: Parameters<Parameters<typeof test>[1] & ((...a: never[]) => unknown)>[1], f: Fake, seen: { context: string[] }) {
  on('mcp.connect', ($, e) =>
    e.server === 'ngine'
      ? { value: { isConnected: true, server: 'plugin:apeiron:ngine' } }
      : { value: { isConnected: false, reason: 'unlisted', message: 'not this plugin' } },
  )
  on('mcp.call', ($, e) => answer(f, String(e.args.op), (e.args.args ?? {}) as Record<string, unknown>))
  // The agent's own editor calls: each one that edits pushes one undo entry.
  on('tool.call', ($, e) => {
    const op = String((e as unknown as { op?: unknown }).op ?? '')
    if (op.startsWith('place.') || op.startsWith('scene.set')) f.undoable += 1
    return { result: { content: [{ type: 'text', text: `ok ${op}` }] } as never, text: `ok ${op}` }
  })
  on('prompt.submit', ($, e) => {
    seen.context = [...(e.context ?? [])]
    return { text: e.text, context: e.context }
  })
  on('turn.complete', ($, e) => ({ text: e.text }) as never)
  on('ui.status', () => ({ value: undefined }) as never)
  on('ui.toast', () => ({ value: undefined }) as never)
  on('session.append', ($, e) => ({ message: e.message, uuid: 'u1' }) as never)
}

function bandProps() {
  return {
    hasSurvey: false,
    isWorking: false,
    maxRows: 6,
    bodyColumns: 120,
    scroll: { offset: 0, bodyRows: 6 },
    view: {},
  } as never
}

async function agentTurn($: Parameters<Parameters<typeof test>[1] & ((...a: never[]) => unknown)>[0], prompt: string, edits: number) {
  await $.prompt.submit({ text: prompt, asUser: true })
  for (let i = 0; i < edits; i++) {
    await $.tool.call({ tool: AGENT_TOOL, op: 'place.actor', args: { kind: 'cube' } } as never)
  }
  await $.turn.complete({ answer: 'done', durationMs: 10, isAborted: false, turnId: 't1', reason: 'answer', category: null, explanation: null, text: 'done' } as never)
}

describe('apeiron live mod', () => {
  test('a prompt carries the selection by name, primary first, and the camera', async ($, on) => {
    const f = fakeEditor()
    const seen = { context: [] as string[] }
    wire(on, f, seen)
    // The band stays dark (and nothing is called) until the agent has reached the editor.
    await $.tool.call({ tool: AGENT_TOOL, op: 'scene.describe', args: {} } as never)
    await $.prompt.submit({ text: 'make this bigger', asUser: true })
    const ctx = seen.context.join('\n')
    expect(ctx).toContain('Rock_07 (e6v0), Moss_Ball (e7v0)')
    expect(ctx).toContain('level: main')
    expect(ctx).toContain('looking at [0, 0.9, 0]')
  })

  test('nothing is called before the agent reaches the editor (the bridge would launch it)', async ($, on) => {
    const f = fakeEditor()
    const seen = { context: [] as string[] }
    wire(on, f, seen)
    await $.prompt.submit({ text: 'hello', asUser: true })
    expect(f.calls).toEqual([])
    expect(seen.context.join('')).not.toContain('Apeiron editor')
  })

  for (const surface of SURFACES) {
    test(`the band names the selection and offers Undo turn on ${surface}`, async ($, on) => {
      const f = fakeEditor()
      const seen = { context: [] as string[] }
      wire(on, f, seen)
      await $.tool.call({ tool: AGENT_TOOL, op: 'scene.describe', args: {} } as never)
      await agentTurn($, 'scatter three cubes', 3)

      const band = await $.ui.mount({ plugin: 'apeiron', surface, component: 'AbovePrompt', props: bandProps() })
      expect(await band.find({ text: /Rock_07, Moss_Ball/ })).toBeTruthy()
      expect(await band.find({ text: /3 edits/ })).toBeTruthy()

      await band.press({ key: 'undo' })
      expect(f.undos).toBe(3) // exactly the turn's edits, on the agent's own history
      expect(f.undoable).toBe(0)
      expect(await band.find({ text: /reverted/ })).toBeTruthy()
    })
  }

  test('Undo turn steps back only the turn, not edits from before it', async ($, on) => {
    const f = fakeEditor()
    const seen = { context: [] as string[] }
    wire(on, f, seen)
    await $.tool.call({ tool: AGENT_TOOL, op: 'place.actor', args: {} } as never) // before the turn
    await agentTurn($, 'two cubes', 2)
    const band = await $.ui.mount({ plugin: 'apeiron', surface: 'terminal', component: 'AbovePrompt', props: bandProps() })
    expect(await band.find({ text: /2 edits/ })).toBeTruthy()
    await band.press({ key: 'undo' })
    expect(f.undos).toBe(2)
    expect(f.undoable).toBe(1)
  })

  test('an editor tool row reads as an action and the editor answer, not JSON', async ($, on) => {
    const f = fakeEditor()
    wire(on, f, { context: [] })
    const row = await $.ui.mount({
      plugin: 'apeiron',
      surface: 'terminal',
      component: 'ToolUse',
      props: {
        tool_use_id: 'tu1',
        tool: AGENT_TOOL,
        input: { op: 'place.actor', args: { kind: 'cube', name: 'Rock_07' } },
        isRunning: false,
        isErrored: false,
        isInterrupted: false,
        output: [{ type: 'text', text: 'placed cube e6v0\nmore detail' }],
      } as never,
    })
    expect(await row.find({ text: /Place actor/ })).toBeTruthy()
    expect(await row.find({ text: /name Rock_07/ })).toBeTruthy()
    expect(await row.find({ text: /placed cube e6v0/ })).toBeTruthy()
    expect(await row.find({ text: /more detail/ })).toBeFalsy()
    expect(await row.find({ type: 'Text', text: /^place$/ })).toBeFalsy() // the domain is not repeated after its own verb
  })
})
