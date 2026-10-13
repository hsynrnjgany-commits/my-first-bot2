WORLD MARKET CORE

Global Market Intelligence | Market DNA | Toobit Hunter

Project Codename: Termite / Shadow Hunter
Core Mission: Global Multi-Market Intelligence and Quantitative Research
Primary Domain: Cryptocurrency Markets
Research Scope: Market Structure, Liquidity, AMD, Volume Profile, Market Regimes, Cross-Symbol Relationships, Quantitative Validation, and Risk Analysis.

Current Operational Mode: READ ONLY · PAPER ONLY · NO LIVE TRADING

---

1. PROJECT VISION

World Market Core is a research-driven market intelligence architecture designed to identify, analyze, classify, and validate recurring patterns and structural behaviors across global financial markets.

The objective is to develop a modular analytical system that goes beyond conventional indicator-based trading bots.

Rather than relying on isolated indicators or simplistic buy/sell rules, the system is designed to study the relationships between:

- Price action and market structure.
- Liquidity distribution and liquidity events.
- Accumulation, Manipulation, and Distribution (AMD).
- Volume Profile and value-area behavior.
- Market sessions and time-dependent behavior.
- Multi-timeframe market structure.
- Volatility and market regimes.
- Cross-symbol and cross-market relationships.
- Forward returns and event-based outcomes.
- Transaction costs, slippage, and execution constraints.
- Statistical stability and out-of-sample performance.

The long-term objective is to build a scalable, multi-layered market intelligence engine capable of researching thousands of market instruments without assuming that a pattern observed in one asset will work in another.

The project prioritizes verified evidence, reproducibility, statistical robustness, and capital preservation over signal quantity or backtest performance alone.

---

2. CORE PRINCIPLES

All project development must follow these principles.

2.1 Evidence Before Conclusions

No strategy, pattern, feature, or model should be considered reliable solely because it produces a high historical profit factor or an attractive backtest.

Every material conclusion must be supported by traceable data, reproducible calculations, and appropriate validation.

2.2 Read-Only Research

Forensic investigations must not modify, overwrite, delete, or silently regenerate original datasets.

New research outputs must be written to separate locations when output generation is authorized.

2.3 Paper-Only Operation

Real-money trading and live order execution remain disabled.

The project must not submit live orders, modify exchange positions, or treat research signals as authorization to trade.

2.4 No Look-Ahead Bias

Historical features must only use information available at the relevant decision time.

Forward-return labels may be used for evaluation, but must never leak into historical signal generation or feature selection.

2.5 Out-of-Sample Validation

Patterns must be tested on data that was not used to discover or optimize them.

A promising in-sample result is a research candidate, not proof of a persistent market edge.

2.6 Reproducibility

Every important result should be traceable to:

- Its source dataset.
- Its input row keys.
- Its feature definitions.
- Its calculation formula.
- Its filtering rules.
- Its time boundaries.
- Its validation method.
- Its software version or script, when available.

Missing evidence must be reported explicitly rather than reconstructed through unsupported assumptions.

---

3. SYSTEM ARCHITECTURE

The intended analytical architecture consists of independent modules connected through standardized data contracts.

Layer 1 — Market Data Infrastructure

Collect and organize market data from supported exchanges and instruments.

Required capabilities:

- Symbol discovery.
- OHLCV collection.
- Timestamp normalization.
- Data completeness checks.
- Duplicate detection.
- Missing-value detection.
- Market and instrument classification.
- Liquidity and tradability assessment.
- Historical data partitioning.
- Source and collection-time tracking.

Initial emphasis is on cryptocurrency spot and futures markets.

Future expansion may include additional exchanges, foreign exchange, and other supported financial instruments where reliable data is available.

Layer 2 — Market DNA

Transform raw market data into measurable descriptions of market behavior.

Potential features include:

