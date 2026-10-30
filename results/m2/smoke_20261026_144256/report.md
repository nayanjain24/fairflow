# FairFlow M2 Scenario A Report: scenario_a_baselines

- **Run ID**: `smoke_20261026_144256`
- **Mode**: `smoke`
- **Timestamp UTC**: `2026-10-26T14:45:48.358089+00:00`
- **Kernel**: `Linux 6.8 (Ubuntu 24.04 aarch64)`
- **TCP Congestion Control**: `cubic`
- **Contract SHA256**: `04893b27e604b38cd0fb0e6267b307d2f05447fcde333fd73f1743b9d5a499a8`

## 1. Primary & Secondary Metrics Summary

| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |
|---|---|---|---|---|---|---|---|---|---|
| `R0_no_qos` | 2/2 | **0/2** | 194.60 | 1.39 | [193.213, 195.984] | 0.007 | 95.21 | 95.20% | 0.00% |
| `B1_static_htb` | 2/2 | **2/2** | 11.04 | 5.79 | [5.247, 16.827] | 0.525 | 90.71 | 90.70% | 0.00% |
| `B2a_fq_codel` | 2/2 | **2/2** | 0.00 | 0.00 | [0.0, 0.0] | 0.000 | 87.56 | 87.60% | 0.00% |
| `B2b_cake` | 2/2 | **2/2** | 0.00 | 0.00 | [0.0, 0.0] | 0.000 | 87.44 | 87.40% | 0.00% |

## 2. Safety Contract Adherence

| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |
|---|---|---|---|
| `R0_no_qos` | FAIL (194.60 ms) | PASS (95.21 Mbps) | **NON-COMPLIANT** |
| `B1_static_htb` | PASS (11.04 ms) | PASS (90.71 Mbps) | **COMPLIANT** |
| `B2a_fq_codel` | PASS (0.00 ms) | PASS (87.56 Mbps) | **COMPLIANT** |
| `B2b_cake` | PASS (0.00 ms) | PASS (87.44 Mbps) | **COMPLIANT** |
