/**
 * Jacket or umbrella, decided here rather than on the server.
 *
 * A deliberate twin of `decide()` in backend/jarvis/providers/weather.py, and
 * the duplication is the point. The API answers with forecast *facts* — the
 * coldest hour you have left today, the wettest — because that response is
 * cached on rounded coordinates and shared by everyone standing near that
 * rounding, so it cannot carry one visitor's idea of what counts as cold.
 *
 * The payoff is that moving the slider re-decides instantly and offline. The
 * price is that these two functions must agree; if you change one, change the
 * other, and keep the guard on `wettest_at` in both.
 */

export interface AdviceFacts {
  coldest_apparent: number | null
  coldest_at: string | null
  max_probability: number
  wettest_at: string | null
  through: string | null
  spans_tomorrow: boolean
}

export interface Advice {
  jacket: { needed: boolean; apparent: number | null; at: string | null; below: number }
  umbrella: { needed: boolean; probability: number; at: string | null; threshold: number }
  headline: string
  through: string | null
  spans_tomorrow: boolean
}

function headline(jacket: boolean, umbrella: boolean): string {
  if (jacket && umbrella) return 'Take a jacket and an umbrella'
  if (jacket) return 'Take a jacket'
  if (umbrella) return 'Take an umbrella'
  return 'Nothing to take'
}

export function decide(facts: AdviceFacts, jacketBelow: number, rainThreshold: number): Advice {
  const cold = facts.coldest_apparent
  const jacket = cold !== null && cold <= jacketBelow
  // `wettest_at !== null` stands in for "the window had any hours in it at all".
  // Without it a threshold of 0 against an empty window reads 0 >= 0 and
  // recommends an umbrella on no data.
  const umbrella = facts.wettest_at !== null && facts.max_probability >= rainThreshold

  return {
    // Rounded for display only. The comparison above is against the unrounded
    // value, because 14.4 with a threshold of 14 is not a jacket.
    jacket: {
      needed: jacket,
      apparent: cold === null ? null : Math.round(cold),
      at: facts.coldest_at,
      below: jacketBelow,
    },
    umbrella: {
      needed: umbrella,
      probability: facts.max_probability,
      at: facts.wettest_at,
      threshold: rainThreshold,
    },
    headline: headline(jacket, umbrella),
    through: facts.through,
    spans_tomorrow: facts.spans_tomorrow,
  }
}
