const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(
  path.join(__dirname, '..', 'workflows', 'sop-run.js'),
  'utf8',
).replace(/^export (?=const meta)/m, '')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const execute = new AsyncFunction(
  'args', 'budget', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'workflow',
  `"use strict";\n${source}`,
)

const material = (name, content = `# ${name}\nverified content 驗證`) => ({
  path: `/attested/${name}.md`,
  sha256: crypto.createHash('sha256').update(content, 'utf8').digest('hex'),
  content,
})

function validBundle(reviewers = 3) {
  const materials = {}
  for (const name of [
    'rules', 'design', 'planPrompt', 'reviewPrompt', 'goalPrompt',
    'goalChecklist', 'knowledge', 'spec',
  ]) materials[name] = material(name)
  return {
    schemaVersion: 2,
    generatedBy: 'sop-preflight.py/v2',
    generatedAt: new Date().toISOString(),
    task: 'test-task',
    sageRoot: '/verified/repo',
    sourceHead: 'b'.repeat(40),
    reviewers,
    materials,
    codegraph: { status: 'current' },
    stitchRequired: false,
    r5_human_verification: 'pending',
    merge_authorized: false,
  }
}

function validPlan() {
  return {
    files: [{ path: 'app.py', role: 'implementation', action: 'modify' }],
    depsDirection: 'interface -> implementation',
    executionOrder: ['update implementation', 'run tests'],
    assumptions: [],
    ambiguities: [],
    routeSuggestion: 'B',
    routeWhy: 'bounded change',
  }
}

function validReview(prompt) {
  const match = prompt.match(/lens field:\n([^\n]+)/)
  return {
    lens: match ? match[1] : 'missing',
    findings: [],
    noProblemDimensions: ['reviewed dimension is clean'],
  }
}

function validAggregate() {
  return {
    agreements: ['implementation is bounded'],
    divergences: [],
    topRisks: ['regression risk'],
  }
}

function validGoal() {
  return {
    goalConditions: [{
      id: 'HANDOFF.md-exists',
      command: 'test -s HANDOFF.md',
      passCriterion: 'exit code 0',
    }],
    failBreakers: ['stop on any nonzero gate'],
    humanGates: ['Human must perform R5 verification'],
    gateChecklist: [1, 2, 3, 4, 5, 6].map(number => ({
      gate: `GATE-${number}`,
      autoSatisfiable: number !== 5,
      note: `gate ${number} evidence`,
    })),
    tokenCap: 10000,
    maxTurns: 8,
  }
}

async function baseAgent(prompt, options) {
  if (options.label === 'plan') return validPlan()
  if (options.label.startsWith('review#')) return validReview(prompt)
  if (options.label === 'aggregate') return validAggregate()
  if (options.label === 'goal-draft') return validGoal()
  throw new Error(`unexpected label ${options.label}`)
}

async function runWorkflow({ args = { bundle: validBundle() }, handler, parallel } = {}) {
  const calls = []
  const logs = []
  const phases = []
  const agent = async (prompt, options) => {
    calls.push(options.label)
    return handler ? handler(prompt, options, baseAgent) : baseAgent(prompt, options)
  }
  const parallelFn = parallel || (tasks => Promise.all(tasks.map(taskFn => taskFn())))
  const result = await execute(
    JSON.stringify(args),
    {},
    agent,
    parallelFn,
    () => {},
    value => phases.push(value),
    value => logs.push(value),
    () => {},
  )
  return { result, calls, logs, phases }
}

test('unverified spec paths stop before any agent', async () => {
  const { result, calls } = await runWorkflow({
    args: { task: 'unsafe', sageRoot: '/missing', specFile: '/missing/spec.md' },
  })
  assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
  assert.deepEqual(calls, [])
  assert.equal(result.r5_human_verification, 'pending')
  assert.equal(result.merge_authorized, false)
})

test('invalid reviewer count stops before any agent', async () => {
  const { result, calls } = await runWorkflow({ args: { bundle: validBundle(1) } })
  assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
  assert.deepEqual(calls, [])
})

test('content hash mismatch stops before any agent', async () => {
  const bundle = validBundle()
  bundle.materials.rules.content += '\nforged rule'
  const { result, calls } = await runWorkflow({ args: { bundle } })
  assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
  assert.deepEqual(calls, [])
})

