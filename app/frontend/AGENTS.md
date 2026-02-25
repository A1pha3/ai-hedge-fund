# app/frontend/

## OVERVIEW

React + ReactFlow node-based UI for building and executing hedge fund workflows. VSCode-style 3-panel layout with SSE streaming for real-time agent execution feedback.

## STRUCTURE

```
frontend/src/
├── App.tsx                 # Root wrapper
├── components/
│   ├── Layout.tsx          # 3-panel orchestrator (left/right/bottom + canvas)
│   ├── Flow.tsx            # ReactFlow canvas — auto-save, undo/redo, keyboard shortcuts
│   ├── layout/             # TopBar
│   ├── panels/
│   │   ├── left/           # Flow list, create/delete/rename flows
│   │   ├── right/          # Component palette (drag nodes onto canvas)
│   │   └── bottom/         # Output console with tabs (signals, trades, portfolio)
│   ├── tabs/               # Tab bar for multi-flow editing
│   ├── settings/           # API key management, model selection
│   └── ui/                 # shadcn/ui primitives (19 components)
├── contexts/
│   ├── flow-context.tsx    # Flow CRUD + node composition (single/multi-node)
│   ├── node-context.tsx    # Per-node status/messages with composite keys (flowId:nodeId)
│   └── layout-context.tsx  # Panel collapse state
├── hooks/
│   ├── use-node-state.ts   # ⚠️ UNUSUAL: Global singleton FlowStateManager class
│   ├── use-flow-connection.ts  # ⚠️ UNUSUAL: Global singleton FlowConnectionManager (SSE)
│   ├── use-flow-history.ts # Per-flow undo/redo with snapshot arrays
│   ├── use-flow-management.ts  # Flow CRUD orchestration
│   ├── use-enhanced-flow-actions.ts  # Extended flow operations
│   ├── use-flow-management-tabs.ts   # Tab-based flow switching
│   ├── use-resizable.ts    # Drag-to-resize panels
│   └── use-keyboard-shortcuts.ts
├── nodes/
│   ├── index.ts            # Node type registry
│   ├── types.ts            # Node type definitions
│   └── components/         # 6 node types (agent, portfolio-start, portfolio-manager, etc.)
├── services/
│   ├── api.ts              # SSE streaming for hedge fund execution
│   ├── backtest-api.ts     # SSE streaming for backtests
│   ├── flow-service.ts     # REST CRUD for flows
│   └── sidebar-storage.ts  # localStorage persistence
├── data/
│   ├── node-mappings.ts    # Node definitions from backend API
│   └── multi-node-mappings.ts  # Pre-configured node groups with edges
└── lib/
    └── utils.ts            # cn() helper (clsx + tailwind-merge)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add node type | `nodes/components/` + `nodes/index.ts` | Create component, register in nodeTypes |
| Add panel section | `components/panels/{left,right,bottom}/` | Follow existing panel patterns |
| Add API call | `services/` | SSE for streaming, REST for CRUD |
| Modify state management | `hooks/use-node-state.ts` | FlowStateManager singleton |
| Add keyboard shortcut | `hooks/use-keyboard-shortcuts.ts` | |
| Add UI component | `components/ui/` | Use shadcn/ui CLI or copy pattern |
| Modify flow save | `components/Flow.tsx` | 1s debounced auto-save |

## UNUSUAL PATTERNS

| Pattern | Standard React | This Project |
|---------|---------------|--------------|
| State management | Redux / Zustand | **Singleton manager classes** with Map + listener pattern |
| Flow isolation | URL params / context | **Composite key strings** (`flowId:nodeId`) |
| Node IDs | Sequential | `base_type` + 6-char random suffix |
| Auto-save | React Query mutations | Debounced callback in `Flow.tsx` |
| Undo/redo | Redux undo | Per-flow snapshot arrays in `use-flow-history.ts` |

## ANTI-PATTERNS

- **DO NOT** clear configuration state when loading flows — `useNodeState` handles flow isolation automatically
- **DO NOT** reset runtime data when loading flows — preserve all runtime state
- **DO NOT** restore `nodeContextData` on flow load — runtime execution data starts fresh, only configuration persists

## CONVENTIONS

- **Stack**: React 18 + Vite + TypeScript + Tailwind + shadcn/ui (Radix primitives)
- **Flow library**: `@xyflow/react` v12.5.1
- **Theme**: `next-themes` for dark/light mode
- **Styling**: Tailwind + `cn()` utility (clsx + tailwind-merge)
- **Backend**: expects FastAPI at `http://localhost:8000`
- **SSE events**: `start` → `progress` (per-agent) → `complete` | `error`