- Candle body and wick structure.
- Relative candle range.
- Returns across multiple horizons.
- Volatility characteristics.
- Directional transitions.
- Consecutive candle behavior.
- Session-dependent behavior.
- Structural changes.
- Cross-symbol breadth.
- Historical event classifications.

Every feature must have a documented definition and a clear timestamp policy.

Layer 3 — Liquidity Intelligence

Research how price interacts with liquidity-related structures.

Areas of investigation include:

- Previous highs and lows.
- Liquidity sweeps.
- Breakouts and failed breakouts.
- Range expansion.
- Local structural levels.
- Volume Profile.
- Value-area behavior.
- High-volume and low-volume areas.
- Potential liquidity cascades.

These classifications must be treated as measurable research hypotheses rather than automatically accepted explanations of market behavior.

Layer 4 — AMD and Session Intelligence

Study Accumulation, Manipulation, and Distribution in relation to market sessions and structural context.

Relevant dimensions include:

- Session classification.
- Previous-session highs and lows.
- Session ranges.
- Sweep direction.
- Range expansion.
- Structural transitions.
- Time-dependent outcomes.
- Market-regime interactions.

A pattern must demonstrate repeatable statistical behavior before being promoted to a validated research candidate.

Layer 5 — Market Regime Intelligence

Classify market conditions using reproducible features.

Potential regimes include:

- Low volatility.
- High volatility.
- Directional trends.
- Ranging markets.
- Expanding volatility.
- Contracting volatility.
- Strong or weak cross-symbol breadth.

Regime classifications must be derived from information available at the relevant time.

Thresholds must be documented, and any optimized thresholds must be validated on independent data.

Layer 6 — Event Engine

Represent market behavior as structured events rather than isolated indicator readings.

Each event should have a defined:

- Event type.
- Timestamp.
- Symbol.
- Market context.
- Trigger condition.
- Reference levels.
- Relevant features.
- Forward evaluation horizons.
- Outcome status.

The event engine must distinguish between confirmed outcomes, ambiguous outcomes, incomplete observations, and invalid observations.

Layer 7 — Cross-Symbol Intelligence

Investigate whether a market behavior is isolated or shared across multiple instruments.

Required research dimensions include:

- Number of symbols tested.
- Percentage of symbols with positive outcomes.
- Percentage with profit factor above 1.0.
- Percentage with profit factor above defined quality thresholds.
- Cross-symbol return dispersion.
- Performance concentration.
- Correlation and dependence.
- Market breadth.
- Stability across time windows.

A result driven by one or two instruments must not be presented as a universal market effect.

Layer 8 — State Transition Engine

Model transitions between discrete market states.

The research process should investigate:

- Initial state.
- Subsequent state.
- Transition frequency.
- Forward outcomes.
- Horizon dependence.
- Market-regime dependence.
- Cross-symbol reproducibility.
- Out-of-sample persistence.

State identifiers and transition definitions must remain consistent across datasets and validation stages.

Layer 9 — Forward Outcome Evaluation

Evaluate events across predefined forward horizons.

Initial research horizons:

- FWD3
- FWD6
- FWD12

The exact interpretation of each horizon must be documented in the corresponding dataset specification.

Required controls:

- Correct symbol and timestamp alignment.
- Correct forward-window boundaries.
- Incomplete-horizon detection.
- No future-data leakage.
- Consistent return definitions.
- Explicit handling of missing observations.
- Reproducible outcome calculations.

Layer 10 — Walk-Forward Validation

Use chronological validation to evaluate whether a discovered relationship persists outside its development window.

The research framework uses the following general structure:

- W1 → W2
- W2 → W3
- W3 → W4

Training and test periods must remain temporally ordered.

A pattern must not be selected using the results of the same test period that is subsequently presented as independent validation.

Where feasible, an additional untouched holdout should be preserved for final evaluation.

Layer 11 — Quantitative Ranking

Rank research candidates using multiple dimensions rather than a single performance statistic.

Candidate evaluation may include:

- Number of events.
- Number of symbols.
- Win rate.
- Profit factor.
- Average return.
- Cumulative return.
- Maximum drawdown.
- MFE and MAE.
- Cross-symbol breadth.
- Walk-forward consistency.
- Regime stability.
- Transaction-cost sensitivity.
- Liquidity constraints.
- Performance concentration.

A high ranking does not automatically authorize deployment.

Layer 12 — Risk and Paper Execution

The eventual system may connect validated research outputs to a paper-trading layer.

Before a candidate can advance, the project must establish:

- Defined entry and exit rules.
- Position-sizing rules.
- Portfolio exposure limits.
- Liquidity requirements.
- Fee and slippage assumptions.
- Drawdown controls.
- Failure handling.
- Independent validation.
- Paper-execution monitoring.

Live execution remains disabled.

---

4. RESEARCH PIPELINE

The intended end-to-end workflow is:

1. Discover supported instruments.
2. Collect and normalize historical data.
3. Validate data integrity.
4. Generate Market DNA features.
5. Classify structural and liquidity events.
6. Add session, AMD, Volume Profile, and regime context.
7. Generate candidate state transitions.
8. Calculate forward outcomes.
9. Validate event and symbol alignment.
10. Evaluate cross-symbol breadth.
11. Perform chronological walk-forward testing.
12. Measure performance stability.
13. Test fees and slippage.
14. Assess concentration and drawdown.
15. Rank candidates using predefined criteria.
16. Generate paper-only research signals.
17. Monitor paper performance.
18. Promote candidates only after independent validation.

Every stage must have explicit input and output contracts.

A downstream stage must not silently change the meaning of an upstream feature or metric.

---

5. STATISTICAL VALIDATION STANDARD

The project must report more than a profit factor.

For each relevant candidate, the research record should contain:

Metric| Purpose
N| Number of evaluated observations
Symbols| Number of distinct instruments
Win Rate| Percentage of positive outcomes
Profit Factor| Gross positive returns divided by absolute gross negative returns, under a documented calculation convention
Average Return| Mean return per evaluated observation
Cumulative Return| Aggregate performance under a clearly defined aggregation method
Maximum Drawdown| Largest peak-to-trough decline under a documented equity-curve convention
MFE| Maximum Favorable Excursion
MAE| Maximum Adverse Excursion
WFO| Walk-forward performance
OOS| Out-of-sample performance
Holdout| Performance on untouched evaluation data
Breadth| Distribution of results across instruments
Stability| Consistency across periods and market regimes
Fee Stress| Sensitivity to transaction costs
Slippage Stress| Sensitivity to execution assumptions
Concentration| Dependence on individual symbols or observations

Metrics must be defined consistently.

In particular, a mean of individual trade returns, a compounded portfolio return, and a profit factor calculated from aggregate trade returns are different quantities and must not be treated as interchangeable.

When the number of observations is insufficient, the result must be labeled inconclusive rather than reliable.

---

6. FORENSIC DATA LINEAGE

Data lineage is a first-class component of the project.

Every important dataset should have a documented relationship to its source.

A lineage investigation must answer:

1. Which source dataset produced the target dataset?
2. Which script or process generated it?
3. Which rows were included or excluded?
4. Which filters were applied?
5. Which features were recalculated?
6. Which formulas were used?
7. Which rows were lost through missing values?
8. Were incomplete forward horizons handled consistently?
9. Were duplicate keys introduced or removed?
10. Can the reported statistics be independently reproduced?

If the original producer script is unavailable, the investigation must distinguish between verified facts and hypotheses.

A matching output does not, by itself, prove that the original generation process has been recovered.

A numerical mismatch does not, by itself, identify the exact cause.

Possible causes must be tested against the available evidence.

---

7. CURRENT PROJECT STATUS

The project is currently in the Market DNA forensic verification and reproducibility phase.

Historical datasets and derived research outputs are being examined to establish reliable source-to-output lineage.