test('missing source HEAD and stale or future bundles stop before any agent', async t => {
  const cases = [
    ['missing source HEAD', bundle => { delete bundle.sourceHead }],
    ['malformed source HEAD', bundle => { bundle.sourceHead = '0'.repeat(64) }],
    ['stale timestamp', bundle => { bundle.generatedAt = new Date(Date.now() - 16 * 60 * 1000).toISOString() }],
    ['future timestamp', bundle => { bundle.generatedAt = new Date(Date.now() + 10 * 60 * 1000).toISOString() }],
  ]
  for (const [name, mutate] of cases) {
    await t.test(name, async () => {
      const bundle = validBundle()
      mutate(bundle)
      const { result, calls } = await runWorkflow({ args: { bundle } })
      assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
      assert.deepEqual(calls, [])
    })
  }
})

test('Stitch requirement is recomputed from task and spec', async t => {
  await t.test('WPF spec cannot claim Stitch is unnecessary', async () => {
    const bundle = validBundle()
    bundle.materials.spec = material('spec', '# Task\nBuild a WPF UI dashboard.\n')
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('desktop visual UI cannot claim Stitch is unnecessary', async () => {
    const bundle = validBundle()
    bundle.materials.spec = material(
      'spec',
      '# Task\nBuild a desktop visual UI for the operator dashboard.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('target-before-action desktop UI phrasing still requires Stitch', async () => {
    const bundle = validBundle()
    bundle.materials.spec = material(
      'spec',
      '# Task\nDesktop UI design for the operator dashboard.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('Stitch governance policy text is not treated as UI implementation', async () => {
    const bundle = validBundle()
    bundle.task = 'policy-update'
    bundle.materials.spec = material(
      'spec',
      '# Task\nRequire Google Stitch before Web UI or WPF/XAML design and lock the export before Agent dispatch.\n',
    )
    const { result } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, undefined)
  })

  await t.test('policy line cannot suppress UI implementation in the same spec', async () => {
    const bundle = validBundle()
    bundle.materials.spec = material(
      'spec',
      '# Task\nBuild a WPF UI dashboard.\nUpdate the policy to lock the Stitch export.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('same-line Stitch policy words cannot suppress UI implementation', async () => {
    const bundle = validBundle()
    bundle.materials.spec = material(
      'spec',
      '# Task\nUpdate the desktop UI design using Stitch and lock the export.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('restyle is treated as a visual implementation action', async () => {
    const bundle = validBundle()
    bundle.materials.spec = material(
      'spec',
      '# Task\nRestyle the desktop UI with new colors.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('Stitch-first wording cannot hide a later UI implementation clause', async () => {
    const bundle = validBundle()
    bundle.materials.spec = material(
      'spec',
      '# Task\nUpdate using Stitch and lock the export, then implement the WPF UI redesign.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('policy task name cannot suppress a Design-to-WPF clause', async () => {
    const bundle = validBundle()
    bundle.task = 'policy-and-dashboard-update'
    bundle.materials.spec = material(
      'spec',
      '# Task\nDesign a WPF UI dashboard.\nUpdate the Stitch policy to lock exports.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('policy task name cannot suppress target-before-action UI work', async () => {
    const bundle = validBundle()
    bundle.task = 'policy-and-dashboard-update'
    bundle.materials.spec = material(
      'spec',
      '# Task\nWPF UI redesign for the operator console.\nUpdate the Stitch policy to lock exports.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('same-line policy wording cannot suppress target-before-redesign work', async () => {
    const bundle = validBundle()
    bundle.task = 'policy-and-dashboard-update'
    bundle.materials.spec = material(
      'spec',
      '# Task\nRequire a locked Stitch export and a WPF UI redesign for the operator console.\n',
    )
    const { result, calls } = await runWorkflow({ args: { bundle } })
    assert.equal(result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(calls, [])
  })

  await t.test('required Stitch export must be present and hash-valid', async () => {
    const bundle = validBundle()
    bundle.materials.spec = material('spec', '# Task\nBuild a WPF UI dashboard.\n')
    bundle.stitchRequired = true
    let execution = await runWorkflow({ args: { bundle } })
    assert.equal(execution.result.hardStop, 'UNVERIFIED_INPUT_BUNDLE')
    assert.deepEqual(execution.calls, [])

    bundle.materials.stitchDesign = material(
      'stitch-design',
      '# Locked Stitch export\nDashboard layout.\n',
    )
    execution = await runWorkflow({ args: { bundle } })
    assert.equal(execution.result.hardStop, undefined)
  })
})

test('valid semantic packet reaches human gate with fixed safety state', async () => {
  const { result } = await runWorkflow()
  assert.equal(result.hardStop, undefined)
  assert.equal(result.reviewersRequested, 3)
  assert.equal(result.reviewersSucceeded, 3)
  assert.equal(result.reviewerQuorum, 2)
  assert.ok(result.humanGate)
  assert.match(result.humanGate.beforeExecuting_youMUST[0], /high-severity\/blocking/)
  assert.equal(result.sourceHead, 'b'.repeat(40))
  assert.equal(result.r5_human_verification, 'pending')
  assert.equal(result.merge_authorized, false)
})

test('schema-shaped empty plan is rejected semantically', async () => {
  const { result, calls } = await runWorkflow({
    handler: async (prompt, options, fallback) => options.label === 'plan'
      ? { ...validPlan(), files: [], executionOrder: [] }
      : fallback(prompt, options),
  })
  assert.equal(result.hardStop, 'PLAN_INVALID')
  assert.deepEqual(calls, ['plan'])
})

test('one reviewer exception is isolated when 3-reviewer quorum still passes', async () => {
  const { result } = await runWorkflow({
    handler: async (prompt, options, fallback) => {
      if (options.label === 'review#1') throw new Error('review exploded')
      return fallback(prompt, options)
    },
  })
  assert.equal(result.hardStop, undefined)
  assert.equal(result.reviewersSucceeded, 2)
  assert.equal(result.reviewFailures.length, 1)
})

test('one survivor out of four fails reviewer quorum', async () => {
  const { result, calls } = await runWorkflow({
    args: { bundle: validBundle(4) },
    handler: async (prompt, options, fallback) => {
      if (options.label.startsWith('review#') && options.label !== 'review#1') {
        throw new Error('review failed')
      }
      return fallback(prompt, options)
    },
  })
  assert.equal(result.hardStop, 'REVIEW_QUORUM_FAILED')
  assert.equal(result.reviewersSucceeded, 1)
  assert.equal(result.reviewerQuorum, 3)
  assert.equal(calls.includes('aggregate'), false)
})

test('parallel dispatch exception returns a structured hard stop', async () => {
  const { result } = await runWorkflow({
    parallel: async () => { throw new Error('dispatch failed') },
  })
  assert.equal(result.hardStop, 'REVIEW_DISPATCH_FAILED')
  assert.match(result.message, /dispatch failed/)
})

test('aggregate exception cannot flow into goal drafting', async () => {
  const { result, calls } = await runWorkflow({
    handler: async (prompt, options, fallback) => {
      if (options.label === 'aggregate') throw new Error('aggregate failed')
      return fallback(prompt, options)
    },
  })
  assert.equal(result.hardStop, 'AGG_FAILED')
  assert.equal(calls.includes('goal-draft'), false)
})

test('empty goal arrays and zero budgets are rejected', async () => {
  const { result } = await runWorkflow({
    handler: async (prompt, options, fallback) => options.label === 'goal-draft'
      ? {
          goalConditions: [], failBreakers: [], humanGates: [], gateChecklist: [],
          tokenCap: 0, maxTurns: 0,
        }
      : fallback(prompt, options),
  })
  assert.equal(result.hardStop, 'GOAL_INVALID')
  assert.equal(result.humanGate, undefined)
})

test('duplicate six-gate labels are rejected', async () => {
  const { result } = await runWorkflow({
    handler: async (prompt, options, fallback) => {
      if (options.label !== 'goal-draft') return fallback(prompt, options)
      const goal = validGoal()
      goal.gateChecklist[5].gate = 'GATE-5'
      return goal
    },
  })
  assert.equal(result.hardStop, 'GOAL_INVALID')
})

test('GATE-5 can never be auto-satisfied', async () => {
  const { result } = await runWorkflow({
    handler: async (prompt, options, fallback) => {
      if (options.label !== 'goal-draft') return fallback(prompt, options)
      const goal = validGoal()
      goal.gateChecklist.find(item => item.gate === 'GATE-5').autoSatisfiable = true
      return goal
    },
  })
  assert.equal(result.hardStop, 'GOAL_INVALID')
  assert.equal(result.r5_human_verification, 'pending')
  assert.equal(result.merge_authorized, false)
})

test('goal must retain an explicit positive R5 or human verification gate', async t => {
  const invalidHumanGates = [
    ['missing', ['none needed']],
    ['negated', ['no human verification required']],
  ]
  for (const [name, humanGates] of invalidHumanGates) {
    await t.test(name, async () => {
      const { result } = await runWorkflow({
        handler: async (prompt, options, fallback) => {
          if (options.label !== 'goal-draft') return fallback(prompt, options)
          return { ...validGoal(), humanGates }
        },
      })
      assert.equal(result.hardStop, 'GOAL_INVALID')
    })
  }
})
