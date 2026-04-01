/**
 * Auto-layout for config-driven P&ID topology nodes.
 * Assigns initial {x, y} positions based on position_hint zones.
 * Users can then drag nodes and save positions via /api/pid/layout.
 */

const FEED_COL_SPACING = 240
const FEED_ROW_SPACING = 110
const FEED_START_X = 40
const FEED_START_Y = 20

const REACTOR_Y = 520

const DRAIN_START_Y_OFFSET = 380  // below reactor
const DRAIN_ROW_SPACING = 110

const SIDE_OFFSETS = {
    left:       { dx: -180, dy: 40 },
    right:      { dx: 300, dy: 40 },
    bottom:     { dx: 0, dy: 240 },
    'top-right': { dx: 370, dy: -60 },
}

/**
 * Compute positions for all topology nodes.
 * @param {object[]} nodes - Nodes from /api/pid/topology with position_hint
 * @returns {object[]} Same nodes with position: {x, y} filled in
 */
export function autoLayout(nodes) {
    // Count feed columns to center the reactor
    const feedCols = nodes.filter(
        n => n.position_hint?.zone === 'feed' && (n.position_hint?.rank ?? 0) === 0
    )
    const numFeedCols = Math.max(feedCols.length, 1)
    const reactorX = FEED_START_X + ((numFeedCols - 1) * FEED_COL_SPACING) / 2
    const reactorPos = { x: reactorX, y: REACTOR_Y }

    // Track side instrument offsets per hint direction
    const sideCounters = {}

    return nodes.map(n => {
        const hint = n.position_hint || {}

        let pos
        switch (hint.zone) {
            case 'center':
                pos = { ...reactorPos }
                break

            case 'feed': {
                const col = hint.column ?? 0
                const rank = hint.rank ?? 0
                pos = {
                    x: FEED_START_X + col * FEED_COL_SPACING,
                    y: FEED_START_Y + rank * FEED_ROW_SPACING,
                }
                break
            }

            case 'drain': {
                const rank = hint.rank ?? 0
                pos = {
                    x: reactorX + 20,
                    y: REACTOR_Y + DRAIN_START_Y_OFFSET + rank * DRAIN_ROW_SPACING,
                }
                break
            }

            case 'jacket':
                pos = { x: reactorX - 210, y: REACTOR_Y + 310 }
                break

            case 'agitator':
                pos = { x: reactorX + 370, y: REACTOR_Y + 310 }
                break

            case 'side': {
                const direction = hint.hint || 'right'
                const offset = SIDE_OFFSETS[direction] || SIDE_OFFSETS.right
                const counter = sideCounters[direction] || 0
                sideCounters[direction] = counter + 1
                pos = {
                    x: reactorX + offset.dx,
                    y: REACTOR_Y + offset.dy + counter * 100,
                }
                break
            }

            default:
                pos = { x: 400, y: 400 }
        }

        return { ...n, position: pos }
    })
}