Current work includes:

- P14 candle-feature lineage.
- P34 prepared-data consistency.
- Forward-return alignment.
- Cross-symbol breadth calculations.
- State-transition statistics.
- Walk-forward result verification.
- D8M and D8N metric comparison.
- P147D regime-survival investigation.
- P147E transaction-cost stress investigation.
- Producer-script discovery.
- Reproduction of previously reported statistics.

The current investigation includes the following unresolved questions.

7.1 D8M / D8N Metric Lineage

The available D8M and D8N metric tables contain 1,217 rows each.

The observed metric values match, but the original producer code has not yet been recovered.

A key discrepancy involves 1INCHUSDT in W1, where the D8N result reports N=762 while the raw comparison reports N=763.

This requires source-level verification before the difference can be explained conclusively.

7.2 P147D Regime Survival

A reported P147D result for transition 02200→02200, W1→W2, H3, BREADTH LOW, contains N=29 and PF approximately 29.98.

An independent reconstruction using the currently available evidence reproduces N=29 but calculates PF approximately 1.294.

The matching observation count does not establish that the underlying returns, filters, or profit-factor formula match.

The original producer logic and return source remain subjects of investigation.

7.3 P147E Fee Stress

The available P147E dataset contains 252 rows.

The observed transition groups include:

- 02200→02200
- 21100→02200

The dataset includes multiple regime classifications and transaction-cost assumptions.

Its calculations must be traced to the original event returns and verified before the results are treated as authoritative.

7.4 Producer Recovery

The original producer scripts for some D8M and P147D outputs have not been found in the available project evidence.

The investigation must continue through source inventories, audit traces, formulas, schemas, and reproducible comparisons.

No unresolved discrepancy should be silently corrected or declared resolved without sufficient evidence.

---

8. DATASET INTEGRITY AND VERSION CONTROL

Every research dataset should be associated with a minimal manifest.

Recommended fields:

- Dataset name.
- Dataset version.
- Creation timestamp.
- Source file names.
- Source hashes, where available.
- Row count.
- Column count.
- Unique symbol count.
- Minimum and maximum timestamps.
- Missing-value counts.
- Duplicate-key counts.
- Applied filters.
- Feature definitions.
- Forward-horizon definitions.
- Producer script.
- Validation status.
- Known discrepancies.

Dataset versions should be immutable once used as an official research reference.

Corrections should create a new version with a documented change history.

Original evidence must remain available for comparison.

---

9. REPOSITORY STRUCTURE

The following is the intended repository structure. It describes the planned organization and does not imply that every component has already been implemented.

world-market-core/
│
├── README.md
│
├── docs/
│   ├── architecture.md
│   ├── research_methodology.md
│   ├── data_dictionary.md
│   ├── validation_protocol.md
│   ├── data_lineage.md
│   └── project_status.md
│
├── research/
│   ├── market_dna/
│   ├── liquidity/
│   ├── amd_sessions/
│   ├── volume_profile/
│   ├── regimes/
│   └── cross_symbol/
│
├── validation/
│   ├── data_integrity/
│   ├── forward_returns/
│   ├── walk_forward/
│   ├── out_of_sample/
│   └── transaction_costs/
│
├── forensic/
│   ├── producer_trace/
│   ├── source_audits/
│   ├── reconciliation/
│   └── discrepancy_reports/
│
├── manifests/
│   └── dataset_manifests/
│
├── tests/
│   ├── test_data_integrity.py
│   ├── test_forward_alignment.py
│   └── test_metric_reconciliation.py
│
└── reports/
    └── research_reports/

This structure should be implemented incrementally.

Existing datasets must not be moved or modified merely to conform to the proposed layout.

Large raw datasets should remain outside version control unless their inclusion is explicitly justified.

---

10. DEVELOPMENT ENVIRONMENT

The initial development environment is Android with Pydroid 3.

Research scripts should therefore favor:

