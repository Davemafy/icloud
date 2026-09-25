# Master Sniper 6.5.90 / Sequence 3.42 Backtest Harness

Status: STAGING / DEMO-PAPER RESEARCH ONLY

This harness upgrades the old TESTER_FILE method so historical testing follows the
current Master Sniper Cloud logic instead of the older simplified zone generator.

## What is replayed

The generator uses the production `app.service.run_analysis` pipeline with an
explicit historical replay timestamp. It keeps the current:

- Master Sniper H4/H1 source-exact/tactical zoning rules
- DXY confirmation/context
- mitigation and publication lifecycle
- target revalidation
- thesis ownership and M1 location handoff logic
- trend/countertrend risk matrix
- A+ / A / B+ current execution grade
- HTF core / zone-sweep / liquidity-reversal execution authority
- Sniper contract fingerprint fields

Historical replay never calls a present-day AI model. It deliberately uses the same
PAPER-only deterministic provider-unavailable fallback already supported by the live
Cloud. This avoids contaminating an old period with a model trained on future data.

## Historical files

Put these files in one input folder:

```text
XAU_D1.csv
XAU_H4.csv
XAU_H1.csv
XAU_M15.csv
XAU_M1.csv
DXY_D1.csv
DXY_H4.csv
DXY_H1.csv
news.csv            # optional
```

The reader accepts normal comma/semicolon/tab CSV and standard MT5-style
`<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL>` headers.

Important: the files must contain history *before* the requested test start so the
system can satisfy its normal analysis windows (roughly one year D1, four months H4,
four weeks H1, and several trading days M15).

## Generate the tester files

Example:

```bash
python -m app.backtest \
  --input-dir historical_data \
  --start 2026-06-01T00:00:00+00:00 \
  --end 2026-08-31T23:59:00+00:00 \
  --out SMC_v659_tester_plans.csv
```

The command runs the replay in a disposable SQLite database and produces:

```text
SMC_v659_tester_plans.csv
SMC_v659_tester_plans_contract.csv
SMC_v659_tester_plans_metadata.json
```

The first file preserves the legacy 21-column MT5 geometry interface. The second is
the Sequence 3.42 sidecar contract containing the historical execution authority,
current grade, qualified mitigations, risk context, risk percentages, thesis key and
contract fingerprint. The metadata file records the replay contract and counts.

## No-lookahead rule

At replay time T:

- M1 is used only after that M1 bar has closed.
- M15/H1/H4/D1 bars are available only after their full timeframe has closed.
- Future news/price bars are never added to the analysis arrays.
- Every snapshot is stamped `HISTORICAL_REPLAY`.
- A hard assertion aborts the run if any analysis bar closes after replay time T.

## MT5 Strategy Tester

Copy both CSV files to:

```text
MT5 -> File -> Open Data Folder
then use the Terminal Common Files folder
```

Use the dedicated backtest EA:

```text
InstitutionalSMC_SequenceEA_v3_42_MasterSniper_Backtest_Demo
```

Settings:

- Symbol: XAUUSD
- Timeframe: M1
- Model: **Every tick based on real ticks**
- OperatingMode: TESTER_FILE
- TesterPlanFile: `SMC_v659_tester_plans.csv`
- TesterContractFile: `SMC_v659_tester_plans_contract.csv`
- Initial deposit: normally 10,000 for the current research risk matrix
- Use the same test dates as the generated replay

The backtest-only EA keeps the live Sequence 3.42 entry/re-entry/flip/management
logic but loads historical Cloud authority/risk/grade from the sidecar. It does not
modify the stable live 3.42 file.

## What should be judged

Do not start with P/L. Review in this order:

1. Did the historical Master Sniper zone exist without future information?
2. Was the contact from the correct side?
3. Did qualified mitigation counting stay correct?
4. Did current grade/risk change only when its rules required it?
5. Did M1 authority appear at the correct time?
6. Did Sequence wait for the full closed-M1 confirmation chain?
7. Did accepted invalidation stop the original thesis and handle the flip correctly?
8. Did position management continue normally?
9. Only then review win rate, expectancy, drawdown and P/L.

The final objective is a walk-forward test: fix defects on one historical period,
freeze the rules, then test a different unseen period without modifying the system.


## Integrated VPS workflow

After the backtest-lab release is deployed, use:

```text
TradeZone_MasterSniper_Backtest_Lab.bat
```

The lab deliberately reduces the whole preparation process to one guided Windows
workflow. It:

1. asks for test dates, XAU symbol, DXY symbol and replay spread;
2. compiles the no-trading history exporter and backtest-only Sequence 3.42 EA;
3. waits while you run the exporter once from MT5;
4. checks that all required XAU/DXY files exist;
5. uploads the ZIP to the authenticated `/validation/backtest/v659/replay` endpoint;
6. runs the production Master Sniper replay in a disposable Cloud process/database;
7. verifies the no-lookahead metadata;
8. places `SMC_v6_tester_plans.csv` and
   `SMC_v659_tester_plans_contract.csv` directly in MT5 Common Files;
9. creates a desktop Strategy Tester configuration using `Model=4`
   (Every tick based on real ticks).

The Cloud job is single-flight, authenticated with the same managed X-API-Key as the
EAs, limited to 120 days per run, bounded in upload/uncompressed size, and never
writes to the live snapshot, analysis or journal database.

Because the normal MT5 terminal may be running the live paper-validation charts, the
lab does not forcibly close or relaunch it. The generated desktop tester launcher
refuses no safety rules: use it only after the normal terminal is closed, or simply
open Strategy Tester manually in the existing terminal and use the prepared files.

The live stable payload remains 6.3.32 / DataBridge 1.51 / Sequence 3.42 throughout.
