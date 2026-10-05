/** Whether the editor answers, and through which MCP server (`plugin:<plugin>:ngine` or `...:apeiron-web`). */
export type Link = {
  state: 'unknown' | 'live' | 'down'
  server?: string
  message?: string
}

export type Picked = { id: string; name: string; kind?: string }

export type Job = { op: string; done: number; total: number; phase?: string }

/** One read of the running editor: what the band draws and what a prompt carries. */
export type EditorSnap = {
  level?: string
  play?: string
  mode?: string
  selection: Picked[]
  selectionCount: number
  job: Job | null
  camera?: { eye: number[]; target: number[] }
  at: number
}

/** What the agent's last turn did to the scene, counted on its own undo history. */
export type TurnEdits = {
  edits: number
  ops: string[]
  prompt: string
  undone: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'apeiron-web': {
      link: Link
      editor: EditorSnap | null
      lastTurn: TurnEdits | null
      isBandHidden: boolean
    }
  }
}