- Clear and concise Python.
- Small, independently executable modules.
- Explicit input paths.
- Read-only source access.
- Memory-conscious processing.
- Incremental validation.
- Plain-text reports.
- CSV-based evidence when appropriate.
- Simple error messages.
- Reproducible output formats.

Scripts should avoid unnecessarily loading large datasets multiple times.

Every forensic script should clearly identify its operational mode and expected behavior.

Recommended script header:

PROJECT: WORLD MARKET CORE
MODE: READ ONLY
EXECUTION: PAPER ONLY
LIVE ORDERS: DISABLED
SOURCE MODIFICATION: PROHIBITED
PURPOSE: RESEARCH / FORENSIC VERIFICATION

No script should claim successful validation unless the relevant checks have actually executed and passed.

---

11. AI AND MACHINE LEARNING POLICY

Artificial intelligence and machine learning may eventually support:

- Feature discovery.
- Pattern classification.
- Regime identification.
- Anomaly detection.
- Cross-market relationship discovery.
- Candidate prioritization.
- Research automation.

However, complexity alone is not evidence of value.

A machine-learning model must demonstrate incremental performance relative to a clearly defined baseline.

Evaluation should include:

- Chronological train/test separation.
- Leakage controls.
- Out-of-sample comparison.
- Stability analysis.
- Feature-importance limitations.
- Model-selection bias.
- Transaction-cost sensitivity.
- Reproducibility.

A model that does not demonstrate meaningful out-of-sample improvement should not be promoted merely because it is more sophisticated.

---

12. FUTURE MULTI-EXCHANGE EXPANSION

The long-term architecture is intended to support multiple exchanges and thousands of instruments.

Expansion must be based on data quality and computational feasibility rather than symbol count alone.

Potential future integrations include:

- Spot market data.
- Futures market data.
- Funding rates.
- Open interest.
- Liquidation data.
- Long/short positioning measures.
- Basis and premium.
- Cross-exchange price differences.
- Market-wide liquidity conditions.

These features must remain unavailable or explicitly marked missing until reliable data sources and validated collection procedures exist.

The system must never fabricate missing market information.

Exchange-specific differences must be handled through standardized data contracts.

---

13. RESEARCH PROMOTION GATES

A research candidate must pass progressively stricter evaluation stages.

Gate 1 — Data Integrity

Source data, timestamps, symbol keys, missing values, and calculations are verified.

Gate 2 — Reproducibility

An independent calculation reproduces the relevant metrics within documented numerical tolerances.

Gate 3 — Statistical Adequacy

Observation counts and symbol coverage are sufficient for the intended claim.

Gate 4 — Out-of-Sample Performance

The candidate demonstrates performance on data not used for its discovery or optimization.

Gate 5 — Walk-Forward Stability

The result remains sufficiently robust across chronological test windows.

Gate 6 — Cost and Liquidity Stress

Fees, slippage, liquidity limitations, and plausible execution constraints are incorporated.

Gate 7 — Risk Review

Drawdown, concentration, adverse excursion, and failure scenarios are assessed.

Gate 8 — Paper Validation

The candidate is monitored without real-money execution.

Passing one gate does not imply passing the next.

The acceptance criteria must be documented before evaluating the final results whenever practical.

---

14. SECURITY AND OPERATIONAL SAFETY

The repository must follow basic security practices.

- Never commit exchange API secrets.
- Never commit passwords, private keys, or recovery phrases.
- Do not place sensitive account information in research logs.
- Keep live trading credentials separate from the research environment.
- Do not enable real order execution in forensic scripts.
- Do not execute unverified scripts against original project data.
- Do not overwrite original research evidence.
- Review dependencies before installing them.
- Record the source and purpose of imported code.

The default operational policy remains:

READ ONLY — PAPER ONLY — NO LIVE TRADING.

---

15. PROJECT GOVERNANCE

Each substantial change should include:

