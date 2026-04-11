/**
 * Bayesian adaptive level assessment, ported from swet_cli/assessment.py.
 *
 * Uses Item Response Theory (IRT 1PL) to estimate the user's competency
 * level through adaptive question selection.
 */

export const TOTAL_ASSESSMENT_QUESTIONS = 100;
export const PART1_QUESTIONS = 50;
export const PART2_QUESTIONS = 50;

const IRT_DISCRIMINATION = 1.5;

const LEVEL_PRIOR: Record<number, number> = {
	1: 0.10,
	2: 0.20,
	3: 0.40,
	4: 0.20,
	5: 0.10
};

export const LEVEL_ELO_MIDPOINTS: Record<number, number> = {
	1: 425.0,
	2: 975.0,
	3: 1225.0,
	4: 1475.0,
	5: 1800.0
};

/** Priors shaped by self-evaluation ratings */
export const SELF_RATING_PRIORS: Record<number, Record<number, number>> = {
	1: { 1: 0.45, 2: 0.30, 3: 0.15, 4: 0.07, 5: 0.03 }, // Beginner
	2: { 1: 0.15, 2: 0.35, 3: 0.30, 4: 0.15, 5: 0.05 }, // Some experience
	3: { 1: 0.10, 2: 0.20, 3: 0.40, 4: 0.20, 5: 0.10 }, // Comfortable
	4: { 1: 0.03, 2: 0.07, 3: 0.20, 4: 0.40, 5: 0.30 }, // Strong
	5: { 1: 0.02, 2: 0.05, 3: 0.13, 4: 0.30, 5: 0.50 }, // Expert
};

/** IRT 1PL probability of correct response */
export function irtProbability(abilityLevel: number, questionDifficulty: number): number {
	return 1.0 / (1.0 + Math.exp(-IRT_DISCRIMINATION * (abilityLevel - questionDifficulty)));
}

/** Bayesian estimator for a single competency's level */
export class BayesianLevelEstimator {
	posterior: Record<number, number>;
	questionsAsked: number = 0;

	constructor(prior?: Record<number, number>) {
		this.posterior = { ...(prior ?? LEVEL_PRIOR) };
	}

	/** Update posterior after observing a score */
	update(questionDifficulty: number, score: number): void {
		for (const level of [1, 2, 3, 4, 5]) {
			const pCorrect = irtProbability(level, questionDifficulty);
			const likelihood = pCorrect * score + (1.0 - pCorrect) * (1.0 - score);
			this.posterior[level] *= likelihood;
		}

		// Normalize
		const total = Object.values(this.posterior).reduce((a, b) => a + b, 0);
		if (total > 0) {
			for (const level of [1, 2, 3, 4, 5]) {
				this.posterior[level] /= total;
			}
		}

		this.questionsAsked++;
	}

	/** Pick optimal difficulty for next question */
	bestNextDifficulty(): number {
		const mapLevel = this.estimatedLevel();
		const confidence = this.posterior[mapLevel] ?? 0;

		if (confidence > 0.6 && mapLevel < 5) {
			return mapLevel + 1;
		}
		return mapLevel;
	}

	/** Maximum A Posteriori level estimate */
	estimatedLevel(): number {
		let maxProb = -1;
		let bestLevel = 3;
		for (const [level, prob] of Object.entries(this.posterior)) {
			if (prob > maxProb) {
				maxProb = prob;
				bestLevel = Number(level);
			}
		}
		return bestLevel;
	}

	/** Confidence (posterior probability of MAP estimate) */
	confidence(): number {
		return this.posterior[this.estimatedLevel()] ?? 0;
	}

	/** Human-readable distribution string */
	distributionStr(): string {
		return [1, 2, 3, 4, 5]
			.map((l) => `L${l}: ${Math.round(this.posterior[l] * 100)}%`)
			.join('  ');
	}
}