1. A unique task identifier.
2. A clear research question.
3. The files examined.
4. The exact checks performed.
5. The results obtained.
6. Any unresolved discrepancies.
7. A statement confirming whether source files were modified.
8. The next required verification step.

Research reports must separate:

- Verified facts.
- Reproduced results.
- Observed discrepancies.
- Plausible explanations.
- Unverified hypotheses.
- Final conclusions.

A discrepancy is not a failure of the research process.

Failing to disclose a discrepancy is.

---

16. PROJECT ROADMAP

Phase A — Forensic Foundation

- Establish source-to-output lineage.
- Recover original producer logic where possible.
- Reconcile D8M, D8N, P147D, and P147E calculations.
- Verify forward-return construction.
- Document unresolved discrepancies.
- Establish reproducible research manifests.

Phase B — Market DNA Standardization

- Formalize feature definitions.
- Standardize symbol and timestamp keys.
- Document missing-value policies.
- Build reusable integrity checks.
- Establish dataset versioning.

Phase C — Quantitative Validation

- Standardize forward-return evaluation.
- Formalize walk-forward testing.
- Add untouched holdout procedures.
- Establish minimum sample requirements.
- Validate cross-symbol breadth.
- Incorporate fees and slippage.

Phase D — Research Engine

- Organize Market DNA features into independent modules.
- Develop structured event definitions.
- Integrate AMD, session, liquidity, and regime context.
- Build reproducible candidate rankings.

Phase E — Paper Research

- Generate research signals from validated candidates.
- Monitor forward outcomes.
- Evaluate risk and performance concentration.
- Compare paper results with historical expectations.

Phase F — Scalable Market Intelligence

- Expand supported instruments.
- Add additional exchanges.
- Integrate futures-specific data where available.
- Develop cross-market analytical relationships.
- Evaluate machine-learning components against established baselines.

Progression between phases depends on verification results, not deadlines.

---

17. PROJECT SUCCESS CRITERIA

The project should be evaluated by the quality and reliability of its research infrastructure, not by the number of generated signals.

Core success criteria:

- Reproducible calculations.
- Traceable data lineage.
- Consistent metric definitions.
- Strict prevention of look-ahead bias.
- Independent out-of-sample validation.
- Cross-symbol robustness.
- Explicit treatment of transaction costs.
- Transparent risk measurements.
- Versioned and auditable datasets.
- Reliable paper-only operation.
- Clear separation between evidence and hypotheses.

The ultimate objective is to determine whether a discovered market behavior represents a persistent, economically meaningful, and realistically testable statistical relationship.

No strategy is guaranteed to remain profitable.

---

18. CONTRIBUTION AND RESEARCH STANDARDS

Contributions should prioritize correctness, reproducibility, and transparency.

Every new research module should document:

- Its objective.
- Its required inputs.
- Its output schema.
- Its formulas.
- Its assumptions.
- Its limitations.
- Its tests.
- Its validation status.

Changes to established calculations must be documented and independently checked.

Unverified improvements should remain experimental until they pass the relevant validation gates.

---

19. DISCLAIMER

World Market Core is a quantitative research and software-development project.

Its analytical outputs are experimental research results, not guarantees of future market performance or personalized financial advice.

Historical performance may not persist under changing market conditions.

Data quality, transaction costs, liquidity, execution constraints, model-selection bias, and statistical uncertainty can materially affect results.

The project does not authorize live trading.

All current forensic research must preserve original evidence and operate under the READ ONLY / PAPER ONLY policy.

---

FINAL STATEMENT

World Market Core is designed to build market intelligence from verified evidence rather than assumptions.

Its foundation is data integrity.

Its methodology is quantitative validation.

Its architecture is modular and scalable.

Its objective is to discover market relationships that survive independent testing.

Its operational principle is strict separation between research, validation, and execution.

Verify the data. Trace the source. Reproduce the result. Test out of sample. Measure the risk. Only then consider promotion.
